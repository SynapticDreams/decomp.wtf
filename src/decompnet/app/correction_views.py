"""Bounded, explicit distinction between research claims, current bindings and active hints."""
from ..network import NetworkError
from ..rom.annotations import inspect, validate_annotation, validate_evidence
from ..rom.sms_locations import coordinate
from ..rom.sms_mapping import Mapper
from . import correction_policy as policy, correction_receipts as receipts, sms_annotation_context as context


def payloads(row, size):
    return (inspect(row['annotation'], validate_annotation, rom_size=size),
            inspect(row['evidence'], validate_evidence))


def geometry(row, value, values=None):
    target = value['target']
    count = value['spec'].get('count', value['spec'].get('bytes_after_call', target['size'] if value['kind'] == 'data' else 0))
    if target['space'] != 'rom' or target['offset'] != row['rom_offset'] or value['kind'] != row['kind'] or count != row['count']:
        raise ValueError('stored correction fields disagree with its annotation')
    if row['kind'] in policy.KINDS and row['cpu'] is None:
        raise ValueError('legacy hint kinds require an explicit CPU coordinate')
    if row['cpu'] is not None:
        if type(row['cpu']) is not int or not 0 <= row['cpu'] < 0xC000:
            raise ValueError('correction CPU coordinate is invalid')
        if values is not None:
            coordinate(Mapper(values[4]['mapper'], len(values[2])), row['rom_offset'], row['cpu'])


def describe(net, row, cfg, values=None):
    tagged = row['annotation'] is not None or row['evidence'] is not None
    where = f"{row['rom_offset'] // 0x4000:02X}:{row['cpu']:04X}" if row['cpu'] is not None else f"ROM+{row['rom_offset']:06X}"
    out = {'id': row['id'], 'kind': row['kind'], 'where': where, 'count': row['count'],
           'unit': policy.KINDS.get(row['kind'], ('', 'records'))[1],
           'says': policy.KINDS.get(row['kind'], (f"declares {row['kind']}", ''))[0],
           'reason': (row['reason'] or '')[:1000], 'by': row['agent'] if 'agent' in row.keys() else None,
           'at': row['created_at'], 'undone': row['undone_at'] is not None, 'active': False,
           'annotation_status': 'legacy_unknown', 'evidence_status': 'legacy_unknown',
           'binding': 'unknown', 'review': 'unknown', 'application': 'legacy_hint' if not tagged else 'invalid'}
    if not tagged:
        try:
            policy.bounds(row['kind'], row['rom_offset'], row['count'], cfg['rom']['size'])
            # A pre-existing untagged fact may describe inline data inside subsequently accepted assembly.
            # Preserve its historical meaning. New writes and bound reviews enforce source protection.
            out['active'] = True
        except NetworkError:
            out['application'] = 'invalid'
    else:
        annotation, evidence = payloads(row, cfg['rom']['size'])
        out.update(annotation_status=annotation.status, evidence_status=evidence.status)
        if 'unsupported_version' in (annotation.status, evidence.status):
            out['application'] = 'unsupported'
        elif annotation.value is not None and evidence.value is not None:
            value, proof = annotation.value, evidence.value
            out.update(target=value['target'], state=proof['state'], confidence=proof['confidence'],
                       origin=proof['origin'], alternatives=len(proof['alternatives']), links=len(proof['links']), review=proof['review']['state'])
            try:
                geometry(row, value)
                if values is None:
                    out.update(binding='unavailable', application='unavailable')
                elif not context.validate_binding(value, proof, row['cpu'], values):
                    out.update(binding='stale', application='stale')
                else:
                    geometry(row, value, values)
                    conflict = policy.conflict(net, row['project_id'], row['kind'], row['rom_offset'], value['target']['size'])
                    trusted = proof['review']['state'] in ('accepted', 'rejected') and receipts.trusted(net, row)
                    out.update(binding='current', conflict=conflict, application='pending_review')
                    if proof['review']['state'] in ('accepted', 'rejected') and not trusted:
                        out.update(review='untrusted', application='untrusted_review')
                    elif trusted:
                        out['application'] = 'rejected' if proof['review']['state'] == 'rejected' else 'conflict' if conflict else \
                            'legacy_hint' if row['kind'] in policy.KINDS else 'awaiting_consumer'
                        out['active'] = out['application'] == 'legacy_hint'
            except (ValueError, TypeError, KeyError, NetworkError):
                out['application'] = 'invalid'
    if out['undone']:
        out.update(active=False, application='undone')
    return out


def raw(view):
    value = view.raw
    if value is None or isinstance(value, str) and len(value) <= 65536 and len(value.encode('utf-8', errors='replace')) <= 65536:
        return {'status': view.status, 'value': view.value, 'raw': value, 'truncated': False}
    return {'status': view.status, 'value': None, 'raw': value[:4096] if isinstance(value, str) else None,
            'truncated': True}


def detail(net, row, cfg, values=None):
    annotation, evidence = payloads(row, cfg['rom']['size'])
    return {**describe(net, row, cfg, values), 'annotation': raw(annotation), 'evidence': raw(evidence)}
