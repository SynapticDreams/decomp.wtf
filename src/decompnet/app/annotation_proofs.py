"""Shared author attribution and pending evidence bindings; parsed receipts never grant authority."""
import copy

from ..rom.annotations import validate_evidence


def hypothesis():
    return {'version': 1, 'revision': None, 'context': None, 'subject_sha256': None, 'origin': None,
            'state': 'hypothesis', 'confidence': 'unknown', 'alternatives': [], 'links': [],
            'review': {'state': 'pending', 'actor': None, 'at': None, 'binding_sha256': None}}


def bind(value, agent, revision, context, subject):
    proof = copy.deepcopy(hypothesis() if value is None else value)
    validate_evidence(proof)
    if proof['review']['state'] not in ('unknown', 'pending'):
        raise ValueError('caller-supplied review receipts are not accepted')
    for key, expected in (('revision', revision), ('context', context), ('subject_sha256', subject)):
        if proof[key] is not None and proof[key] != expected:
            raise ValueError('evidence belongs to another revision, context or subject')
        proof[key] = expected
    proof['origin'] = {'kind': 'agent', 'ref': f'agent:{agent.id}'}
    proof['review'] = {'state': 'pending', 'actor': None, 'at': None, 'binding_sha256': None}
    validate_evidence(proof)
    return proof
