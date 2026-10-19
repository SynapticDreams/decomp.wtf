"""The tool-backed gate must not turn missing tools, skipped checks or stale reports into success."""
import xml.etree.ElementTree as ET

import pytest

from tools import sms_gate


def report(tmp_path, *, skipped=False, failed=False, missing_module=False, gg=True, mapper_matrix=True, recovery=True, revalidation=True, archive=True, dependencies=True, undo=True, migration=True, inspection=True, project_archive=True, legacy=True, verification=True, progress=True, export_state=True, c_reference=True, progress_routes=True, artifacts=True, wla=True, symbol_imports=True, adjacent=True):
    suite = ET.Element("testsuite")
    modules = sms_gate.TESTS[:-1] if missing_module else sms_gate.TESTS
    for name in modules:
        extra = None
        if name.endswith('test_sms_symbol_adjacent.py') and adjacent:
            extra = [f'test_initial_sidecar_import_preserves_bytes_and_never_guesses_nonuniform_geometry[{p}-{mode}]'
                     for p in ('sms', 'gg') for mode in ('declared', 'missing', 'malformed', 'different_revision', 'invalid_geometry',
                                                        'null', 'new_version', 'wrong_crc', 'oversized', 'bad_source', 'future_symbols')]
            extra += [f'{test}[{p}]' for p in ('sms', 'gg') for test in (
                'test_legacy_layout_uncertainty_preserves_actual_accepted_source_and_recovery',
                'test_stored_inspection_cannot_mix_mapper_contexts_with_the_same_source_bytes')]
        elif name.endswith('test_sms_symbol_import.py') and symbol_imports:
            extra = [f'{test}[{p}]' for p in ('sms', 'gg') for test in (
                'test_preview_apply_reload_resplit_and_undo_preserve_source_identity_and_existing_work',
                'test_missing_layout_retains_raw_records_without_applying_names_or_seeds',
                'test_corrupt_bundle_is_visible_and_stops_resplit_without_legacy_fallback',
                'test_remove_disables_sources_and_keeps_original_provenance_without_legacy_fallback',
                'test_failed_database_publication_does_not_change_the_active_source_or_functions',
                'test_inspection_pages_preserve_every_alias_and_reject_a_changed_source')]
            extra += [f'test_stale_preview_never_replaces_current_source_or_work[{p}-{change}]'
                      for p in ('sms', 'gg') for change in ('source', 'work', 'input')]
        elif name.endswith('test_sms_symbol_routes.py') and symbol_imports:
            extra = [f'test_authenticated_preview_apply_and_inspection_preserve_binary_source_without_exposing_it[{p}]' for p in ('sms', 'gg')]
        elif name.endswith('test_sms_symbol_preservation.py') and symbol_imports:
            extra = [f'test_declared_symbol_import_retains_actual_{kind}_and_resplit_undo[{p}]'
                     for p in ('sms', 'gg') for kind in ('documented_source', 'c_match')]
        elif name.endswith('test_sms_wla_tool.py') and wla:
            extra = [f'test_actual_nonuniform_wla_symbols_seed_the_right_bytes_and_keep_aliases[{p}]' for p in ('sms', 'gg')]
        elif name.endswith('test_sms_wla_symbols.py') and wla:
            extra = ['test_nonuniform_banks_aliases_duplicate_cpu_windows_and_automatic_seeds_are_distinct',
                     'test_data_ram_locals_unknown_and_impossible_fixed_prefix_do_not_seed_code',
                     'test_public_reader_requires_geometry_or_explicit_physical_code_coordinates']
        elif name.endswith('test_sms_progress.py') and progress:
            extra = ['test_aliases_and_data_overlap_are_measured_as_physical_unions',
                     'test_current_reference_dates_attribute_overlapping_bytes_once_and_bound_the_chart'] + [
                f'test_overview_and_banked_map_use_the_same_union_and_fresh_input_status[{p}]' for p in ('sms', 'gg')]
        elif name.endswith('test_sms_export_state.py') and export_state:
            extra = [f'test_last_success_is_historical_after_work_or_input_changes[{p}-{change}]'
                     for p in ('sms', 'gg') for change in ('source', 'header', 'symbol', 'note', 'profile', 'input', 'missing',
                                                        'tree', 'artifact', 'receipt', 'baserom', 'tree_missing')]
            extra += [f'{test}[{p}]' for p in ('sms', 'gg') for test in (
                'test_failed_preflight_records_a_new_failed_attempt_and_keeps_previous_output',
                'test_unbound_legacy_input_cannot_be_promoted_to_an_exact_export',
                'test_summary_counts_union_inserted_bytes_and_bounds_omission_bodies',
                'test_new_work_during_export_remains_and_prevents_a_current_success_claim',
                'test_tree_edit_during_the_build_cannot_bind_a_current_success',
                'test_result_edit_after_measurement_cannot_be_bound_to_the_older_success')]
        elif name.endswith('test_sms_export_artifacts.py') and artifacts:
            extra = ['test_source_edits_and_measured_outputs_change_fingerprint_but_scratch_files_do_not',
                     'test_caps_and_nonregular_inputs_cannot_be_attested',
                     'test_symlinks_including_the_output_directory_are_not_followed',
                     'test_paths_and_permissions_are_framed_unambiguously']
        elif name.endswith('test_sms_c_reference_export.py') and c_reference:
            extra = [f'test_named_unit_c_reference_keeps_its_header_flags_and_truthful_scope[{p}]' for p in ('sms', 'gg')]
        elif name.endswith('test_sms_progress_routes.py') and progress_routes:
            extra = [f'test_operator_controls_strict_insertion_and_sees_independent_evidence[{p}]' for p in ('sms', 'gg')]
            extra += [f'test_configuration_or_helper_failure_replaces_a_stale_standalone_success[{p}-{file}]'
                      for p in ('sms', 'gg') for file in ('build.json', 'layout.json', 'tools/sms_export_build_run.py', 'tools/sms_export_artifacts.py')]
        if extra is not None:
            for test in extra:
                ET.SubElement(suite, 'testcase', classname=name[:-3].replace('/', '.'), name=test)
            continue
        if name.endswith('test_sms_export_verification.py') and verification:
            for platform in ('sms', 'gg'):
                for test in ('test_standalone_reports_inserted_disabled_and_required_source_separately',
                             'test_changed_assembly_reports_actual_insertion_and_the_image_difference',
                             'test_failed_standalone_run_replaces_old_success_receipts_and_artifacts'):
                    suffix = f'[{platform}-tool]' if test.startswith('test_failed') else f'[{platform}]'
                    ET.SubElement(suite, 'testcase', classname='tests.test_sms_export_verification', name=test + suffix)
            continue
        if name.endswith('test_sms_project_archive.py') and project_archive:
            for platform in ('sms', 'gg'):
                ET.SubElement(suite, 'testcase', classname='tests.test_sms_project_archive', name=
                    f'test_project_note_context_and_binary_dependencies_are_recoverable_after_new_work_blocks_undo[{platform}]')
            continue
        if name.endswith('test_sms_resplit_legacy_integration.py') and legacy:
            for platform in ('sms', 'gg'):
                for kind in ('c', 'asm'):
                    ET.SubElement(suite, 'testcase', classname='tests.test_sms_resplit_legacy_integration', name=
                        f'test_old_schema_source_is_migrated_revalidated_and_restored_without_losing_work[{platform}-{kind}]')
            continue
        if name.endswith('test_sms_resplit_inspection.py') and inspection:
            for platform in ('sms', 'gg'):
                for migrate in ('False', 'True'):
                    ET.SubElement(suite, 'testcase', classname='tests.test_sms_resplit_inspection', name=
                        f'test_every_changed_check_and_overlap_record_can_be_inspected_without_saving[{platform}-{migrate}]')
            continue
        if name.endswith('test_sms_profile_migration.py') and migration:
            for platform in ('sms', 'gg'):
                for mapper in ('mapperless', 'codemasters'):
                    ET.SubElement(suite, 'testcase', classname='tests.test_sms_profile_migration', name=
                        f'test_proposed_model_revalidates_unchanged_c_and_undo_restores_the_old_model[{platform}-{mapper}]')
                for test in ('test_assembly_is_rejudged_in_the_new_model_with_semantic_review_pending',
                             'test_old_documented_entry_without_new_model_placement_is_archived_unaccepted'):
                    ET.SubElement(suite, 'testcase', classname='tests.test_sms_profile_migration', name=f'{test}[{platform}]')
            continue
        if name.endswith('test_sms_resplit_undo_validation.py') and undo:
            for platform in ('sms', 'gg'):
                for change in ('note', 'header', 'claim'):
                    ET.SubElement(suite, 'testcase', classname='tests.test_sms_resplit_undo_validation', name=
                        f'test_new_edits_during_undo_validation_prevent_restoring_over_them[{platform}-{change}]')
                ET.SubElement(suite, 'testcase', classname='tests.test_sms_resplit_undo_validation', name=
                    f'test_old_accepted_bytes_outside_the_frozen_input_cannot_be_restored[{platform}]')
            continue
        if name.endswith('test_sms_resplit_dependency_integration.py') and dependencies:
            for platform in ('sms', 'gg'):
                for changed in ('False', 'True'):
                    ET.SubElement(suite, 'testcase', classname='tests.test_sms_resplit_dependency_integration', name=
                        f'test_nested_unit_dependencies_are_revalidated_and_recoverable_without_layout_changes[{platform}-{changed}]')
            continue
        if name.endswith('test_sms_resplit_archive.py') and archive:
            for platform in ('sms', 'gg'):
                for kind in ('c', 'asm'):
                    ET.SubElement(suite, 'testcase', classname='tests.test_sms_resplit_archive', name=
                        f'test_saved_source_can_be_recovered_and_rejudged_after_new_work_blocks_undo[{platform}-{kind}]')
            continue
        if name.endswith('test_sms_resplit_revalidate.py') and revalidation:
            for platform in ('sms', 'gg'):
                for changed in ('False', 'True'):
                    ET.SubElement(suite, 'testcase', classname='tests.test_sms_resplit_revalidate', name=
                        f'test_c_resplit_rechecks_bytes_and_unit_header_and_preserves_provenance[{platform}-{changed}]')
                ET.SubElement(suite, 'testcase', classname='tests.test_sms_resplit_revalidate', name=
                    f'test_assembly_resplit_rechecks_new_cpu_then_inserts_retained_source_in_exact_export[{platform}]')
            continue
        if name.endswith("test_sms_resplit_history.py") and recovery:
            for platform in ("sms", "gg"):
                ET.SubElement(suite, "testcase", classname="tests.test_sms_resplit_history", name=
                    f"test_changed_documented_source_and_attempts_are_recoverable_and_rebuild_after_undo[{platform}]")
            continue
        if name.endswith("test_sms_mapper_integration.py") and mapper_matrix:
            for mapper in ("sega", "mapperless", "codemasters"):
                for platform in ("sms", "gg"):
                    ET.SubElement(suite, "testcase", classname="tests.test_sms_mapper_integration",
                                  name=f"test_declared_models_agree_across_project_consumers[{mapper}-{platform}]")
            continue
        case = ET.SubElement(suite, "testcase", classname=name[:-3].replace("/", "."),
                             name="test_rebuild[gg]" if gg else "test_rebuild[sms]")
        if skipped:
            ET.SubElement(case, "skipped")
        if failed:
            ET.SubElement(case, "failure")
    path = tmp_path / "results.xml"
    ET.ElementTree(suite).write(path)
    return path


def test_gate_rejects_missing_or_stale_tool_install(monkeypatch):
    monkeypatch.setattr(sms_gate.toolchains, "installed", lambda _: None)
    with pytest.raises(ValueError, match="install the pinned tools"):
        sms_gate.require_tools()
    monkeypatch.setattr(sms_gate.toolchains, "installed", lambda _: {"source": "old", "parts": []})
    with pytest.raises(ValueError, match="differs from the registry"):
        sms_gate.require_tools()


def test_gate_rejects_an_install_manifest_without_binaries(tmp_path, monkeypatch):
    spec = sms_gate.toolchains.get("wla-dx")
    monkeypatch.setattr(sms_gate.toolchains, "installed", lambda _: {"source": spec.source, "parts": spec.parts_for()})
    monkeypatch.setattr(sms_gate.toolchains, "path", lambda _: tmp_path)
    with pytest.raises(ValueError, match="missing or not executable"):
        sms_gate.require_tools()


@pytest.mark.parametrize("kwargs", [{"skipped": True}, {"failed": True}, {"missing_module": True}, {"gg": False},
                                    {"mapper_matrix": False}, {"recovery": False}, {"revalidation": False}, {"archive": False}, {"dependencies": False}, {"undo": False}, {"migration": False}, {"inspection": False}, {"project_archive": False}, {"legacy": False}, {"verification": False}, {"progress": False}, {"export_state": False}, {"c_reference": False}, {"progress_routes": False}, {"artifacts": False}, {"wla": False}, {"symbol_imports": False}, {"adjacent": False}])
def test_gate_rejects_incomplete_or_unsuccessful_execution(tmp_path, kwargs):
    with pytest.raises(ValueError):
        sms_gate.verify_report(report(tmp_path, **kwargs))


def test_gate_requires_a_valid_report_with_executed_tests(tmp_path):
    path = tmp_path / "missing.xml"
    with pytest.raises(ValueError, match="valid JUnit"):
        sms_gate.verify_report(path)
    path.write_text("<testsuite />")
    with pytest.raises(ValueError, match="executed, passing tests"):
        sms_gate.verify_report(path)
    assert sms_gate.verify_report(report(tmp_path)) == len(sms_gate.TESTS) + 143


def test_gate_rejects_gbdk_from_path_without_the_pinned_install(monkeypatch):
    monkeypatch.setattr(sms_gate.toolchains, 'installed', lambda _: None)
    with pytest.raises(ValueError, match='install gbdk-2020'):
        sms_gate.require_tools('gbdk-2020')
