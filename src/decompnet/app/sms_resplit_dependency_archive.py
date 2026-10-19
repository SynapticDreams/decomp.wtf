"""Recover selected configured compiler dependencies from private versioned resplit records."""
import base64
import hashlib
import json
from pathlib import PurePosixPath

from ..project import compiler_settings
from .sms_resplit_dependencies import DependencyError, MAX_BYTES, MAX_FILES
from .sms_resplit_dependency_context import recipe


def items(snapshot, row, item):
    settings = compiler_settings(json.loads(snapshot['project']['config']), row['unit'])
    if not settings.get('include_dirs'):
        return []
    manifest = {'version': 1, 'configured': settings['include_dirs'], 'scope': 'configured-include-trees',
                'capture_point': 'resplit snapshot; prior acceptance context is not established by capture'}
    out, files, size = [], [], 0
    try:
        bundle, indices = recipe(snapshot, settings, row['unit'])
        manifest['order'] = indices
        manifest['directories'] = []
        for index in dict.fromkeys(indices):
            directory = bundle['directories'][index]
            manifest['directories'].append({'index': index, 'exists': directory['exists'], 'directories': directory['directories'],
                                            'directory_metadata': directory['directory_metadata']})
            for file in directory['files']:
                raw = file['content']
                size += len(raw)
                if len(files) >= MAX_FILES or size > MAX_BYTES or hashlib.sha256(raw).hexdigest() != file['sha256']:
                    raise DependencyError('saved compiler dependency content or budget differs')
                try:
                    text, encoding = raw.decode('utf-8'), 'utf-8'
                    suffix = PurePosixPath(file['path']).suffix.removeprefix('.')
                    extension = suffix if suffix.isalnum() and len(suffix) <= 12 else 'txt'
                except UnicodeDecodeError:
                    text, encoding, extension = base64.b64encode(raw).decode('ascii'), 'base64', 'b64'
                key = f'dependency:{len(files)}'
                provenance = {'directory': index, 'path': file['path'], 'bytes': len(raw),
                              'content_sha256': file['sha256'], 'encoding': encoding,
                              'mode': file['mode'], 'mtime_ns': str(file['mtime_ns'])}
                files.append({'key': key, **provenance})
                out.append(item(key, f"Dependency {index}: {file['path']}", text, provenance, extension))
        manifest.update(state='captured', files=files)
    except (DependencyError, KeyError, IndexError, TypeError) as exc:
        reason = str(exc) if isinstance(exc, DependencyError) else 'saved compiler dependency context is malformed'
        manifest.update(state='unavailable', reason=reason)
        out = []
    return [item('dependencies', 'Compiler dependency manifest', lambda: json.dumps(manifest, sort_keys=True,
                                                                                 separators=(',', ':')), {}, 'json'), *out]
