"""Notes and symbols retain research status independently of code acceptance and discovery."""
from ..network import NetworkError
from ..rom.annotations import inspect
from . import annotation_archives as archives, annotation_keys as keys, annotation_subjects as subjects
from .annotation_payloads import parse, raw


def describe(net, kind, row, cfg, values=None, *, full=False):
    annotation, evidence = parse(row, cfg['rom']['size'])
    subject = inspect(row['subject'], subjects.validate)
    is_archive = kind == 'note' and archives.is_archive(row)
    out = {'kind': kind, 'key': row['id'] if kind == 'note' else row['name'],
           'annotation_status': annotation.status, 'evidence_status': evidence.status,
           'subject_status': subject.status, 'binding': 'unknown', 'review': 'unknown',
           'application': 'legacy_unknown', 'discovery': False}
    if kind == 'note':
        out.update(text=row['text'] if full else row['text'][:1000], text_truncated=not full and len(row['text']) > 1000,
                   function_id=row['function_id'], archived=is_archive)
    else:
        out.update(symbol={key: row[key] for key in ('name', 'address', 'size', 'kind')})
    if any(row[key] is not None for key in ('annotation', 'evidence', 'subject')):
        out['application'] = 'invalid'
        if 'unsupported_version' in (annotation.status, evidence.status, subject.status):
            out['application'] = 'unsupported'
        elif (row['annotation'] is None or annotation.value is not None) and evidence.value is not None:
            proof = evidence.value
            out.update(state=proof['state'], confidence=proof['confidence'], origin=proof['origin'],
                       review=proof['review']['state'], alternatives=len(proof['alternatives']), links=len(proof['links']))
            try:
                if proof['review']['state'] in ('accepted', 'rejected') and not keys.trusted(net, kind, row):
                    out['review'] = 'untrusted'
                if subject.status == 'legacy_unknown':
                    out.update(binding='unknown', application='unbound')
                elif subject.value is None:
                    out['application'] = 'invalid'
                elif values is None:
                    out.update(binding='unavailable', application='unavailable')
                elif not subjects.current(net, kind, row, annotation.value, proof, subject.value, values):
                    out.update(binding='stale', application='stale')
                else:
                    out.update(binding='current', application='pending_review')
                    if proof['review']['state'] in ('accepted', 'rejected'):
                        if keys.trusted(net, kind, row):
                            out['application'] = 'reviewed_research' if proof['review']['state'] == 'accepted' else 'rejected'
                        else:
                            out.update(review='untrusted', application='untrusted_review')
            except (ValueError, TypeError, KeyError, NetworkError):
                out['application'] = 'invalid'
    if is_archive:
        out.update(application='archived', binding='original_subject')
    if full:
        out.update(annotation=raw(annotation), evidence=raw(evidence), subject=raw(subject))
        if kind == 'note' and len(out['text']) > 8192:
            out.update(text=out['text'][:8192], text_truncated=True)
    return out
