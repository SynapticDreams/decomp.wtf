"""Validate and materialize captured includes without reading live compiler dependencies."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import tempfile

from .sms_resplit_dependencies import DependencyError, VERSION, MAX_BYTES, MAX_FILES, MAX_NODES, MAX_DEPTH, MAX_ROOTS, MAX_FILE


def recipe(snapshot, settings, unit):
    """An old snapshot with configured includes has no proof of their historical contents."""
    if not settings.get('include_dirs'):
        return None, []
    bundle = snapshot.get('inputs', {}).get('compiler_dependencies')
    if not isinstance(bundle, dict) or type(bundle.get('version')) is not int or bundle['version'] != VERSION:
        raise DependencyError('compiler includes need a captured dependency context before automatic revalidation')
    recipes = bundle['recipes']
    selected = recipes['units'].get(unit, recipes['default'])
    indices = selected['indices']
    if (selected['configured'] != list(settings['include_dirs']) or not isinstance(indices, list)
            or len(indices) != len(settings['include_dirs'])):
        raise DependencyError('captured compiler dependency recipe differs from the selected unit')
    return bundle, indices


def extra_inputs(settings):
    if settings.get('toolchain') != 'gbdk-2020' or settings.get('cmd'):
        return True
    flags = settings.get('flags') or []
    if not isinstance(flags, list):
        return True
    # Additional paths/response files can read inputs outside the configured, captured include trees.
    return any(re.match(r'(?:@|-I|-L|-l|--?include|--?preinclude|-Wp,|--lib-path|-isystem|-iquote|-idirafter|--?sysroot|--peep-file)', str(flag)) for flag in flags)


def _path(root, name):
    if not isinstance(name, str):
        raise DependencyError('captured compiler dependency path is malformed')
    parts = PurePosixPath(name).parts
    target = root.joinpath(*parts).resolve()
    if not parts or len(parts) > MAX_DEPTH or any(part in ('.', '..') for part in parts) or not target.is_relative_to(root):
        raise DependencyError('captured compiler dependency path escapes its private directory')
    return target


def _metadata(path, values):
    if type(values['mode']) is not int or type(values['mtime_ns']) is not int:
        raise DependencyError('captured compiler dependency metadata is malformed')
    os.chmod(path, values['mode'] & 0o777)
    os.utime(path, ns=(values['mtime_ns'], values['mtime_ns']))


def _write(snapshot, settings, unit, base):
    bundle, indices = recipe(snapshot, settings, unit)
    if bundle is None:
        return ()
    directories = bundle['directories']
    if not isinstance(directories, list) or len(directories) > MAX_ROOTS:
        raise DependencyError('captured compiler dependency directory budget exceeded')
    paths, size, count, nodes = {}, 0, 0, 0
    for index in dict.fromkeys(indices):
        if type(index) is not int or not 0 <= index < len(directories):
            raise DependencyError('captured compiler dependency directory is unavailable')
        entry, root = directories[index], base / str(index)
        if not entry['exists']:
            paths[index] = str(root)  # Ordinary gb_build skips an absent directory.
            continue
        root.mkdir()
        nodes += 1
        for name in entry['directories']:
            nodes += 1
            if nodes > MAX_NODES:
                raise DependencyError('captured compiler dependency traversal budget exceeded')
            _path(root, name).mkdir(parents=True, exist_ok=True)
        for file in entry['files']:
            count += 1
            nodes += 1
            data = file['content']
            size += len(data)
            if count > MAX_FILES or nodes > MAX_NODES or len(data) > MAX_FILE or size > MAX_BYTES or hashlib.sha256(data).hexdigest() != file['sha256']:
                raise DependencyError('captured compiler dependency content or budget differs')
            path = _path(root, file['path'])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            _metadata(path, file)
        for name in sorted(entry['directory_metadata'], key=lambda value: value.count('/') + bool(value), reverse=True):
            _metadata(_path(root, name) if name else root, entry['directory_metadata'][name])
        paths[index] = str(root)
    return tuple(paths[index] for index in indices)


@contextmanager
def materialize(snapshot, settings, unit):
    with tempfile.TemporaryDirectory(prefix='sms-includes-') as temporary:
        try:
            paths = _write(snapshot, settings, unit, Path(temporary).resolve())
        except DependencyError:
            raise
        except (KeyError, TypeError, ValueError, OSError):
            raise DependencyError('captured compiler dependency context is malformed or unavailable') from None
        yield paths
