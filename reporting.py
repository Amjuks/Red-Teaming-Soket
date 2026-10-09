"""Versioned common report envelope and overview; native evidence stays intact."""
import html
import json
import os
from pathlib import Path
import tempfile

VERSION = '1.1.0'
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


def publish(benchmark, run_id, model, data, coverage, directory, report_directory, findings=None):
    """Adapt native aggregates without regrading results or flattening denominators."""
    directory, report_directory = Path(directory), Path(report_directory)
    if benchmark == 'llm02':
        overall = data['overall']
        progress = dict(unit='test', planned=data['total_tests'], completed=overall['completed'],
                        errored=overall['errors'], skipped=0, pending=data['unexecuted'])
        normalized = [finding(f['id'], f['description'], 'observed_disclosure', f['severity'].lower(),
                              [{'test_id': t} for t in f['test_ids']], f) for f in data['findings']]
        limitations = ['HTML overview omits raw protected values and responses; evidence exports are private.',
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
        normalized = [finding(f.get('finding_id', f'{run_id}:{i}'), f['rule'], 'observed_policy_violation', f['severity'].lower(),
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
    artifacts = [dict(name=name, path=os.path.relpath(directory/name, report_directory),
                      media_type='text/csv' if name.endswith('.csv') else 'application/x-ndjson' if name.endswith('.jsonl') else 'application/json',
                      sensitivity='private') for name in names if (directory/name).is_file()]
    doc = envelope(benchmark, run_id, model, progress, coverage, data, normalized, limitations, artifacts)
    atomic_text(report_directory/'report.json', json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    return overview(doc)


def overview(doc):
    """Same accessible layout for each benchmark; raw findings stay in native details."""
    esc = lambda x: html.escape(str(x), quote=True)
    p = doc['progress']
    cards = ''.join(f'<div><strong>{p[k]}</strong><span>{k.title()}</span></div>'
                    for k in ('planned', 'completed', 'errored', 'skipped', 'pending'))
    downloads = ''.join(f'<li><a href="{esc(a["path"])}">{esc(a["name"])}</a> (private)</li>' for a in doc['artifacts'])
    return '''<style>.common-report{font:16px/1.6 system-ui;background:#f5f7fb;color:#18283b;padding:24px;margin:0 auto;max-width:1180px}.common-report .common-cards{display:flex;flex-wrap:wrap;gap:16px}.common-cards div{background:white;border:1px solid #d9e2ee;border-radius:8px;padding:16px;min-width:100px}.common-cards strong{display:block;font-size:28px}.common-report pre{white-space:pre-wrap;overflow-wrap:anywhere}.common-report a{color:#126779}</style>''' + f'''<section class="common-report" aria-label="Common benchmark report">
<h1>{esc(doc['benchmark']['id'].upper())} · {esc(doc['benchmark']['title'])}</h1>
<p><strong>{esc(doc['run']['name'])}</strong></p><p>Run ID {esc(doc['run']['id'])} · Report schema {esc(doc['schema_version'])} · {esc(doc['run']['execution_state'])}</p>
<nav><a href="#common-progress">Progress</a> · <a href="#common-coverage">Coverage</a> · <a href="#common-findings">Findings</a> · <a href="#common-limitations">Limitations</a> · <a href="#common-downloads">Downloads</a> · <a href="#benchmark-details">Benchmark details</a></nav>
<h2>Run configuration</h2><pre>{esc(json.dumps(doc['run']['model'], indent=2))}</pre>
<h2 id="common-progress">Execution progress</h2><p>Unit: {esc(p['unit'])}. Execution completion does not establish safety or task success. Partial describes unfinished work, not process liveness.</p><div class="common-cards">{cards}</div>
<h2 id="common-coverage">Coverage</h2><p>Source coverage and category breakdowns appear in the benchmark details and report.json. Overlapping groups must not be added together.</p>
<h2 id="common-findings">Findings</h2><p>{len(doc['findings'])} benchmark-specific findings or observations. See the detailed evidence and interpretation below; finding counts and severity are not comparable across benchmarks.</p>
<h2 id="common-limitations">Limitations</h2><ul>{''.join('<li>'+esc(v)+'</li>' for v in doc['limitations'])}</ul>
<h2 id="common-downloads">Downloads</h2><p><a href="report.json">Common report.json</a> includes complete native metrics, coverage, normalized findings with evidence IDs, and artifact paths. Detailed exports can contain sensitive prompts and responses.</p><ul>{downloads}</ul>
<h2 id="benchmark-details">Benchmark details</h2></section>'''
