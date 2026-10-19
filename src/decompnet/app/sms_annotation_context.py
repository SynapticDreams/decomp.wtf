"""Frozen input/subject bindings and independent mutable-work guards for research edits."""
import hashlib
from contextlib import contextmanager, nullcontext

from ..network import NetworkError
from ..rom import sms_profile
from ..rom.annotations import dump, validate_annotation
from . import banked_resplit_history as history, banked_resplit_state as state, correction_policy as policy
from .sms_symbol_import import image


@contextmanager
def read(net):
    """Serialize local readers and hold one SQLite snapshot across row, binding and work checks."""
    with net.store.lock:
        with (nullcontext() if net.store.conn.in_transaction else net.store.tx()):
            yield


def digest(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


def load(net, slug):
    proj, cfg = policy.project(net, slug, sms=True)
    try:
        sms_profile.require_supported(cfg)
        original = image(proj, cfg)
        revision = {'platform': cfg['platform'], 'size': len(original), 'sha256': hashlib.sha256(original).hexdigest()}
        profile = sms_profile.read(cfg)
        context = {'mapper': profile['mapper'], 'sha256': digest({
            'version': 1, 'profile': profile, 'symbol_source': cfg.get('symbol_file')})}
        return proj, cfg, original, revision, context
    except (ValueError, TypeError, KeyError, OSError):
        raise NetworkError('frozen SMS/GG input or declared mapping is unavailable or differs') from None


def subject(value, cpu, original):
    validate_annotation(value, rom_size=len(original))
    target = value['target']
    if target['space'] != 'rom':
        raise ValueError('corrections target ROM; RAM declarations belong on notes or symbols')
    start, size = target['offset'], target['size']
    raw = original[start:start + size]
    if value['kind'] == 'number' and int.from_bytes(raw, value['spec']['endian']) != value['spec']['value']:
        raise ValueError('forced numeric value differs from the original bytes')
    return digest({'version': 1, 'annotation': value, 'cpu': cpu, 'bytes_sha256': hashlib.sha256(raw).hexdigest()})


def guard(net, proj):
    return state.encode(history.capture(net, proj))[1]


def check_plan(expected, actual, *, required=False):
    if (required and expected is None) or (expected is not None and expected != actual):
        raise NetworkError('correction preview is missing or stale; preview again')


def plan(work, request):
    # Requests are bounded by the annotation codec; the work digest has its own snapshot budget.
    return digest({'version': 1, 'work': work, 'request': request})


def current(net, slug, expected_work, revision, context):
    values = load(net, slug)
    proj = values[0]
    if values[3:] != (revision, context) or guard(net, proj) != expected_work:
        raise NetworkError('project work, input or mapping changed; preview again')
    return values


def validate_binding(value, evidence, cpu, values):
    _proj, _cfg, original, revision, context = values
    return evidence['revision'] == revision and evidence['context'] == context and \
        evidence['subject_sha256'] == subject(value, cpu, original)
