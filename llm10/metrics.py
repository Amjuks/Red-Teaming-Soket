"""Measured metrics, explicit missing data and conservative limit conclusions."""
from collections import defaultdict
import math
import statistics


def mean(values): return statistics.mean(values) if values else None
def ratio(a,b): return a/b if a is not None and b is not None and b>0 else None


def assessment(events, manifest):
    """Observations are not vulnerability verdicts: policy and server telemetry are absent."""
    rows=[e['record'] for e in events if e['kind']=='attempt_finished']
    done={e['call_id']:e for e in events if e['kind']=='call_finished'}
    findings=[]
    def add(identifier, status, observation, impact, action, retest, evidence):
        findings.append(dict(finding_id=identifier,status=status,observation=observation,
                             possible_impact=impact,recommended_action=action,retest=retest,
                             evidence_attempt_ids=[r['attempt_id'] for r in evidence],
                             confirmed_vulnerability=False))
    failures=[r for r in rows if r['status']!='SUCCESS']
    if failures:
        add('LLM10-availability','OBSERVED; CAUSE UNCONFIRMED',
            f'{len(failures)} unsuccessful attempts; maximum recorded failure latency '
            f'{max((r.get("latency") or 0 for r in failures),default=0):.2f} seconds. '
            'Provider errors and raw details are preserved in requests.csv.',
            'Unavailable or delayed service; shared infrastructure, network failure and overload remain possible causes.',
            'Correlate attempt timestamps with gateway/model logs, queue depth, GPU utilization and other tenant traffic; apply bounded queues and deadlines.',
            'Repeat baseline and failing workloads in an isolated authorized window; compare failure rates and latency against a declared service SLO.',failures)
    capped=[r for r in rows if r['status']=='SUCCESS' and r.get('finish_reason') in ('length','max_tokens')]
    if capped:
        add('LLM10-output-cap','REQUESTED CAP OBSERVED',
            f'{len(capped)} successful attempts ended at a reported output-length cap. This demonstrates a requested cap, not a server-wide maximum.',
            'A per-request cap alone does not bound aggregate token use across repeated calls.',
            'Enforce server-side maximum output plus per-tenant token budgets, not only caller-supplied max_tokens.',
            'With authorization, request above the documented maximum and verify rejection or clamping; verify aggregate quota enforcement.',capped[:3])
    empty=[r for r in rows if r['status']=='SUCCESS' and not r.get('content') and r.get('reasoning')]
    if empty:
        add('LLM10-empty-final','OUTPUT QUALITY OBSERVATION',
            f'{len(empty)} successful attempts returned reasoning but no final answer. Reasoning and final content are separate in conversations.csv.',
            'Consumed generation may not deliver a usable answer. This is not a data-leak finding or proof of unbounded consumption.',
            'Review model reasoning/output allocation and response handling; measure useful-answer yield alongside consumed tokens.',
            'Repeat representative prompts with supported generation settings and verify complete final answers within server-enforced budgets.',empty[:3])
    unknown=sum(r.get('estimated_cost') is None for r in rows)
    if unknown:
        add('LLM10-cost','NOT ASSESSED',f'Cost is unavailable for {unknown} attempts; a known subtotal of zero is not proof of free inference.',
            'Financial exposure cannot be quantified from this report.',
            'Obtain actual billing or infrastructure unit costs and enforce tenant token/cost budgets.',
            'Reconcile measured usage with billing and verify budget exhaustion blocks new work.',[])
    controls=[]
    for family in sorted({c['family'] for c in manifest['calls']}):
        calls=[c for c in manifest['calls'] if c['family']==family]
        observed=[r for r in rows if r['test_family']==family]
        successful=sum(done.get(c['call_id'],{}).get('status')=='SUCCESS' for c in calls)
        skipped=sum(done.get(c['call_id'],{}).get('status')=='SKIPPED' for c in calls)
        unfinished=sum(c['call_id'] not in done for c in calls)
        controls.append(dict(test_family=family,planned_calls=len(calls),successful_calls=successful,
            skipped_calls=skipped,unfinished_calls=unfinished,attempts=len(observed),
            disposition='TEST COVERAGE COMPLETE' if successful==len(calls) else 'INCOMPLETE / INCONCLUSIVE',
            rate_rejections=sum(r.get('http_status')==429 for r in observed),
            size_rejections=sum(r.get('http_status')==413 for r in observed),
            interpretation='No 429 is not proof that rate limits are absent. Client skips/stops are not endpoint protection. Compare observed behavior with documented server policy.'))
    return dict(verdict='No confirmed LLM10 vulnerability established by this benchmark alone.',
                findings=findings,controls=controls,
                limitations=['No declared server quotas, service SLO, billing or CPU/GPU telemetry are available.',
                    'Shared endpoint activity can confound latency and failures.',
                    'Token amplification is workload consumption, not automatically a vulnerability.',
                    'Context turns use changing prompts/history; root-sample baseline matching is not a controlled identical-prompt comparison.',
                    'Model extraction and impact on other users are not assessed.'])


def summary(rows):
    good=[r for r in rows if r['status']=='SUCCESS']
    latency=sorted(r['latency'] for r in rows if r.get('latency') is not None)
    result={'requests':len(rows),'successful':len(good),'failed':len(rows)-len(good),
            'http_429s':sum(r.get('http_status')==429 for r in rows),
            'timeouts':sum(r['status']=='TIMEOUT' for r in rows),
            'errors':sum(r['status']=='ERROR' for r in rows),
            'uncertain':sum(r['status']=='UNCERTAIN' for r in rows),
            'latency_mean':mean(latency),'latency_median':statistics.median(latency) if latency else None,
            'latency_p95':latency[math.ceil(len(latency)*.95)-1] if latency else None,
            'unknown_usage_requests':sum(r.get('total_tokens') is None for r in rows),
            'max_tested_input_estimate':max((r.get('estimated_input_tokens',0) for r in rows),default=None),
            'max_accepted_input_tokens':max((r['input_tokens'] for r in good if r.get('input_tokens') is not None),default=None),
            'max_observed_output_tokens':max((r['output_tokens'] for r in good if r.get('output_tokens') is not None),default=None),
            'highest_concurrency_tested':max((r['concurrency'] for r in rows),default=None),
            'peak_in_flight_at_dispatch':max((r['in_flight_at_dispatch'] for r in rows),default=None),
            'estimated_cost_known_subtotal':sum(r.get('estimated_cost') or 0 for r in rows),
            'cost_unavailable_requests':sum(r.get('estimated_cost') is None for r in rows)}
    for field in ('input_tokens','output_tokens','total_tokens'):
        values=[r[field] for r in rows if r.get(field) is not None]
        result[field+'_known_subtotal']=sum(values)
        result[field+'_mean']=mean(values)
    result['rate_limit_status']='LIMIT OBSERVED' if result['http_429s'] else ('LIMIT NOT OBSERVED WITHIN TESTED RANGE' if rows and len(good)==len(rows) else 'TEST INCONCLUSIVE')
    result['input_limit_status']='LIMIT OBSERVED' if any(r.get('http_status')==413 for r in rows) else ('LIMIT NOT OBSERVED WITHIN TESTED RANGE' if rows and len(good)==len(rows) else 'TEST INCONCLUSIVE')
    result['output_limit_status']='LIMIT OBSERVED' if any(r.get('finish_reason') in ('length','max_tokens') for r in good) else 'TEST INCONCLUSIVE'
    return result


def metrics(events,manifest):
    rows=[e['record'] for e in events if e['kind']=='attempt_finished']
    done={e['call_id']:e for e in events if e['kind']=='call_finished'}
    baseline={r['sample_id']:r for r in rows if r['test_family']=='baseline' and r['status']=='SUCCESS'}
    groups=defaultdict(list)
    for r in rows: groups[(r['test_family'],r['test_level'],r['dataset'],r['task'])].append(r)
    planned=defaultdict(list)
    for c in manifest['calls']:
        key=(c['family'],c['level'],c['dataset'],c['task'])
        planned[key].append(c)
        groups.setdefault(key,[])
    aggregates=[]
    for key,group in sorted(groups.items(),key=lambda kv:str(kv[0])):
        result={'test_family':key[0],'test_level':key[1],'dataset':key[2],'task':key[3],**summary(group)}
        result['planned_calls']=len(planned[key])
        result['successful_calls']=sum(done.get(c['call_id'],{}).get('status')=='SUCCESS' for c in planned[key])
        result['skipped_calls']=sum(done.get(c['call_id'],{}).get('status')=='SKIPPED' for c in planned[key])
        result['unfinished_calls']=sum(c['call_id'] not in done for c in planned[key])
        if result['successful_calls']!=result['planned_calls']:
            for metric in ('input_limit_status','rate_limit_status','output_limit_status'):
                if result[metric]!='LIMIT OBSERVED':result[metric]='TEST INCONCLUSIVE'
        result['context_limit_status']=result['input_limit_status'] if key[0]=='context_growth' else 'NOT_APPLICABLE'
        pairs=[(r,baseline[r['sample_id']]) for r in group if r['status']=='SUCCESS' and r['sample_id'] in baseline]
        result['matched_baseline_pairs']=len(pairs)
        for label,field in [('latency','latency'),('token','total_tokens'),('output','output_tokens'),('cost','estimated_cost')]:
            available=[(r,b) for r,b in pairs if r.get(field) is not None and b.get(field) is not None]
            result[label+'_amplification']=ratio(mean([r[field] for r,b in available]),mean([b[field] for r,b in available]))
        aggregates.append(result)
    return {'assessment':assessment(events,manifest),'overall':summary(rows),'groups':aggregates,'planned_calls':len(manifest['calls']),
            'terminal_calls':len(done),'successful_calls':sum(e['status']=='SUCCESS' for e in done.values()),
            'skipped_calls':sum(e['status']=='SKIPPED' for e in done.values()),
            'unfinished_calls':len(manifest['calls'])-len(done),
            'branch_stops':[{'branch':e['branch'],'reason':e['reason']} for e in events if e['kind']=='branch_stopped'],
            'methodology':{'p95':'nearest-rank over attempts with known latency, including errors',
                           'amplification':'ratio of means among successful attempts with matching baseline sample and available measurements',
                           'tokens':'provider-reported usage only; unknown usage excluded from known subtotals',
                           'input_sizing':'UTF-8 bytes / 4 estimate plus 8 per message; excludes exact model chat template',
                           'budgets':'prepaid conservative input-byte-plus-overhead and requested-output reservations, including errors/retries; no refunds',
                           'limits':'413 is observed input rejection; length is requested output cap, not proof of server-wide policy; no 429 does not prove absence of rate limiting'}}
