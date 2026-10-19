"""Required SMS/GG annotation workflow evidence, kept separate from the tool runner."""
from decompnet.rom.annotations.payloads import KINDS


def verify(cases):
    names = lambda module: {case.get('name') for case in cases if case.get('classname') == f'tests.{module}'}
    metadata = names('test_sms_annotation_storage')
    required = {f'test_actual_accepted_work_and_old_pending_undo_survive_annotation_migration[{p}-{kind}]'
                for p in ('sms', 'gg') for kind in ('c', 'asm')} | {
                    f'test_tagged_corrections_cannot_override_actual_accepted_code_before_qualified_consumption[{p}-{state}-{field}]'
                    for p in ('sms', 'gg') for state in ('supported', 'future', 'invalid') for field in ('annotation', 'evidence')}
    if not required <= metadata:
        raise ValueError('SMS gate report is missing actual SMS/GG annotation migration and inactive-metadata checks')
    facts = names('test_sms_correction_facts')
    required = {f'{test}[{p}-{kind}]' for p in ('sms', 'gg') for kind in KINDS for test in (
        'test_every_kind_is_bound_pending_inspectable_and_undoable_after_reload',
        'test_operator_review_is_separate_from_recording_and_only_legacy_kinds_feed_hints')}
    if not required <= facts:
        raise ValueError('SMS gate report is missing the SMS/GG versioned correction kind matrix')
    integration = names('test_sms_correction_integration')
    required = {f'{test}[{p}-{kind}]' for p in ('sms', 'gg') for kind in ('c', 'asm') for test in (
        'test_qualified_five_kinds_drive_discovery_and_preserve_real_source_through_resplit_undo',
        'test_pending_and_forged_data_cannot_override_actual_accepted_source_and_review_refuses_it')} | {
            f'test_changed_original_input_disables_previously_reviewed_hints_without_erasing_evidence[{p}]' for p in ('sms', 'gg')}
    if not required <= integration:
        raise ValueError('SMS gate report is missing real SMS/GG correction discovery and source-protection checks')
    authority = names('test_sms_correction_authority')
    required = {f'{test}[{p}]' for p in ('sms', 'gg') for test in (
        'test_review_and_inspection_hold_one_database_snapshot_against_other_connections',
        'test_review_checks_new_work_and_rolls_back_a_failed_authority_event',
        'test_a_receipt_cannot_authorize_a_different_record_or_restore_superseded_approval',
        'test_actual_mcp_preview_is_structured_and_rejects_boolean_counts_or_numeric_apply_flags')}
    if not required <= authority:
        raise ValueError('SMS gate report is missing SMS/GG correction authority and actual MCP checks')
    routes = names('test_sms_correction_routes')
    required = {f'test_authenticated_proposal_inspection_review_and_undo_use_existing_routes[{p}]' for p in ('sms', 'gg')} | {
        f'test_http_does_not_coerce_invalid_correction_arguments[{p}-{field}-{value}]' for p in ('sms', 'gg')
        for field, value in (('apply', '1'), ('count', 'True'), ('count', '2'))}
    if not required <= routes:
        raise ValueError('SMS gate report is missing authenticated SMS/GG correction routes')
