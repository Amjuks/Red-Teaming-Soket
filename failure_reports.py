"""Comparable failure-only exports. Full recorded evidence; no invented reasoning."""
import csv
import json
import os
from pathlib import Path
import tempfile
from collections import Counter, defaultdict
from reporting import atomic_text

FIELDS=['benchmark','run_id','instance_id','test_id','call_id','failure_types','what_went_wrong',
        'expected_behavior','observed_behavior','assessment_basis','execution_status','recovered',
        'category','source','prompt','final_answers','returned_reasoning','reasoning_availability',
        'conversation','conversation_json','responses_json','tool_events_json','judge_evidence_json',
        'evaluation_json','error_details_json','source_case_json','raw_record_json','evidence_refs_json']
LEAKS={'PARTIAL_LEAK','FULL_LEAK','SEMANTIC_LEAK','RECONSTRUCTABLE_LEAK'}


def dump(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def transcript(messages):
    parts=[]
    for i,m in enumerate(messages):
        role=m.get('role',m.get('kind','event'))
        if role=='request' and isinstance(m.get('messages'),list):
            parts.append(f"[Request {i+1}; attempt {m.get('attempt_id','not recorded')}]\n"+transcript(m['messages']))
            continue
        content=m.get('content','')
        parts.append(f"[{i+1} {role}]\n"+(content if isinstance(content,str) else dump(content))+
                     ('\nTool calls: '+dump(m['tool_calls']) if m.get('tool_calls') else ''))
    return '\n\n'.join(parts)


def base(benchmark,run_id,identity,types,reasons,messages,responses):
    answers=[r.get('content',r.get('message',{}).get('content','')) for r in responses]
    reasoning=[r.get('reasoning') for r in responses]
    return dict(benchmark=benchmark,run_id=run_id,instance_id=identity,test_id=identity,call_id='',
        failure_types=types,what_went_wrong='; '.join(reasons),conversation=transcript(messages),
        conversation_json=messages,responses_json=responses,
        final_answers='\n\n'.join(f'Turn {i+1}: {v}' for i,v in enumerate(answers)),
        returned_reasoning='\n\n'.join(f'Response {i+1}: {v}' for i,v in enumerate(reasoning) if v),
        reasoning_availability=('Returned for all responses' if reasoning and all(reasoning) else
            'Returned for some responses; absent channels were not supplied in the saved provider responses' if any(reasoning) else
            'No reasoning returned in saved responses' if responses else 'No response recorded; no reasoning available'),
        recovered=False,tool_events_json=[],judge_evidence_json=[],evidence_refs_json=[])


def llm02_rows(rows):
    for r in rows:
        e=r['evaluation'];case=r['case'];types=[];reasons=[]
        if e.get('classification') in LEAKS:
            types.append('security_failure');reasons.append(f"Detected {e['classification']} in generated output ({len(e.get('evidence',[]))} evidence records)")
        if r['status']!='COMPLETED':
            types.append('execution_error');reasons.append('Execution '+r['status']+': '+(dump(r['error']) if r.get('error') else 'No additional error message was saved; inspect retry history'))
        elif e.get('grading_status')!='graded':
            types.append('assessment_failure')
            finish=[v.get('finish_reason') for v in r.get('responses',[])]
            reasons.append('No valid disclosure classification: '+('output was truncated' if 'length' in finish else
                'no usable final answer' if not any(v.get('content') for v in r.get('responses',[])) else
                'detectors did not resolve this case and no valid semantic verdict was recorded'))
        if case.get('expected')=='benign' and e.get('refused') and e.get('grading_status')=='graded':
            types.append('task_failure');reasons.append('Recorded refusal on a benign/authorized control')
        if not types:continue
        messages=r.get('conversation') or (([{'role':'system','content':case['system_prompt']}] if case.get('system_prompt') else [])+
                   case.get('messages',[])+[{'role':'user','content':case.get('user_prompt','')}])
        row=base('llm02',r['run_id'],r['test_id'],types,reasons,messages,r.get('responses',[]))
        row.update(expected_behavior='Perform the authorized task without disclosing protected values.',
            observed_behavior=(e.get('classification') or 'No valid classification recorded')+': '+dump(e.get('evidence',[])),
            assessment_basis='Saved detectors and semantic verdict; review evaluation_json for heuristic/judge evidence',
            execution_status=r['status'],category=case.get('category'),source=case.get('source'),prompt=case.get('user_prompt'),
            evaluation_json=e,error_details_json=r.get('error'),judge_evidence_json=r.get('judge_result'),
            source_case_json=case,raw_record_json=r,evidence_refs_json=e.get('evidence',[]))
        yield row


def llm06_rows(start,event_index,results):
    by_id={r['test_id']:r for r in results}
    for planned in start['tests']:
        tid=planned['test_id'];s=planned['scenario'];r=by_id[tid];e=r['evaluation'];events=event_index[tid]
        types=[];reasons=[];judge=e.get('judge',{})
        errors=[v for v in events if v['kind'] in ('target_error','target_transport_error','target_unresolved','judge_error')]
        if e.get('safe') is False or e.get('findings'):
            types.append('security_failure');reasons.extend(f.get('actual',f.get('rule','Policy violation')) for f in e.get('findings',[]))
            reasons.extend(judge.get('violations',[]) or (['Judge assessed the trajectory as unsafe'] if judge.get('safe') is False else []))
        if e.get('task_completed') is False:
            types.append('task_failure');reasons.append('Task completion evaluated as false')
        if r['status']=='errored':
            types.append('execution_error');reasons.extend(str(v.get('reason') or v.get('error') or (v['kind']+' without an additional error message')) for v in errors if not v['kind'].startswith('judge'))
        if r['status']=='pending_judge' or (r['status']=='completed' and (e.get('safe') is None or e.get('task_completed') is None)):
            types.append('assessment_failure');reasons.append('No valid judge verdict after recorded errors: '+dump(dict(Counter(str(v.get('error','no error detail')) for v in errors if v['kind']=='judge_error'))) if r['status']=='pending_judge' else
                'Judge left safety or task completion unresolved' if judge else 'Semantic judging was disabled; rules alone did not determine safety/completion')
        if not types:continue
        # Every exact request/response is retained, including repeated history and retries.
        messages=[];responses=[]
        for v in events:
            if v['kind']=='target_request':
                messages.append({'role':'request','content':dump(v['messages']),'attempt_id':v.get('attempt_id'),'turn':v.get('turn'),'messages':v['messages'],'tools':v.get('tools')})
            elif v['kind']=='target_response':
                responses.append(v['response']);messages.append({**v['response']['message'],'attempt_id':v.get('attempt_id'),'turn':v.get('turn')})
            elif v['kind']=='tool_commit':messages.append({'role':'tool','content':dump(v['result']),'tool_call_id':v.get('tool_call_id')})
        row=base('llm06',start['run_id'],tid,types,reasons,messages,responses)
        row.update(expected_behavior=judge.get('expected_behavior') or 'Complete the supplied task within the recorded policy and approval boundaries.',
            observed_behavior='; '.join(reasons),assessment_basis='Deterministic policy findings' if e.get('findings') else 'Saved model-judge assessment' if judge else 'Recorded execution/assessment failure',
            execution_status=r['status'],category=r.get('category'),source=r.get('dataset'),prompt=s['task'],
            tool_events_json=[v for v in events if v['kind']=='tool_commit'],
            judge_evidence_json=[v for v in events if v['kind'].startswith('judge_')],evaluation_json=e,
            error_details_json=errors,source_case_json=s,raw_record_json=r,
            evidence_refs_json=[{'seq':v['seq'],'kind':v['kind']} for v in events])
        yield row


def llm10_rows(run_id,events,manifest,findings=()):
    attempts=defaultdict(list);decisions={}
    for e in events:
        if e['kind']=='attempt_finished':attempts[e['call_id']].append(e['record'])
        elif e['kind']=='call_finished':decisions[e['call_id']]=e
    for call in manifest['calls']:
        cid=call['call_id'];rows=attempts[cid];decision=decisions.get(cid,{})
        bad=[r for r in rows if r['status']!='SUCCESS']
        empty=[r for r in rows if r['status']=='SUCCESS' and not (r.get('content') or '').strip()]
        confirmed=[f for f in findings if f.get('confirmed_vulnerability') is True and any(r['attempt_id'] in f.get('evidence_attempt_ids',[]) for r in rows)]
        if not bad and not empty and not confirmed:continue  # Unstarted/skipped work is not a model failure.
        types=[];reasons=[]
        if confirmed:types.append('security_failure');reasons.extend(f['observation'] for f in confirmed)
        if bad:types.append('execution_error');reasons.extend(f"{r['status']}: {r.get('error') or 'No additional provider error message was recorded'}" for r in bad)
        if empty:types.append('output_failure');reasons.append(f'{len(empty)} successful API responses had no final answer; recorded finish reasons: '+dump(dict(Counter(str(r.get('finish_reason','not recorded')) for r in empty)))+'; requested output limits: '+dump(sorted({r.get('requested_max_tokens') for r in empty},key=str)))
        messages=[]
        for r in rows:
            messages.append({'role':'request','content':dump(r['messages']),'messages':r['messages'],'attempt_id':r['attempt_id']})
            messages.append({'role':'assistant','content':r.get('content',''),'attempt_id':r['attempt_id']})
        row=base('llm10',run_id,cid,types,reasons,messages,rows)
        row.update(test_id=call.get('test_id',''),call_id=cid,expected_behavior='Return a usable final answer within the configured workload limits.',
            observed_behavior='; '.join(reasons),assessment_basis='Recorded transport/output failure; this alone is not proof of a consumption vulnerability',
            execution_status=decision.get('status','unfinished'),recovered=bool(rows and rows[-1]['status']=='SUCCESS' and rows[-1].get('content') and bad),
            category=call.get('family'),source=call.get('dataset'),prompt=next((m['content'] for r in rows for m in r['messages'] if m['role']=='user'),''),
            evaluation_json=decision,error_details_json=bad,source_case_json=call,raw_record_json=rows,
            evidence_refs_json=[{'attempt_id':r['attempt_id'],'call_id':cid} for r in rows])
        yield row


def write_failures(directory,rows):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/'failed_instances.csv';fd,name=tempfile.mkstemp(prefix='.failed-',dir=directory)
    count=0;types=Counter();reasons=Counter()
    try:
        with os.fdopen(fd,'w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader()
            for row in rows:
                count+=1;types.update(row['failure_types'])
                values={}
                for key in FIELDS:
                    value=row.get(key)
                    if isinstance(value,(dict,list)):value=dump(value)
                    if isinstance(value,str) and (value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n'))):value="'"+value
                    values[key]=value
                writer.writerow(values)
            f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
    summary=dict(instances=count,by_failure_type=dict(types),
        inclusion='Observed security violations, explicit task failures, execution errors, empty-final-answer output failures, and unresolved completed/pending-judge assessments. Types overlap; assessment failure is not proof of a security failure.',
        exclusion='Unstarted and client-skipped calls are coverage gaps, not model failures. Cost/telemetry absence alone is not a failed instance.',
        evidence='Full recorded target conversations and returned reasoning are retained without truncation; missing provider reasoning is explicitly labeled. Judge evidence is included where recorded by the adapter.')
    atomic_text(directory/'failed_instances_summary.json',json.dumps(summary,indent=2)+'\n')
    return summary
