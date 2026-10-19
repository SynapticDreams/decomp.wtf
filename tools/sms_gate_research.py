"""Required note/symbol subject, lifecycle, source identity and authority checks."""


def required():
    platforms, kinds = ('sms', 'gg'), ('note', 'symbol')
    return {
        'test_store_subjects': {
            'test_previous_metadata_migrates_without_inventing_subjects_or_changing_saved_contexts',
            'test_second_subject_alter_failure_rolls_back_both_tables_and_keeps_all_old_metadata'},
        'test_sms_annotation_subjects': {
            f'test_notes_and_symbols_bind_full_subjects_and_reload_without_inventing_ram_contents[{p}-{space}-{kind}]'
            for p in platforms for space in ('None', 'rom', 'wram', 'cart_ram') for kind in kinds} | {
                f'{test}[{p}-{kind}]' for p in platforms for kind in kinds for test in (
                    'test_metadata_replacement_and_detachment_archive_original_subject_and_receipts',
                    'test_changed_inputs_make_research_unavailable_but_opaque_metadata_can_be_detached')} | {
                        f'{test}[{p}]' for p in platforms for test in (
                            'test_full_length_notes_and_large_valid_record_payloads_fit_guarded_request_framing',
                            'test_orphan_note_subject_retains_its_original_attachment_without_inventing_a_function')},
        'test_sms_symbol_evidence_lifecycle': {
            f'test_actual_c_and_assembly_keep_research_through_resplit_and_archive_original_subject_on_rename[{p}-{kind}]'
            for p in platforms for kind in ('c', 'asm')} | {f'{test}[{p}]' for p in platforms for test in (
                'test_split_and_merge_preserve_metadata_as_original_subject_without_inheriting_approval',
                'test_idempotent_symbol_refresh_preserves_raw_future_metadata_and_changed_role_archives_it',
                'test_rename_refuses_new_work_during_source_checks_and_preserves_the_new_observation',
                'test_research_status_is_visible_in_briefs_and_archives_stay_out_of_active_context')},
        'test_sms_annotation_sources': {f'{test}[{p}]' for p in platforms for test in (
            'test_declared_symbol_sources_support_all_research_records_and_ignore_presentation_metadata',
            'test_changed_or_missing_source_bundle_is_unavailable_without_erasing_original_evidence')},
        'test_sms_annotation_routes': {
            f'test_note_and_symbol_operator_routes_require_authenticated_exact_previews_for_review_and_detachment[{p}-{kind}]'
            for p in platforms for kind in kinds} | {
                f'test_actual_mcp_note_symbol_and_inspection_tools_preserve_plaintext_calls_and_do_not_expose_review[{p}]' for p in platforms},
        'test_sms_annotation_safety': {f'{test}[{p}-{kind}]' for p in platforms for kind in kinds for test in (
            'test_metadata_write_and_review_failures_roll_back_archives_and_keep_new_work',
            'test_review_reads_row_binding_and_guard_in_one_snapshot_for_other_database_connections',
            'test_caller_review_receipts_and_tampered_future_subjects_are_not_accepted')} | {
                f'{test}[{p}]' for p in platforms for test in (
                    'test_copied_or_superseded_note_receipts_do_not_authorize_identical_new_subjects',
                    'test_note_and_symbol_pages_are_complete_and_legacy_metadata_keeps_unknown_subjects')}}


def verify(cases):
    for module, expected in required().items():
        actual = {case.get('name') for case in cases if case.get('classname') == f'tests.{module}'}
        if not expected <= actual:
            raise ValueError(f'SMS gate report is missing required note/symbol research checks: {module}')
