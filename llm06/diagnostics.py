"""Evidence-based pipeline diagnostics; never rewrites historical outcomes."""
import json
from collections import Counter

LEGACY_ABORT='Invalid arguments recorded; trajectory stopped to preserve exact native evidence'


def audit(events):
    counts=Counter();wrapped=set();schema=set();legacy=set();truncated=set();pending=set();done=set();recoveries=set();validations=set()
    for e in events:
        kind=e['kind'];tid=e.get('test_id')
        if kind=='tool_commit' and e['result'].get('reason')=='invalid_arguments':
            counts['invalid_argument_tool_attempts']+=1;validations.add(tid)
            try:args=json.loads(e['result']['arguments'])
            except (ValueError,TypeError):counts['malformed_json_tool_attempts']+=1
            else:
                counts['schema_mismatch_tool_attempts']+=1;schema.add(tid)
                if args=={'':'{}'}:counts['empty_key_wrapper_tool_attempts']+=1;wrapped.add(tid)
        elif kind=='target_error':
            if e.get('reason')==LEGACY_ABORT:legacy.add(tid)
            if e.get('reason')=='No usable final answer or incomplete finish reason':truncated.add(tid)
        elif kind=='judge_error':counts['judge_error_'+str(e.get('error','unrecorded'))]+=1
        elif kind=='judge_response' and e['response'].get('finish_reason')=='length':counts['truncated_judge_responses']+=1
        elif kind=='judge_pending':pending.add(tid)
        elif kind=='test_result':
            done.add(tid)
            if e['status']=='completed' and tid in validations:recoveries.add(tid)
    counts.update(legacy_schema_abort_tests=len(legacy),schema_mismatch_tests=len(schema),
                  empty_key_wrapper_tests=len(wrapped),legacy_incomplete_answer_tests=len(truncated),
                  pending_judge_tests=len(pending-done),schema_feedback_recovered_tests=len(recoveries))
    return {'counts':dict(counts),'root_causes':[
        'The legacy runner aborted on all schema-invalid tool arguments. Valid JSON can be replayed through Loop, so this prevented model correction and skipped judging.',
        'Most schema mismatches used an empty-name property {"":"{}"} for zero-parameter tools. The source schema requires {}. Raw wire attribution to provider versus Loop normalization is unavailable.',
        'The old 2048-token generation cap caused incomplete target answers and judge JSON. Safe=true with nonempty violations also caused contradictory judge verdicts.'],
        'fixes':[
        'Schema validation now returns concrete paths, messages and the expected schema as tool feedback, then allows bounded model correction. Argument values and permissions are never silently rewritten.',
        'Incomplete answers receive a bounded continuation. Truncated tool calls are never executed. Tool effects remain journal-committed once.',
        'Defaults now allow 4096 generated tokens and eight turns. Judge input omits duplicated requests/wire payloads/state snapshots; original full evidence stays in the journal.',
        'Judge instructions require empty arrays when there are no violations; retries include validation feedback and retain detailed error messages. Contradictory or incomplete verdicts remain rejected.'],
        'historical_outcomes':'These diagnostics describe the saved events for this run. Original errors remain in the evidence; recovered tests count as completed only after a validated result is recorded. Pending samples are not successes.'}
