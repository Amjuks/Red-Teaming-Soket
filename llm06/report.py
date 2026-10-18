"""Offline report projections; explicit denominators and Markdown assessments."""
import csv
import json
import sys
from pathlib import Path

# Support the existing standalone `python run.py` entry point.
if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.append(str(Path(__file__).resolve().parents[1]))
from reporting import publish
from collections import Counter, defaultdict
from common import ROOT, atomic_json, canonical, local_path
from evaluator import evaluate

def rate(n,d,eligibility):return {'numerator':n,'denominator':d,'rate':n/d if d else None,'eligibility':eligibility}

def build(journal,report_dir):
    events=journal.snapshot() if hasattr(journal,'snapshot') else list(journal.events); start=next(e for e in events if e['kind']=='run_start'); run_id=start['run_id']
    event_index=defaultdict(list)
    for event in events:
        if event.get('test_id'):event_index[event['test_id']].append(event)
    rows=[]; tools=[]; conversations=[]; findings=[]; results=[]
    for planned in start['tests']:
        tid=planned['test_id'];s=planned['scenario'];ev=event_index[tid]
        end=next((e for e in reversed(ev) if e['kind']=='test_result'),None)
        status=end['status'] if end else ('pending_judge' if any(e['kind']=='target_done' for e in ev) else 'planned' if not ev else 'unfinished')
        evaluation=end['evaluation'] if end else evaluate(s,ev)
        base={'run_id':run_id,'test_id':tid,'scenario_id':s['scenario_id'],'variant_id':s['variant_id'],
              'dataset':s['source']['dataset'],'source_revision':s['source'].get('revision'), 'sample_id':s['source']['sample_id']}
        row={**base,'status':status,'safe':evaluation['safe'],'task_completed':evaluation['task_completed'],
             'finding_count':len(evaluation['findings']),'category':s.get('category',[]),'domains':s.get('domains',['fixture']),'task':s['task'],'coverage_mode':s.get('coverage_mode','explicit_json_adapter'),
             'source_split':s['source']['sample_id'].split(':')[0],
             'source_environments':s.get('source_environments',[])}
        rows.append(row);results.append({**row,'evaluation':evaluation})
        for f in evaluation['findings']:findings.append({**base,**f})
        for e in ev:
            if e['kind']=='tool_commit':
                tools.append({**base,'evidence_seq':e['seq'],'turn':e['turn'],'tool_call_id':e['tool_call_id'],
                              **{k:v for k,v in e['result'].items() if k!='snapshot'}})
            if e['kind'] in ('target_request','target_response','judge_request','judge_response','tool_commit'):
                conversations.append({**base,'evidence_seq':e['seq'],'kind':e['kind'],'turn':e.get('turn'),
                                      'attempt_id':e.get('attempt_id'),'tool_call_id':e.get('tool_call_id'),'evidence':e})
    n=len(rows);completed=[r for r in rows if r['status']=='completed']
    eligible=[r for r in completed if r['safe'] is not None and r['task_completed'] is not None]
    success=sum(r['safe'] is True and r['task_completed'] is True for r in completed)
    known_safe=[r for r in completed if r['safe'] is not None]
    known_task=[r for r in completed if r['task_completed'] is not None]
    categories=Counter(f['risk_type'] for f in findings)
    metrics={'planned':n,'status_counts':dict(Counter(r['status'] for r in rows)),
        'unassessed':sum(r['safe'] is None or r['task_completed'] is None for r in rows),
        'safe_task_completion_all_planned':rate(success,n,'all planned scenario/variant pairs'),
        'safe_task_completion_evaluable':rate(success,len(eligible),'completed with known safety and completion'),
        'task_completion':rate(sum(r['task_completed'] is True for r in known_task),len(known_task),'completed with known completion'),
        'safe':rate(sum(r['safe'] is True for r in known_safe),len(known_safe),'completed with assessed safety'),
        'risky_all_planned':rate(sum(r['safe'] is False for r in rows),n,'all planned; includes established violations in errored trajectories'),
        'unsafe_tool_attempts':rate(sum(bool(t['violations']) for t in tools),len(tools),'all recorded tool attempts'),
        'blocked_tool_attempts':rate(sum(t['status']=='blocked' for t in tools),len(tools),'all recorded tool attempts'),
        'simulated_executed':sum(t['status']=='simulated_executed' for t in tools),
        'severity':dict(Counter(f['severity'] for f in findings)),
        'risk_categories':{cat:rate(len({f['test_id'] for f in findings if f['risk_type']==cat}),n,'all planned; categories overlap') for cat in categories},
        'usage_cost':'unknown; consult raw provider evidence. Loop may normalize missing usage/cost to zero.',
        'unassessed_semantic_categories':['unnecessary_actions','disclosure','unsafe_chains','intent_drift','indirect_injection'] if start['config']['judge'] is None else [],
        'by_variant':{v:{'planned':sum(r['variant_id']==v for r in rows),'risky':sum(r['variant_id']==v and r['safe'] is False for r in rows)} for v in {r['variant_id'] for r in rows}}}
    def breakdown(field):
        labels=sorted({label for r in rows for label in (r[field] if isinstance(r[field],list) else [r[field]])})
        output={}
        for label in labels:
            group=[r for r in rows if label in (r[field] if isinstance(r[field],list) else [r[field]])]
            output[label]={'planned':len(group),'completed':sum(r['status']=='completed' for r in group),
                'errored':sum(r['status']=='errored' for r in group),'unassessed':sum(r['safe'] is None or r['task_completed'] is None for r in group),
                'risky':rate(sum(r['safe'] is False for r in group),len(group),'planned in group; overlapping groups are not additive')}
        return output
    metrics['by_domain']=breakdown('domains');metrics['by_category']=breakdown('category')
    metrics['by_coverage_mode']=breakdown('coverage_mode');metrics['by_source_split']=breakdown('source_split')
    metrics['by_dataset']=breakdown('dataset');metrics['by_variant']=breakdown('variant_id')
    metrics['by_tool']={name:{'attempts':len(group),'blocked':sum(t['status']=='blocked' for t in group),
        'violating_attempts':rate(sum(bool(t['violations']) for t in group),len(group),'attempts for this tool'),
        'affected_tests':len({t['test_id'] for t in group})} for name in sorted({t['name'] for t in tools})
        for group in [[t for t in tools if t['name']==name]]}
    metrics['pairs']=[]
    pair_index=defaultdict(dict)
    tool_counts={t['test_id']:len(t['scenario']['tools']) for t in start['tests']}
    for row in rows:pair_index[row['scenario_id']][row['variant_id']]=row
    for sid,pair in sorted(pair_index.items()):
        if 'least' in pair and 'broad' in pair:
            metrics['pairs'].append({'scenario_id':sid,'sample_id':pair['least']['sample_id'],
                'least_status':pair['least']['status'],'broad_status':pair['broad']['status'],
                'least_findings':pair['least']['finding_count'],'broad_findings':pair['broad']['finding_count'],
                'least_safe':pair['least']['safe'],'broad_safe':pair['broad']['safe'],
                'added_tools':tool_counts[pair['broad']['test_id']]-tool_counts[pair['least']['test_id']]})
    metrics['execution_errors']=dict(Counter(e.get('reason','unspecified') for e in events if e['kind']=='target_error'))
    metrics['finish_reasons']=dict(Counter(str(e['response'].get('finish_reason')) for e in events if e['kind']=='target_response'))
    metrics['unique_scenarios']=len({r['scenario_id'] for r in rows})
    metrics['source_data_unavailable_attempts']=sum(t.get('reason')=='source_data_unavailable' for t in tools)
    directory=journal.directory
    for name,records in [('scenarios',rows),('tool_calls',tools),('conversations',conversations),('findings',findings)]:
        keys=list(dict.fromkeys(k for record in records for k in record)) or ['run_id','test_id']
        with (directory/(name+'.csv')).open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader()
            for row in records:
                formatted={k:canonical(v) if isinstance(v,(dict,list)) else v for k,v in row.items()}
                # Prevent spreadsheet formula interpretation of untrusted dataset/model strings.
                writer.writerow({k:"'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v for k,v in formatted.items()})
    (directory/'results.jsonl').write_text(''.join(canonical(r)+'\n' for r in results))
    atomic_json(directory/'metrics.json',metrics)
    target=local_path(report_dir)/run_id;target.mkdir(parents=True,exist_ok=True)
    semantic_findings=[]
    for result in results:
        verdict=result['evaluation'].get('judge')
        if not verdict or not (verdict.get('safe') is False or verdict.get('violations')):continue
        tid=result['test_id']
        evidence=next((e['seq'] for e in reversed(event_index[tid]) if e['kind']=='judge_verdict'),None)
        semantic_findings.append({'finding_id':tid+'-judge','test_id':tid,'evidence_seq':evidence,
            'rule':'semantic_judge','severity':verdict.get('severity','unknown'),
            'expected':verdict.get('expected_behavior'),'actual':'; '.join(verdict.get('violations',[])) or 'Judge assessed safety as false.',
            'why_risky':'Model-judged simulated risk; review original verdict and trajectory.',
            'recommendation':verdict.get('recommendation','Review evidence.'),
            'retest':'Repeat the task and review with an independent evaluator.', 'judge':verdict})
    from failure_reports import write_failures, llm06_rows
    failure_summary=write_failures(directory, llm06_rows(start,event_index,results))
    from diagnostics import audit
    diagnostics=audit(events)
    atomic_json(directory/'pipeline_diagnostics.json',diagnostics)
    failure_summary['pipeline_diagnostics']=diagnostics
    atomic_json(directory/'failed_instances_summary.json',failure_summary)
    settings=next((e for e in reversed(events) if e['kind']=='execution_settings'),{})
    report_config={**start['config'],'concurrency':settings.get('concurrency',start['config'].get('concurrency',1))}
    publish('llm06', run_id, start['config']['target'], metrics, start.get('coverage', {}), directory, target, findings+semantic_findings, configuration=report_config)
    if start.get('coverage', {}).get('dataset')=='aradhye/agent-safety-bench':
        atomic_json(target.parent/'latest.json', {'run_id':run_id, 'report':str(target/'report.md')})
    if target.parent==ROOT/'reports' and start.get('coverage',{}).get('dataset')=='aradhye/agent-safety-bench':
        from run_names import register
        register(ROOT.parent/'runs',target/'report.md',directory)
    return metrics, target/'report.md'
