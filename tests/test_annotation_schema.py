"""Research schema bounds and explicit encodings prevent accidental pointer or confidence assumptions."""
import copy
import json

import pytest

from decompnet.rom.annotations import codec, evidence as provenance, validate_annotation, validate_evidence
from decompnet.rom.annotations.payloads import KINDS
from .annotation_fixture import annotation, evidence, SIZE


@pytest.mark.parametrize('kind', KINDS)
def test_each_research_kind_roundtrips_without_losing_declared_geometry(kind):
    value = annotation(kind)
    original = copy.deepcopy(value)
    validate_annotation(value, rom_size=SIZE)
    raw = codec.dump(value)
    viewed = codec.inspect(raw, validate_annotation, rom_size=SIZE)
    assert viewed.status == 'supported' and viewed.value == original and viewed.raw == raw
    assert value == original


@pytest.mark.parametrize('space,limit', [('rom', SIZE), ('wram', 0x2000), ('cart_ram', 0x8000)])
def test_targets_keep_physical_address_spaces_separate_and_bounded(space, limit):
    value = annotation('record')
    value['target'].update(space=space, offset=limit - 64)
    validate_annotation(value, rom_size=SIZE)
    value['target']['offset'] += 1
    with pytest.raises(ValueError, match='outside'):
        validate_annotation(value, rom_size=SIZE)


@pytest.mark.parametrize('change', ['boolean', 'negative', 'version', 'extra', 'zero', 'large_count', 'stride',
                                    'field_end', 'duplicate_name', 'overlap', 'bit_end', 'bit_overlap', 'field_type'])
def test_invalid_record_geometry_and_malformed_fields_are_rejected(change):
    value = annotation()
    spec = value['spec']
    if change == 'boolean': spec['count'] = True
    elif change == 'negative': value['target']['offset'] = -1
    elif change == 'version': value['version'] = True
    elif change == 'extra': value['target']['cpu'] = 0x100
    elif change == 'zero': value['target']['size'] = 0
    elif change == 'large_count': spec['count'] = 4097
    elif change == 'stride': spec['stride'] = 2
    elif change == 'field_end': spec['fields'][1]['offset'] = 15
    elif change == 'duplicate_name': spec['fields'][1]['name'] = 'flags'
    elif change == 'overlap': spec['fields'][3]['offset'] = 2
    elif change == 'bit_end': spec['fields'][0]['bits'][1].update(lsb=7, width=2)
    elif change == 'bit_overlap': spec['fields'][0]['bits'][1].update(lsb=0, width=2)
    else: spec['fields'][0]['type'] = 'guessed_type'
    with pytest.raises(ValueError):
        validate_annotation(value, rom_size=SIZE)


def test_overlapping_record_views_require_an_explicit_policy():
    value = annotation()
    value['spec']['fields'].append({'name': 'packed_word_view', 'offset': 0, 'type': 'u16le'})
    with pytest.raises(ValueError, match='overlap'):
        validate_annotation(value, rom_size=SIZE)
    value['spec']['overlap'] = 'views'
    validate_annotation(value, rom_size=SIZE)


@pytest.mark.parametrize('kind', ['pointers', 'split_pointers'])
@pytest.mark.parametrize('change', ['end', 'bank_overlap', 'missing_layout', 'meaning', 'target', 'boolean'])
def test_pointer_fields_cannot_read_metadata_or_unbound_bank_identifiers(kind, change):
    value = annotation(kind)
    spec = value['spec']
    if change == 'end': spec['count'] = 4096
    elif change == 'bank_overlap': spec['bank']['offset'] = spec.get('pointer_offset', spec.get('low_offset'))
    elif change == 'missing_layout': spec['bank']['meaning'] = 'assembler'
    elif change == 'meaning': spec['bank']['meaning'] = 'automatic'
    elif change == 'target': spec['target'] = 'function_guess'
    else: spec['stride'] = False
    with pytest.raises(ValueError):
        validate_annotation(value, rom_size=SIZE)


def test_near_far_and_split_pointer_layouts_remain_explicit():
    near = annotation('pointers'); near['spec']['bank'] = None
    validate_annotation(near, rom_size=SIZE)
    far = annotation('pointers')
    far['spec']['bank'].update(meaning='assembler', source_sha256='a' * 64)
    validate_annotation(far, rom_size=SIZE)
    split = annotation('split_pointers')
    split['spec'].update(stride=2, low_offset=0, high_offset=1)
    split['spec']['bank'] = None
    validate_annotation(split, rom_size=SIZE)
    split['spec']['high_offset'] = 2
    with pytest.raises(ValueError, match='overlap'):
        validate_annotation(split, rom_size=SIZE)


def test_numeric_literals_and_scoped_mapping_claims_are_not_implicit_pointers_or_live_state():
    number = annotation('number')
    validate_annotation(number, rom_size=SIZE)
    number['spec']['value'] = 65536
    with pytest.raises(ValueError): validate_annotation(number, rom_size=SIZE)
    mapping = annotation('mapping')
    validate_annotation(mapping, rom_size=SIZE)
    mapping['spec']['facts']['banks'][2] = 256
    with pytest.raises(ValueError): validate_annotation(mapping, rom_size=SIZE)
    mapping['spec']['facts']['banks'][2] = 5
    mapping['spec']['facts']['guessed_bank'] = 5
    with pytest.raises(ValueError): validate_annotation(mapping, rom_size=SIZE)


@pytest.mark.parametrize('state', ['observation', 'static_derivation', 'interpretation', 'hypothesis'])
def test_evidence_states_remain_distinct_from_confidence_and_review(state):
    value = evidence()
    value.update(state=state, links=[{'kind': 'analysis', 'ref': 'authored-check:1', 'sha256': 'b' * 64}])
    raw = codec.dump(value)
    viewed = codec.inspect(raw, validate_evidence)
    assert viewed.status == 'supported' and viewed.value['state'] == state
    assert viewed.value['review']['state'] == 'pending'


def test_review_shape_is_bound_to_subject_revision_and_context_without_authenticating_it():
    value = evidence()
    value.update(revision={'platform': 'sms', 'size': SIZE, 'sha256': 'a' * 64},
                 context={'mapper': 'sega', 'sha256': 'b' * 64}, subject_sha256='c' * 64)
    value['review'].update(state='accepted', actor='operator:1', at=1, binding_sha256=provenance.binding(value))
    validate_evidence(value)
    value['subject_sha256'] = 'd' * 64
    with pytest.raises(ValueError, match='binding differs'):
        validate_evidence(value)
    value['review']['binding_sha256'] = provenance.binding(value)
    value['revision'] = None
    with pytest.raises(ValueError, match='require revision'):
        validate_evidence(value)


@pytest.mark.parametrize('change', ['state', 'origin', 'confidence', 'references', 'review', 'alternative', 'url'])
def test_invalid_evidence_and_unbound_review_claims_are_rejected(change):
    value = evidence()
    if change == 'state': value['state'] = 'fact'
    elif change == 'origin': value['origin']['kind'] = 'original_author'
    elif change == 'confidence': value.update(state='unknown', confidence='high')
    elif change == 'references': value['state'] = 'observation'
    elif change == 'review': value['review']['actor'] = 'unbound-claim'
    elif change == 'alternative': value['alternatives'] = ['x'] * 9
    else: value['links'] = [{'kind': 'external', 'ref': 'file:///private/path', 'sha256': None}]
    with pytest.raises(ValueError): validate_evidence(value)


@pytest.mark.parametrize('raw,status', [(None, 'legacy_unknown'), ('{"version":2,"future":true}', 'unsupported_version'),
    ('{"version":true}', 'invalid'), ('{"version":1,"version":2}', 'invalid'), ('{', 'invalid'), ('NaN', 'invalid')])
def test_unsupported_or_invalid_metadata_stays_original_and_inactive(raw, status):
    view = codec.inspect(raw, validate_evidence)
    assert view.status == status and view.raw == raw and view.value is None


def test_json_size_depth_node_and_integer_budgets_are_enforced():
    with pytest.raises(ValueError): codec.dump({'large': ['x' * 4096] * 20})
    with pytest.raises(ValueError): codec.dump([0] * (codec.MAX_NODES + 1))
    deep = []
    for _ in range(codec.MAX_DEPTH + 1): deep = [deep]
    with pytest.raises(ValueError): codec.dump(deep)
    with pytest.raises(ValueError): codec.dump({'integer': 2**53})
    raw = json.dumps({'version': 2, 'future': 'x' * codec.MAX_BYTES})
    assert codec.inspect(raw, validate_evidence).status == 'invalid'
