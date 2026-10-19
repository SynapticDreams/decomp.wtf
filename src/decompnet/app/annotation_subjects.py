"""Research subjects identify declarations and attachments; RAM contents are never invented."""
import hashlib

from ..rom import sms_profile
from ..rom.annotations import dump, validate_annotation, validate_evidence
from ..rom.annotations.fields import fields, version, choice, digest
from .annotation_proofs import hypothesis
from . import sms_annotation_context as context


def attachment(net, pid, name=None, fid=None):
    if name is None and fid is None:
        return None
    row = net.store.one('SELECT id,name,rom_offset,vram,size,target FROM functions WHERE project_id=? AND ' +
                        ('name=?' if name is not None else 'id=?'), pid, name if name is not None else fid)
    if row is None:
        return None
    return {key: row[key] for key in ('id', 'name', 'rom_offset', 'vram', 'size')} | {
        'stored_target_sha256': hashlib.sha256(row['target']).hexdigest() if row['target'] is not None else None}


def entity(net, kind, row):
    pid = row['project_id']
    if kind == 'note':
        return {'kind': kind, 'text': row['text'], 'function_id': row['function_id'],
                'function': attachment(net, pid, fid=row['function_id'])}
    return {'kind': kind, 'symbol': {key: row[key] for key in ('name', 'address', 'size', 'kind')},
            'function': attachment(net, pid, name=row['name'])}


def descriptor(entity, annotation, values):
    _proj, cfg, original, revision, mapping = values
    source = None
    if annotation is not None:
        validate_annotation(annotation, rom_size=len(original))
        target = annotation['target']
        if target['space'] == 'rom':
            raw = original[target['offset']:target['offset'] + target['size']]
            if annotation['kind'] == 'number' and int.from_bytes(raw, annotation['spec']['endian']) != annotation['spec']['value']:
                raise ValueError('forced numeric value differs from the original bytes')
            source = {'space': 'rom', 'sha256': hashlib.sha256(raw).hexdigest()}
        else:
            source = {'space': target['space'], 'contents': 'unobserved'}
    return {'version': 1, 'kind': entity['kind'], 'entity': entity, 'source': source,
            'annotation_sha256': context.digest(annotation) if annotation is not None else None,
            'revision': revision, 'context': mapping,
            'mapping': {'profile': sms_profile.read(cfg), 'symbol_source': cfg.get('_annotation_source')}}


def validate(value):
    """Validate descriptor shape. Exact correspondence is checked separately against the current subject."""
    dump(value)
    fields(value, ('version', 'kind', 'entity', 'source', 'annotation_sha256', 'revision', 'context', 'mapping'))
    version(value['version'])
    choice(value['kind'], ('note', 'symbol'))
    if value['annotation_sha256'] is not None:
        digest(value['annotation_sha256'])
    proof = hypothesis()
    proof.update(revision=value['revision'], context=value['context'])
    validate_evidence(proof)
    if not isinstance(value['entity'], dict) or value['entity'].get('kind') != value['kind']:
        raise ValueError('subject entity kind differs')
    fields(value['mapping'], ('profile', 'symbol_source'))
    if not isinstance(value['mapping']['profile'], dict) or value['mapping']['symbol_source'] is not None and not isinstance(value['mapping']['symbol_source'], dict):
        raise ValueError('subject mapping is unavailable')
    source = value['source']
    if source is not None:
        if not isinstance(source, dict):
            raise ValueError('subject source is malformed')
        if source.get('space') == 'rom':
            fields(source, ('space', 'sha256')); digest(source['sha256'])
        else:
            fields(source, ('space', 'contents')); choice(source['space'], ('wram', 'cart_ram'))
            if source['contents'] != 'unobserved':
                raise ValueError('RAM contents cannot be invented by a declaration')


def current(net, kind, row, annotation, evidence, saved, values):
    expected = descriptor(entity(net, kind, row), annotation, values)
    return evidence['revision'] == values[3] and evidence['context'] == values[4] and saved == expected and \
        evidence['subject_sha256'] == context.digest(saved)
