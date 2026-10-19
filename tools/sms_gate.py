"""Run the synthetic SMS/GG assembly checks with pinned tools and no skipped tests."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from decompnet import toolchains

ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "tests/test_sms_asm.py",
    "tests/test_sms_asm_mapping.py",
    "tests/test_sms_mapper_integration.py",
    "tests/test_sms_mapper_hardware.py",
    "tests/test_sms_resplit_history.py",
    "tests/test_sms_resplit_source_check.py",
    "tests/test_sms_resplit_revalidate.py",
    "tests/test_sms_resplit_archive.py",
    "tests/test_sms_resplit_dependencies.py",
    "tests/test_sms_resplit_dependency_integration.py",
    "tests/test_sms_resplit_undo_validation.py",
    "tests/test_sms_profile_migration.py",
    "tests/test_sms_resplit_inspection.py",
    "tests/test_sms_project_archive.py",
    "tests/test_sms_resplit_legacy_integration.py",
    "tests/test_sms_export_verification.py",
    "tests/test_sms_progress.py",
    "tests/test_sms_export_state.py",
    "tests/test_sms_c_reference_export.py",
    "tests/test_sms_progress_routes.py",
    "tests/test_sms_export_artifacts.py",
    "tests/test_sms_wla_layout.py",
    "tests/test_sms_wla_symbols.py",
    "tests/test_sms_wla_tool.py",
    "tests/test_sms_wla_bundle.py",
    "tests/test_sms_symbol_import.py",
    "tests/test_sms_symbol_routes.py",
    "tests/test_sms_symbol_preservation.py",
    "tests/test_sms_symbol_adjacent.py",
    "tests/test_sms_documented.py",
    "tests/test_export_sms.py",
)


def require_tools(tid: str = "wla-dx") -> str:
    """Check the install manifest against the registry, not a fallback assembler on PATH."""
    manifest = toolchains.installed(tid)
    spec = toolchains.get(tid)
    if manifest is None:
        raise ValueError(f"install the pinned tools: decompnet toolchain install {tid}")
    expected = {(p["url"], p["sha256"]) for p in spec.parts_for()}
    installed = {(p["url"], p["sha256"]) for p in manifest.get("parts", [])}
    if not expected or installed != expected or manifest.get("source") != spec.source:
        raise ValueError(f"{tid} install differs from the registry pin; reinstall with --force")
    folder = toolchains.path(tid)
    dirs = [folder] if tid == 'wla-dx' else [folder / 'bin', folder / 'gbdk/bin']
    names = ('wla-z80', 'wlalink') if tid == 'wla-dx' else ('sdcc', 'sdasz80')
    for name in names:
        executables = [directory / (name + ('.exe' if sys.platform == 'win32' else '')) for directory in dirs]
        if not any(exe.is_file() and os.access(exe, os.X_OK) for exe in executables):
            raise ValueError(f"pinned {tid} executable is missing or not executable: {name}")
    return spec.source


def verify_report(report: Path) -> int:
    """Require successful execution in each module, including the GG export cases."""
    try:
        root = ET.parse(report).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError("SMS gate did not produce a valid JUnit report") from exc
    cases = list(root.iter("testcase"))
    if not cases or any(case.find(tag) is not None for case in cases for tag in ("skipped", "error", "failure")):
        raise ValueError("SMS gate requires executed, passing tests with no skips")
    modules = {case.get("classname") for case in cases}
    if not all(test.removesuffix(".py").replace("/", ".") in modules for test in TESTS):
        raise ValueError("SMS gate report is missing a required test module")
    if not any(case.get("classname") == "tests.test_export_sms" and "[gg]" in case.get("name", "")
               for case in cases):
        raise ValueError("SMS gate report is missing Game Gear export checks")
    matrix = {case.get("name") for case in cases if case.get("classname") == "tests.test_sms_mapper_integration"}
    if not all(f"test_declared_models_agree_across_project_consumers[{mapper}-{platform}]" in matrix
               for mapper in ("sega", "mapperless", "codemasters") for platform in ("sms", "gg")):
        raise ValueError("SMS gate report is missing the supported-mapper SMS/GG build matrix")
    recovery = {case.get("name") for case in cases if case.get("classname") == "tests.test_sms_resplit_history"}
    if not all(f"test_changed_documented_source_and_attempts_are_recoverable_and_rebuild_after_undo[{platform}]" in recovery
               for platform in ("sms", "gg")):
        raise ValueError("SMS gate report is missing SMS/GG source recovery and rebuild checks")
    revalidation = {case.get('name') for case in cases if case.get('classname') == 'tests.test_sms_resplit_revalidate'}
    required = {f'test_c_resplit_rechecks_bytes_and_unit_header_and_preserves_provenance[{platform}-{changed}]'
                for platform in ('sms', 'gg') for changed in ('False', 'True')}
    required.update(f'test_assembly_resplit_rechecks_new_cpu_then_inserts_retained_source_in_exact_export[{platform}]'
                    for platform in ('sms', 'gg'))
    if not required <= revalidation:
        raise ValueError('SMS gate report is missing actual C/assembly resplit revalidation checks')
    archive = {case.get('name') for case in cases if case.get('classname') == 'tests.test_sms_resplit_archive'}
    if not all(f'test_saved_source_can_be_recovered_and_rejudged_after_new_work_blocks_undo[{platform}-{kind}]' in archive
               for platform in ('sms', 'gg') for kind in ('c', 'asm')):
        raise ValueError('SMS gate report is missing actual SMS/GG forward recovery checks')
    dependencies = {case.get('name') for case in cases if case.get('classname') == 'tests.test_sms_resplit_dependency_integration'}
    if not all(f'test_nested_unit_dependencies_are_revalidated_and_recoverable_without_layout_changes[{platform}-{changed}]'
               in dependencies for platform in ('sms', 'gg') for changed in ('False', 'True')):
        raise ValueError('SMS gate report is missing actual SMS/GG compiler dependency checks')
    undo = {case.get('name') for case in cases if case.get('classname') == 'tests.test_sms_resplit_undo_validation'}
    required = {f'test_new_edits_during_undo_validation_prevent_restoring_over_them[{platform}-{change}]'
                for platform in ('sms', 'gg') for change in ('note', 'header', 'claim')}
    required.update(f'test_old_accepted_bytes_outside_the_frozen_input_cannot_be_restored[{platform}]' for platform in ('sms', 'gg'))
    if not required <= undo:
        raise ValueError('SMS gate report is missing actual SMS/GG guarded undo checks')
    migration = {case.get('name') for case in cases if case.get('classname') == 'tests.test_sms_profile_migration'}
    required = {f'test_proposed_model_revalidates_unchanged_c_and_undo_restores_the_old_model[{platform}-{mapper}]'
                for platform in ('sms', 'gg') for mapper in ('mapperless', 'codemasters')}
    required.update(f'{test}[{platform}]' for platform in ('sms', 'gg') for test in (
        'test_assembly_is_rejudged_in_the_new_model_with_semantic_review_pending',
        'test_old_documented_entry_without_new_model_placement_is_archived_unaccepted'))
    if not required <= migration:
        raise ValueError('SMS gate report is missing actual SMS/GG profile migration checks')
    inspection = {case.get('name') for case in cases if case.get('classname') == 'tests.test_sms_resplit_inspection'}
    if not all(f'test_every_changed_check_and_overlap_record_can_be_inspected_without_saving[{platform}-{migrate}]'
               in inspection for platform in ('sms', 'gg') for migrate in ('False', 'True')):
        raise ValueError('SMS gate report is missing complete SMS/GG preview inspection checks')
    project = {case.get('name') for case in cases if case.get('classname') == 'tests.test_sms_project_archive'}
    if not all(f'test_project_note_context_and_binary_dependencies_are_recoverable_after_new_work_blocks_undo[{platform}]'
               in project for platform in ('sms', 'gg')):
        raise ValueError('SMS gate report is missing SMS/GG project-context recovery checks')
    legacy = {case.get('name') for case in cases if case.get('classname') == 'tests.test_sms_resplit_legacy_integration'}
    if not all(f'test_old_schema_source_is_migrated_revalidated_and_restored_without_losing_work[{platform}-{kind}]'
               in legacy for platform in ('sms', 'gg') for kind in ('c', 'asm')):
        raise ValueError('SMS gate report is missing actual SMS/GG old-database source integration checks')
    verification = {case.get('name') for case in cases if case.get('classname') == 'tests.test_sms_export_verification'}
    if not all(f'{test}[{platform}]' in verification for platform in ('sms', 'gg') for test in (
        'test_standalone_reports_inserted_disabled_and_required_source_separately',
        'test_changed_assembly_reports_actual_insertion_and_the_image_difference')) or not all(
            f'test_failed_standalone_run_replaces_old_success_receipts_and_artifacts[{platform}-tool]' in verification
            for platform in ('sms', 'gg')):
        raise ValueError('SMS gate report is missing actual SMS/GG structured export verification checks')
    required_progress = {
        'tests.test_sms_progress': {f'test_overview_and_banked_map_use_the_same_union_and_fresh_input_status[{p}]' for p in ('sms', 'gg')} |
                                  {'test_aliases_and_data_overlap_are_measured_as_physical_unions',
                                   'test_current_reference_dates_attribute_overlapping_bytes_once_and_bound_the_chart'},
        'tests.test_sms_export_state': {f'test_last_success_is_historical_after_work_or_input_changes[{p}-{change}]'
                                       for p in ('sms', 'gg') for change in ('source', 'header', 'symbol', 'note', 'profile', 'input', 'missing',
                                                                          'tree', 'artifact', 'receipt', 'baserom', 'tree_missing')} |
                                      {f'{test}[{p}]' for p in ('sms', 'gg') for test in (
                                          'test_failed_preflight_records_a_new_failed_attempt_and_keeps_previous_output',
                                          'test_unbound_legacy_input_cannot_be_promoted_to_an_exact_export',
                                          'test_summary_counts_union_inserted_bytes_and_bounds_omission_bodies',
                                          'test_new_work_during_export_remains_and_prevents_a_current_success_claim',
                                          'test_tree_edit_during_the_build_cannot_bind_a_current_success',
                                          'test_result_edit_after_measurement_cannot_be_bound_to_the_older_success')},
        'tests.test_sms_c_reference_export': {f'test_named_unit_c_reference_keeps_its_header_flags_and_truthful_scope[{p}]' for p in ('sms', 'gg')},
        'tests.test_sms_export_artifacts': {'test_source_edits_and_measured_outputs_change_fingerprint_but_scratch_files_do_not',
                                          'test_caps_and_nonregular_inputs_cannot_be_attested',
                                          'test_symlinks_including_the_output_directory_are_not_followed',
                                          'test_paths_and_permissions_are_framed_unambiguously'},
        'tests.test_sms_progress_routes': {f'test_operator_controls_strict_insertion_and_sees_independent_evidence[{p}]' for p in ('sms', 'gg')} |
            {f'test_configuration_or_helper_failure_replaces_a_stale_standalone_success[{p}-{name}]'
             for p in ('sms', 'gg') for name in ('build.json', 'layout.json', 'tools/sms_export_build_run.py', 'tools/sms_export_artifacts.py')}}
    for module, required in required_progress.items():
        if not required <= {case.get('name') for case in cases if case.get('classname') == module}:
            raise ValueError(f'SMS gate report is missing required progress/export evidence: {module}')
    wla = {case.get('name') for case in cases if case.get('classname') == 'tests.test_sms_wla_tool'}
    symbols = {case.get('name') for case in cases if case.get('classname') == 'tests.test_sms_wla_symbols'}
    if not all(f'test_actual_nonuniform_wla_symbols_seed_the_right_bytes_and_keep_aliases[{p}]' in wla
               for p in ('sms', 'gg')) or not {
                   'test_nonuniform_banks_aliases_duplicate_cpu_windows_and_automatic_seeds_are_distinct',
                   'test_data_ram_locals_unknown_and_impossible_fixed_prefix_do_not_seed_code',
                   'test_public_reader_requires_geometry_or_explicit_physical_code_coordinates'} <= symbols:
        raise ValueError('SMS gate report is missing declared WLA symbol normalization checks')
    imports = {
        'tests.test_sms_symbol_import': {
            f'{test}[{platform}]' for platform in ('sms', 'gg') for test in (
                'test_preview_apply_reload_resplit_and_undo_preserve_source_identity_and_existing_work',
                'test_missing_layout_retains_raw_records_without_applying_names_or_seeds',
                'test_corrupt_bundle_is_visible_and_stops_resplit_without_legacy_fallback',
                'test_remove_disables_sources_and_keeps_original_provenance_without_legacy_fallback',
                'test_failed_database_publication_does_not_change_the_active_source_or_functions',
                'test_inspection_pages_preserve_every_alias_and_reject_a_changed_source')} |
            {f'test_stale_preview_never_replaces_current_source_or_work[{platform}-{change}]'
             for platform in ('sms', 'gg') for change in ('source', 'work', 'input')},
        'tests.test_sms_symbol_routes': {f'test_authenticated_preview_apply_and_inspection_preserve_binary_source_without_exposing_it[{p}]'
                                         for p in ('sms', 'gg')},
        'tests.test_sms_symbol_preservation': {f'test_declared_symbol_import_retains_actual_{kind}_and_resplit_undo[{p}]'
                                               for p in ('sms', 'gg') for kind in ('documented_source', 'c_match')}}
    for module, required in imports.items():
        if not required <= {case.get('name') for case in cases if case.get('classname') == module}:
            raise ValueError(f'SMS gate report is missing project symbol preservation checks: {module}')
    adjacent = {case.get('name') for case in cases if case.get('classname') == 'tests.test_sms_symbol_adjacent'}
    modes = ('declared', 'missing', 'malformed', 'different_revision', 'invalid_geometry', 'null', 'new_version',
             'wrong_crc', 'oversized', 'bad_source', 'future_symbols')
    if not {f'test_initial_sidecar_import_preserves_bytes_and_never_guesses_nonuniform_geometry[{platform}-{mode}]'
            for platform in ('sms', 'gg') for mode in modes} <= adjacent or not {
                f'{test}[{p}]' for p in ('sms', 'gg') for test in (
                    'test_legacy_layout_uncertainty_preserves_actual_accepted_source_and_recovery',
                    'test_stored_inspection_cannot_mix_mapper_contexts_with_the_same_source_bytes')} <= adjacent:
        raise ValueError('SMS gate report is missing declared/pending adjacent-source and legacy recovery checks')
    return len(cases)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    # Keep artifacts ignored by default, and remove stale reports before starting the process.
    report = (args.report or ROOT / "build" / "sms-tool-tests.xml").resolve()
    try:
        print(f"SMS gate toolchains: {require_tools()}; {require_tools('gbdk-2020')}", flush=True)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.unlink(missing_ok=True)
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                               f"--junitxml={report}", *TESTS], cwd=ROOT)
        if proc.returncode:
            return proc.returncode
        count = verify_report(report)
    except ValueError as exc:
        print(f"SMS gate failed: {exc}", file=sys.stderr)
        return 1
    print(f"SMS gate: {count} passed, zero skipped (SMS and GG)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
