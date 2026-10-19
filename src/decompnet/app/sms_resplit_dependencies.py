"""Capture configured SMS/GG compiler include trees; private snapshot data, never public report content."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from ..network import NetworkError
from ..project import compiler_settings

VERSION = 1
MAX_BYTES = 32 << 20
MAX_FILE = 4 << 20
MAX_FILES = 8192
MAX_NODES = 16384
MAX_DEPTH = 64
MAX_ROOTS = 64
MAX_RECIPES = 1024


class DependencyError(ValueError):
    pass


class Budget:
    def __init__(self):
        self.bytes = self.files = self.nodes = 0

    def node(self, depth):
        self.nodes += 1
        if self.nodes > MAX_NODES or depth > MAX_DEPTH:
            raise DependencyError('compiler dependency traversal budget exceeded')

    def read(self, path):
        self.files += 1
        if self.files > MAX_FILES:
            raise DependencyError('compiler dependency file budget exceeded')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise DependencyError('compiler dependency is not a regular file')
            limit = min(MAX_FILE, MAX_BYTES - self.bytes)
            data = stream.read(limit + 1)
            self.bytes += len(data)
            if len(data) > limit:
                raise DependencyError('compiler dependency byte budget exceeded')
            return data, {'mode': stat.S_IMODE(info.st_mode), 'mtime_ns': info.st_mtime_ns}


def _tree(path, budget):
    result = {'exists': path.exists(), 'directories': [], 'directory_metadata': {}, 'files': []}
    if not result['exists']:
        return result  # gb_build skips absent include roots, including dangling root aliases.

    def visit(directory, relative, parents, depth):
        info = directory.stat()
        identity = (info.st_dev, info.st_ino)
        if not stat.S_ISDIR(info.st_mode) or identity in parents:
            raise DependencyError('compiler dependency directory is invalid or cyclic')
        key = '' if relative == Path() else relative.as_posix()
        result['directory_metadata'][key] = {'mode': stat.S_IMODE(info.st_mode), 'mtime_ns': info.st_mtime_ns}
        entries = []
        with os.scandir(directory) as listing:
            for entry in listing:
                budget.node(depth)
                entries.append(entry)
        for entry in sorted(entries, key=lambda item: item.name):
            name = (relative / entry.name).as_posix()
            if entry.is_dir(follow_symlinks=True):
                result['directories'].append(name)
                visit(Path(entry.path), relative / entry.name, parents | {identity}, depth + 1)
            else:
                data, metadata = budget.read(entry.path)
                result['files'].append({'path': name, 'content': data, 'sha256': hashlib.sha256(data).hexdigest(), **metadata})
    budget.node(0)
    visit(path, Path(), set(), 1)
    return result


def capture(root: Path, cfg: dict):
    """No key for projects with no configured include trees: their existing snapshot digests stay compatible."""
    recipes, roots, directories, budget = {}, {}, [], Budget()
    compiler = cfg.get('compiler')
    if not isinstance(compiler, dict) or not isinstance(compiler.get('units', {}), dict):
        raise NetworkError('compiler dependency settings are malformed')
    units = [None, *sorted(compiler.get('units') or {})]
    if len(units) > MAX_RECIPES:
        raise NetworkError('compiler dependency recipe budget exceeded')
    try:
        for unit in units:
            configured = compiler_settings(cfg, unit).get('include_dirs') or []
            if not isinstance(configured, (list, tuple)) or any(not isinstance(value, str) or not value for value in configured):
                raise DependencyError('compiler include directories must be a list of paths')
            recipe = []
            for value in configured:
                path = root / value
                key = str(path.resolve())
                if key not in roots:
                    if len(roots) >= MAX_ROOTS:
                        raise DependencyError('compiler dependency directory budget exceeded')
                    roots[key] = len(directories)
                    directories.append(_tree(path, budget))
                recipe.append(roots[key])
            recipes[unit] = {'configured': list(configured), 'indices': recipe}
    except DependencyError as exc:
        raise NetworkError(str(exc)) from None
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError, KeyError):
        raise NetworkError('compiler dependency input is malformed, unavailable or cyclic') from None
    return {'version': VERSION, 'recipes': {'default': recipes.pop(None), 'units': recipes},
            'directories': directories} if any(recipe['configured'] for recipe in recipes.values()) else None
