"""Physical aliases cannot inflate any progress dimension or establish semantic approval."""
import json

import pytest

from decompnet.app.sms_progress import calculate
from decompnet.rom.physical_ranges import union, length, overlap, acceptance_timeline

from .test_sms_profile_migration import project as fixture_project

project = fixture_project


def row(low, count, status='open', **meta):
    return {'rom_offset': low, 'size': count, 'status': status, 'has_source': status in ('matched', 'documented'),
            'meta': json.dumps(meta)}


def test_aliases_and_data_overlap_are_measured_as_physical_unions():
    rows = [row(0, 10, 'matched'), row(5, 10, 'matched'), row(8, 10, 'documented', sample=True),
            row(9, 2, 'documented'), row(16, 6, 'asm'), row(40, 10)]
    regions = [{'rom_offset': low, 'size': count} for low, count in ((20, 10), (25, 10), (0, 2))]
    measured = calculate(rows, regions, 64, lambda _: True)
    assert measured['totals'] == {'bytes': 32, 'matched_bytes': 15, 'asm_bytes': 6, 'documented_bytes': 10}
    assert measured['mapped'] == {'rom': 64, 'code': 32, 'data': 17, 'covered': 45, 'overlap': 4, 'to_document': 1}
    metrics = measured['metrics']
    assert metrics['c_reference']['eligible_bytes'] == 25 and not metrics['c_reference']['source_linked']
    assert metrics['semantic_review']['pending'] == 1 and metrics['semantic_review']['unknown'] == 1
    assert metrics['semantic_review']['approved'] == 0 and metrics['typed_data']['bytes'] is None
    assert metrics['runtime_parity']['status'] == 'not_tested'


def test_bad_coordinates_metadata_and_absent_sources_never_become_positive_proof():
    rows = [row(None, 10, 'matched'), row(-3, 5, 'matched'), row(60, 10, 'matched'),
            {**row(0, 4, 'matched'), 'has_source': False}, row(8, 4, 'documented', sample=False),
            {**row(12, 4, 'documented'), 'meta': 'broken'}, {**row(16, 4, 'documented'), 'has_source': False}]
    metrics = calculate(rows, [], 64, lambda _: False)['metrics']
    assert metrics['c_reference']['bytes'] == 0
    assert metrics['unplaced_or_clipped_functions'] == 3 and metrics['invalid_metadata'] == 1
    assert metrics['semantic_review']['unknown'] == 3 and metrics['semantic_review']['approved'] == 0
    assert metrics['documented_assembly']['bytes'] == 8 and metrics['documented_assembly']['unbacked_records'] == 1


def test_union_handles_adjacency_bounds_and_shared_cpu_aliases_without_summing_them():
    spans = union([(0, 4), (4, 4), (2, 3), (-2, 4), (15, 6), (None, 3), (True, 2), (1, -1)], 16)
    assert spans == [(0, 8), (15, 16)] and length(spans) == 9
    assert overlap(spans, union([(6, 4), (14, 2)], 16)) == 3


def test_current_reference_dates_attribute_overlapping_bytes_once_and_bound_the_chart():
    timeline = acceptance_timeline([(0, 10, 20), (5, 10, 30), (8, 4, None)], 32)
    assert timeline['baseline_bytes'] == 4 and timeline['points'] == [[20, 12], [30, 15]]
    assert timeline['bytes'] == 15
    dense = acceptance_timeline([(i, 1, i + 1) for i in range(1000)], 1024)
    assert dense['bytes'] == 1000 and len(dense['points']) <= 128 and dense['truncated']
    assert dense['points'][-1] == [1000, 1000]


def test_overview_and_banked_map_use_the_same_union_and_fresh_input_status(project):
    net, slug = project
    proj = net.project_row(slug)
    with net.store.tx() as db:
        db.execute('DELETE FROM functions WHERE project_id=?', (proj['id'],))
        for name, low in [('AliasA', 512), ('AliasB', 516)]:
            db.execute('INSERT INTO functions(project_id,name,rom_offset,vram,size,target,status,matched_source) '
                       "VALUES(?,?,?,?,8,?,'matched','authored stored reference')", (proj['id'], name, low, low, b'\0' * 8))
        db.execute('DELETE FROM data_regions WHERE project_id=?', (proj['id'],))
        db.execute("INSERT INTO data_regions VALUES(?,520,8,'data','authored overlap')", (proj['id'],))
    overview = net.overview(slug)
    assert overview['bytes'] == overview['matched_bytes'] == 12
    assert overview['mapped']['covered'] == 16 and overview['mapped']['overlap'] == 4
    assert overview['sms_progress']['input']['status'] == 'verified'
    assert net._mapped(proj, net.cfg(proj)) == overview['mapped']
    assert '100.0% of C candidates, stored byte references; not linked' in net.list_projects()
    status = next(row for row in net.status_json()['projects'] if row['slug'] == slug)
    assert status['bytes'] == status['matched_bytes'] == 12
    assert '100.0% of C candidates, stored byte references; not linked' in net.status()


@pytest.mark.parametrize('value', ['true', 1, None, {}])
def test_strict_export_setting_requires_a_boolean(project, value):
    from decompnet.network import NetworkError

    net, slug = project
    with pytest.raises(NetworkError, match='boolean'):
        net.export_rom(slug, strict_documented=value)
