"""Versioned provenance and bound review shape; parsed claims are not authenticated review receipts."""
import hashlib
from urllib.parse import urlsplit

from .codec import dump
from .fields import fields, integer, choice, sequence, text, digest, version

STATES = ('unknown', 'observation', 'static_derivation', 'interpretation', 'hypothesis')


def binding(value):
    return hashlib.sha256(dump({key: value[key] for key in ('version', 'revision', 'context', 'subject_sha256')}).encode()).hexdigest()


def link(value):
    fields(value, ('kind', 'ref', 'sha256'))
    kind = choice(value['kind'], ('source', 'note', 'analysis', 'session', 'external'))
    ref = text(value['ref'], 512)
    if any(ord(char) < 32 for char in ref):
        raise ValueError('evidence references cannot contain control characters')
    if kind == 'external':
        uri = urlsplit(ref)
        if uri.scheme not in ('http', 'https') or not uri.netloc or uri.username is not None or uri.password is not None:
            raise ValueError('external evidence must be an HTTP(S) reference without credentials')
    if value['sha256'] is not None:
        digest(value['sha256'])


def validate(value):
    dump(value)
    fields(value, ('version', 'revision', 'context', 'subject_sha256', 'origin', 'state', 'confidence',
                   'alternatives', 'links', 'review'))
    version(value['version'])
    revision = value['revision']
    if revision is not None:
        fields(revision, ('platform', 'size', 'sha256'))
        choice(revision['platform'], ('sms', 'gg'))
        size = integer(revision['size'], 0x2000, 0x400000)
        if size % 0x2000:
            raise ValueError('revision size is not a normalized cartridge extent')
        digest(revision['sha256'])
    context = value['context']
    if context is not None:
        fields(context, ('mapper', 'sha256'))
        choice(context['mapper'], ('sega', 'mapperless', 'codemasters'))
        digest(context['sha256'])
    if value['subject_sha256'] is not None:
        digest(value['subject_sha256'])
    origin = value['origin']
    if origin is not None:
        fields(origin, ('kind', 'ref'))
        choice(origin['kind'], ('legacy', 'operator', 'agent', 'import', 'analysis', 'session'))
        if origin['ref'] is not None:
            text(origin['ref'], 512)
    state = choice(value['state'], STATES)
    confidence = choice(value['confidence'], ('unknown', 'low', 'medium', 'high'))
    if state == 'unknown' and confidence != 'unknown':
        raise ValueError('unknown evidence cannot assert confidence')
    for alternative in sequence(value['alternatives'], 0, 8):
        text(alternative, 512)
    links = sequence(value['links'], 0, 16)
    for item in links:
        link(item)
    if state in ('observation', 'static_derivation', 'interpretation') and not links:
        raise ValueError('supported evidence states require evidence references')
    review = value['review']
    fields(review, ('state', 'actor', 'at', 'binding_sha256'))
    choice(review['state'], ('unknown', 'pending', 'accepted', 'rejected'))
    if review['state'] in ('unknown', 'pending'):
        if any(review[key] is not None for key in ('actor', 'at', 'binding_sha256')):
            raise ValueError('unreviewed evidence cannot claim a review receipt')
    else:
        if revision is None or context is None or value['subject_sha256'] is None:
            raise ValueError('review claims require revision, context and subject bindings')
        text(review['actor'], 128)
        integer(review['at'], 1, 2**53 - 1)
        if digest(review['binding_sha256']) != binding(value):
            raise ValueError('review binding differs from its subject or context')
    return value
