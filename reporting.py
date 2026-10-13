"""Versioned common report envelope and overview; native evidence stays intact."""
import html
import json
import os
from pathlib import Path
import tempfile

VERSION = '2.1.0'
TITLES = {'llm02': 'Sensitive Information Disclosure', 'llm06': 'Excessive Agency',
          'llm10': 'Unbounded Consumption'}


def atomic_text(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def envelope(benchmark, run_id, model, progress, coverage, metrics, findings,
             limitations, artifacts):
    """Completion describes execution only. Unknown assessment remains unknown."""
    if progress['planned'] != sum(progress[k] for k in ('completed', 'errored', 'skipped', 'pending')):
        raise ValueError('Common report progress does not reconcile')
    if any(not isinstance(v, int) or v < 0 for k, v in progress.items() if k != 'unit'):
        raise ValueError('Progress counts must be nonnegative integers')
    from run_names import run_name
    name = run_name(benchmark, model, run_id, progress['planned'], progress['unit'])
    return {'schema_version': VERSION, 'benchmark': {'id': benchmark, 'title': TITLES[benchmark]},
            'run': {'id': run_id, 'name': name, 'model': {k: model[k] for k in ('model', 'provider', 'mode', 'transport') if k in model},
                    'execution_state': 'partial' if progress['pending'] else 'finished'},
            'progress': progress, 'coverage': coverage, 'metrics': metrics, 'findings': findings,
            'limitations': limitations, 'artifacts': artifacts}


def finding(identifier, title, status, severity, evidence, details):
    return dict(id=identifier, title=title, status=status, severity=severity,
                evidence=evidence, details=details)


def publish(benchmark, run_id, model, data, coverage, directory, report_directory, findings=None, configuration=None):
    """Adapt native aggregates without regrading results or flattening denominators."""
    directory, report_directory = Path(directory), Path(report_directory)
    if benchmark == 'llm02':
        overall = data['overall']
        progress = dict(unit='test', planned=data['total_tests'], completed=overall['completed'],
                        errored=overall['errors'], skipped=0, pending=data['unexecuted'])
        normalized = [finding(f['id'], f['description'], 'observed_disclosure', f['severity'].lower(),
                              [{'test_id': t} for t in f['test_ids']], f) for f in data['findings']]
        limitations = ['Markdown report omits raw protected values and responses; evidence exports are private.',
                       'Completed execution does not imply a graded result. ASR uses graded attacks only.',
                       'NO_LEAK means no detected disclosure, not proof of privacy. Source groups can overlap.']
        names = ['metrics.json', 'raw_results.jsonl', 'summary.csv', 'test_details.csv', 'successful_attacks.csv',
                 'conversation_turns.csv', 'leak_evidence.csv', 'findings.csv', 'failures.csv', 'unexecuted.csv',
                 'coverage.csv', 'configuration.csv', 'events.jsonl']
    elif benchmark == 'llm06':
        counts = data['status_counts']
        completed, errored = counts.get('completed', 0), counts.get('errored', 0)
        progress = dict(unit='scenario_variant', planned=data['planned'], completed=completed,
                        errored=errored, skipped=0, pending=data['planned']-completed-errored)
        normalized = [finding(f.get('finding_id', f'{run_id}:{i}'), f['rule'], 'judge_assessment' if f.get('rule')=='semantic_judge' else 'observed_policy_violation', f['severity'].lower(),
                              [{'test_id': f['test_id'], 'event_seq': f.get('evidence_seq')}], f)
                      for i, f in enumerate(findings or [], 1)]
        limitations = ['All tool effects are simulated; blocked unsafe attempts can still be findings.',
                       'Completed conversations do not establish task success. Unknown outcomes are not passes.',
                       'Catalog effect probes deny approval; source adaptations and coverage exclusions remain in native evidence.',
                       'Semantic assessments require a configured judge. Group counts may overlap.']
        names = ['metrics.json', 'results.jsonl', 'scenarios.csv', 'tool_calls.csv', 'conversations.csv', 'findings.csv', 'events.jsonl']
    else:
        progress = dict(unit='workload_call', planned=data['planned_calls'], completed=data['successful_calls'],
                        errored=data['terminal_calls']-data['successful_calls']-data['skipped_calls'],
                        skipped=data['skipped_calls'], pending=data['unfinished_calls'])
        normalized = [finding(f['finding_id'], f['observation'], f['status'], None,
                              [{'attempt_id': a} for a in f['evidence_attempt_ids']], f)
                      for f in data['assessment']['findings']]
        limitations = list(data['assessment']['limitations']) + [
            'Progress counts workload calls; consumption metrics count attempts, including retries.',
            'Client skips are not server protection. Unknown usage and cost are not zero.']
        names = ['metrics.json', 'results.jsonl', 'requests.csv', 'conversations.csv', 'summary.csv',
                 'call_status.csv', 'control_assessment.csv', 'findings.csv', 'events.jsonl']
    names += ['failed_instances.csv','failed_instances_summary.json']
    artifacts = [dict(name=name, path=os.path.relpath(directory/name, report_directory),
                      media_type='text/csv' if name.endswith('.csv') else 'application/x-ndjson' if name.endswith('.jsonl') else 'application/json',
                      sensitivity='private') for name in names if (directory/name).is_file()]
    doc = envelope(benchmark, run_id, model, progress, coverage, data, normalized, limitations, artifacts)
    doc = normalize(doc, configuration or {})
    summary_path=directory/'failed_instances_summary.json'
    if summary_path.exists():doc['failure_export']=json.loads(summary_path.read_text())
    atomic_text(report_directory/'report.json', json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    text = overview(doc)
    atomic_text(report_directory/'report.md', text)
    return text


def measure(name, value, unit='count', numerator=None, denominator=None, population='recorded outcomes'):
    return dict(name=name, value=value, unit=unit, numerator=numerator,
                denominator=denominator, population=population)


def normalize(doc, configuration):
    """All risks expose identical metric, coverage, group and finding records."""
    native, coverage = doc['metrics'], doc['coverage']
    benchmark = doc['benchmark']['id']
    measures, groups = [], []

    def flatten(mapping, population):
        output = []
        for key, value in mapping.items():
            if isinstance(value, dict) and {'numerator','denominator','rate'} <= value.keys():
                output.append(measure(key, value['rate'], 'ratio', value['numerator'], value['denominator'], value.get('eligibility', population)))
            elif isinstance(value, (int, float)) or value is None:
                unit = 'ratio' if 'rate' in key or 'amplification' in key else 'seconds' if 'latency' in key else 'tokens' if 'tokens' in key else 'count'
                output.append(measure(key, value, unit, population=population))
                if 'amplification' in key:
                    components=mapping.get(key+'_components',{})
                    output[-1]['numerator']=components.get('workload_mean')
                    output[-1]['denominator']=components.get('baseline_mean')
                    output[-1]['population']='Ratio of workload mean to matched baseline mean; '+str(components.get('matched_pairs',mapping.get('matched_baseline_pairs',0)))+' usable matched pairs'
                    if value is None and components:
                        reason=('No matched pairs with both measurements recorded.' if not components['matched_pairs'] else 'Matched baseline mean is zero; the ratio is undefined.')
                        output[-1]['missing_reasons']={k:reason for k in ('value','numerator','denominator') if output[-1][k] is None}

        return output

    if benchmark == 'llm02':
        overall = native.get('overall',{})
        measures = flatten(overall, 'recorded tests; rates use graded eligible tests only')
        rate_counts = {'attack_success_rate': (overall.get('leaks'), overall.get('attack_denominator')),
                       'false_refusal_rate': (overall.get('false_refusals'), overall.get('control_denominator')),
                       'appropriate_refusal_rate': (overall.get('appropriate_refusals'),overall.get('attack_denominator'))}
        classifications={'full_leakage_rate':'FULL_LEAK','partial_leakage_rate':'PARTIAL_LEAK','semantic_leakage_rate':'SEMANTIC_LEAK','reconstructable_leakage_rate':'RECONSTRUCTABLE_LEAK'}
        for key,label in classifications.items():rate_counts[key]=(overall.get('classification_counts',{}).get(label,0),overall.get('attack_denominator'))
        for m in measures:
            if m['unit']=='ratio':
                m['denominator'] = overall.get('control_denominator') if m['name']=='false_refusal_rate' else overall.get('attack_denominator')
                m['population'] = 'graded controls' if m['name']=='false_refusal_rate' else 'graded attacks'
                if m['name'] in rate_counts: m['numerator'] = rate_counts[m['name']][0]
        for dimension, values in native.get('breakdowns', {}).items():
            for label, group in values.items():
                gm=flatten(group, 'graded attacks/controls in group; source groups overlap')
                for m in gm:
                    if m['unit']=='ratio':
                        m['denominator']=group.get('control_denominator') if m['name']=='false_refusal_rate' else group.get('attack_denominator')
                        if m['name']=='attack_success_rate':m['numerator']=group.get('leaks')
                        elif m['name'] in classifications:m['numerator']=group.get('classification_counts',{}).get(classifications[m['name']],0)
                        elif m['name']=='false_refusal_rate':m['numerator']=group.get('false_refusals')
                        elif m['name']=='appropriate_refusal_rate':m['numerator']=group.get('appropriate_refusals')
                groups.append(dict(dimension=dimension, group=str(label), metrics=gm))
        assessment = dict(verdict=native.get('overall_risk','not_assessed'),
                          assessed=overall.get('graded'), unassessed=overall.get('ungraded'),
                          population='completed tests', judge=configuration.get('evaluation',{}).get('judge') if configuration.get('evaluation',{}).get('semantic_judge') else None)
    elif benchmark == 'llm06':
        measures=flatten(native, 'planned scenario/variant tests unless explicitly stated')
        for dimension, values in native.items():
            if dimension.startswith('by_'):
                for label, group in values.items():
                    groups.append(dict(dimension=dimension[3:], group=str(label), metrics=flatten(group,'group tests or tool attempts; groups can overlap')))
        for reason, count in native.get('execution_errors',{}).items():
            groups.append(dict(dimension='execution_error',group=reason,metrics=[measure('errors',count)]))
        for status,count in native.get('status_counts',{}).items():
            groups.append(dict(dimension='execution_status',group=status,metrics=[measure('tests',count)]))
        unassessed=native.get('unassessed')
        assessment=dict(verdict='Review established violations and judge assessments; unknown outcomes are not passes.',
                        assessed=native['planned']-unassessed if unassessed is not None else None,
                        unassessed=unassessed, population='all planned tests; known safety and task completion required', judge=configuration.get('judge'))
    else:
        measures=flatten(native.get('overall',{}),'API attempts, including retries; only known usage contributes to subtotals')
        for group in native.get('groups',[]):
            label=' / '.join(str(group.get(k,'')) for k in ('test_family','test_level','dataset','task'))
            groups.append(dict(dimension='workload',group=label,metrics=flatten(group,'API attempts in workload group; call counts explicitly named')))
        assessment=dict(verdict=native['assessment'].get('verdict','not_assessed'),assessed=None,unassessed=None,
                        population='server policy violations; benchmark execution alone is insufficient',judge=None)
    normalized_coverage=[]
    datasets=coverage.get('datasets',{})
    if benchmark=='llm10': datasets={k:v for k,v in coverage.items() if not k.startswith('_') and isinstance(v,dict)}
    if isinstance(datasets,dict):
        for source, values in datasets.items():
            normalized_coverage.append(dict(source=source,counts=flatten(values if isinstance(values,dict) else {},'source records'),details=values if isinstance(values,dict) else {'value':values}))
    if not normalized_coverage:
        normalized_coverage=[dict(source=str(coverage.get('dataset',benchmark)), counts=flatten(coverage,'source records'),details=coverage)]
    for f in doc['findings']:
        raw=f['details']
        f.update(observation=raw.get('observation',raw.get('actual',raw.get('description',f['title']))),
                 impact=raw.get('possible_impact',raw.get('why_risky',str(raw.get('impact','Not quantified')))),
                 recommendation=raw.get('recommended_action',raw.get('recommendation',raw.get('mitigation','Review the evidence.'))),
                 retest=raw.get('retest',raw.get('retest_criteria','Repeat the affected tests.')))
    # Native structures remain lossless, but consumers need only the common fields.
    doc.update(metrics=measures,coverage=normalized_coverage,breakdowns=groups,assessment=assessment,
               configuration={k:v for k,v in configuration.items() if not k.startswith('_')},
               extensions={'metrics':native,'coverage':coverage})
    explain_availability(doc)
    return doc


def md(value):
    if value is None: return 'Not recorded — the saved source record did not supply this field'
    text=html.escape(str(value),quote=False).replace('\n',' ').replace('\r',' ')
    for char in ('\\','`','*','_','[',']','|'):
        text=text.replace(char,'\\'+char)
    return text


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join('---' for _ in headers)+' |']+
                     ['| '+' | '.join(md(v) for v in row)+' |' for row in rows])+'\n'


def metric_rows(metrics):
    for m in metrics:
        reasons=m.get('missing_reasons',{})
        value = f"{m['value']:.2%}" if m['unit']=='ratio' and m['value'] is not None else m['value']
        yield [m['name'],value if value is not None else reasons.get('value'),m['unit'],
               m['numerator'] if m['numerator'] is not None else reasons.get('numerator'),
               m['denominator'] if m['denominator'] is not None else reasons.get('denominator'),m['population'],m.get('notes','')]


def fenced_json(value):
    text=json.dumps(value,ensure_ascii=False,indent=2)
    import re
    fence='`'*max(3,1+max((len(m.group()) for m in re.finditer(r'`+',text)),default=0))
    return fence+'json\n'+text+'\n'+fence


def overview(doc):
    """The actual assessment, not a navigation page; identical sections for all risks."""
    # envelope() is also used by callers building minimal reports.
    if 'assessment' not in doc: doc=normalize(doc,{})
    p=doc['progress']; a=doc['assessment']
    lines=[f"# {md(doc['benchmark']['id'].upper())} — {md(doc['benchmark']['title'])}",
           f"Run: **{md(doc['run']['name'])}** · Schema: {VERSION}",
           'SYNTHETIC MOCK DEMONSTRATION' if doc['run']['model'].get('mode')=='mock' else 'Recorded model assessment',
           '## Summary',md(a['verdict']),
           f"{p['completed']} completed, {p['errored']} errored, {p['skipped']} skipped, {p['pending']} pending out of {p['planned']} {md(p['unit'])}.",
           'This is a saved-evidence assessment. Execution completion is not a security pass. Partial means unfinished work, not that a process is running.',
           '## Run configuration',
           table(['Field','Value'], [('Run ID',doc['run']['id']),('Model',doc['run']['model'].get('model')),('Provider',doc['run']['model'].get('provider')),('Execution state',doc['run']['execution_state']),('Judge',a['judge'].get('model') if a['judge'] else 'disabled / not applicable')]),
           'Full configuration:', fenced_json(doc.get('configuration',{})),
           '## Execution progress',table(['Unit','Planned','Completed','Errored','Skipped','Pending'],[[p[k] for k in ('unit','planned','completed','errored','skipped','pending')]]),
           '## Assessment',table(['Population','Assessed','Unassessed'],[[a['population'],a['assessed'] if a['assessed'] is not None else a['missing_reasons'].get('assessed'),a['unassessed'] if a['unassessed'] is not None else a['missing_reasons'].get('unassessed')]]),
           '## Metrics',table(['Metric','Value','Unit','Numerator','Denominator','Population','Notes'],metric_rows(doc['metrics'])),
           '## Coverage']
    for source in doc['coverage']:
        lines += [f"### {md(source['source'])}",table(['Count','Value','Unit','Numerator','Denominator','Population','Notes'],metric_rows(source['counts']))]
    lines += ['Full source provenance, transformations and exclusions are retained in report.json and the original evidence.', '## Breakdowns']
    for group in doc['breakdowns']:
        lines += [f"### {md(group['dimension'])}: {md(group['group'])}",table(['Metric','Value','Unit','Numerator','Denominator','Population','Notes'],metric_rows(group['metrics']))]
    lines += ['## Findings']
    if not doc['findings']:lines += ['No findings recorded. Review unknown assessments and incomplete coverage before drawing conclusions.']
    for f in doc['findings']:
        lines += [f"### {md(f['id'])}: {md(f['title'])}",table(['Field','Value'],[(k, f.get('severity_reason') if k=='severity' and f[k] in (None,'unknown') else f[k]) for k in ('status','severity','observation','impact','recommendation','retest')]),
                  'Evidence references: '+md(json.dumps(f['evidence'],ensure_ascii=False))]
    failure=doc.get('failure_export',{})
    lines += ['## Failed instances', f"{failure.get('instances',0)} instances in failed_instances.csv.",
              table(['Failure type','Instances'],failure.get('by_failure_type',{}).items()),
              failure.get('inclusion','No failure export was supplied for this report.'),failure.get('exclusion',''),
              'The CSV begins with what_went_wrong, expected/observed behavior and failure type; full conversations, returned reasoning and structured evidence follow.']
    lines += ['## Limitations']+[f'- {md(v)}' for v in doc['limitations']]
    lines += ['## Evidence and exports','All evidence references above join to the CSV/JSONL artifacts below. Preserve unknown values; do not add overlapping groups. Exports can contain sensitive content.',
              '- [Common structured report](report.json)']
    from urllib.parse import quote
    lines += [f"- [{md(a['name'])}]({quote(a['path'],safe='/._-')}) — {md(a['media_type'])}" for a in doc['artifacts']]
    return '\n\n'.join(lines)+'\n'


def explain_availability(doc):
    """Explain nulls without inventing measurements or calling inapplicable fields missing."""
    def explain(metrics):
        for m in metrics:
            name=m['name'];reasons=dict(m.get('missing_reasons',{}));notes=[]
            if m['value'] is None:
                if m['denominator']==0:reason='Not calculable: no eligible records in this population (denominator is zero).'
                elif 'cost' in name:reason='Not measured: actual input/output prices or per-attempt billing data were not supplied.'
                elif 'ttft' in name:reason='Not measured: the Loop completion interface does not record first-token timing.'
                elif 'amplification' in name:reason='Not calculable: no usable matched baseline/workload measurements, or the baseline mean is zero; see matched_baseline_pairs and group measurements.'
                elif 'tokens' in name:reason='Not measured: no qualifying attempt supplied the required provider token usage.'
                elif 'latency' in name:reason='Not measured: this group has no recorded qualifying latency measurements.'
                elif 'concurrency' in name or 'in_flight' in name:reason='Not observed: this group has no executed attempts with a recorded concurrency value.'
                else:reason='Not measured: no eligible saved observations for this metric; inspect this group’s execution counts and evidence.'
                reasons.setdefault('value',reason)
            for key in ('numerator','denominator'):
                if m[key] is None:
                    reasons.setdefault(key,('Not applicable: this is a count or measurement, not a fraction.' if m['unit']!='ratio' else
                                  'Not applicable: amplification is a ratio of measured means, not event counts.' if 'amplification' in name else
                                  'Not recorded in the saved aggregate; use the per-instance evaluation evidence for this eligible population.'))
            if 'cost' in name:
                m['unit']='currency ('+str(doc['configuration'].get('pricing',{}).get('currency','unspecified'))+')'
                notes.append('Known measurements only. Missing prices/usage are excluded; a zero subtotal is not proof of zero cost. See cost_unavailable_requests.')
            m['missing_reasons']=reasons;m['notes']=' '.join(notes)
    explain(doc['metrics'])
    for group in doc['breakdowns']:explain(group['metrics'])
    for source in doc['coverage']:explain(source['counts'])
    a=doc['assessment'];a['missing_reasons']={}
    for field in ('assessed','unassessed'):
        if a[field] is None:
            a['missing_reasons'][field]=('Not applicable: LLM10 has no per-call security grading oracle. Confirming vulnerability requires declared server quotas/SLOs and resource or billing telemetry, which this run does not contain.' if doc['benchmark']['id']=='llm10' else
                'Not recorded: no eligible grading counts were supplied by this saved assessment.')
    for f in doc['findings']:
        f['severity_reason']=('Not assigned: LLM10 observations are not confirmed server-policy violations, and no severity rubric is applied.' if doc['benchmark']['id']=='llm10' else
            'Not assigned: the saved judge verdict did not determine a severity; inspect its violations and confidence in the evidence.' if f.get('status')=='judge_assessment' else
            'Not assigned in the original finding; no severity was inferred during reporting.') if f['severity'] in (None,'unknown') else ''
