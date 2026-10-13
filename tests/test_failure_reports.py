import csv
import json
import tempfile
from pathlib import Path
from failure_reports import llm02_rows,llm06_rows,llm10_rows,write_failures,FIELDS
from reporting import publish


def test_disclosure_and_assessment_failures_preserve_reasoning_and_skip_passes():
    rows=[]
    for id,classification,grading in [('leak','FULL_LEAK','graded'),('pass','NO_LEAK','graded'),('ungraded',None,'ungraded')]:
        rows.append(dict(run_id='run',test_id=id,status='COMPLETED',case={'expected':'must_not_disclose','category':'credential','protected_values':['secret'],'user_prompt':'  =formula'},
            responses=[{'content':'answer','reasoning':'full reasoning\nsecond line','raw':{'wire':'unchanged'}}],conversation=[{'role':'user','content':'  =formula'},{'role':'assistant','content':'answer'}],
            evaluation={'classification':classification,'grading_status':grading,'evidence':[{'matched':'secret'}] if classification=='FULL_LEAK' else []}))
    with tempfile.TemporaryDirectory() as tmp:
        summary=write_failures(tmp,llm02_rows(rows));assert summary['instances']==2
        with (Path(tmp)/'failed_instances.csv').open(encoding='utf-8-sig',newline='') as f:data=list(csv.DictReader(f))
        assert list(data[0])==FIELDS
        assert {r['test_id'] for r in data}=={'leak','ungraded'}
        assert 'full reasoning\nsecond line' in data[0]['returned_reasoning']
        assert json.loads(data[0]['raw_record_json'])==rows[0]
        assert data[0]['prompt'].startswith("'")
        assert (Path(tmp)/'failed_instances.csv').stat().st_mode & 0o777==0o600


def test_llm06_errors_pending_judge_and_tools_are_complete():
    start={'run_id':'r','tests':[{'test_id':'t','scenario':{'task':'do task'}}]}
    events={'t':[{'kind':'target_request','seq':1,'messages':[{'role':'user','content':'task'}]},
                 {'kind':'target_response','seq':2,'response':{'message':{'role':'assistant','content':'answer'},'reasoning':'thinking'}},
                 {'kind':'tool_commit','seq':3,'result':{'status':'blocked'}},
                 {'kind':'judge_error','seq':4,'error':'schema_validation'}]}
    results=[{'test_id':'t','status':'pending_judge','evaluation':{'safe':None,'task_completed':None,'findings':[]}}]
    row=list(llm06_rows(start,events,results))[0]
    assert row['failure_types']==['assessment_failure']
    assert row['returned_reasoning']=='Response 1: thinking'
    assert row['tool_events_json']==[events['t'][2]]
    assert row['judge_evidence_json']==[events['t'][3]]
    assert 'schema_validation' in json.dumps(row['error_details_json'])


def test_llm10_retries_empty_answers_and_skips_have_distinct_meanings():
    calls=[{'call_id':id,'test_id':id} for id in ('retry','empty','skipped','pass')]
    events=[]
    for cid,status,content in [('retry','ERROR',''),('retry','SUCCESS','answer'),('empty','SUCCESS',''),('pass','SUCCESS','answer')]:
        record={'call_id':cid,'attempt_id':str(len(events)),'status':status,'content':content,'reasoning':'retained','messages':[{'role':'user','content':'question'}],'error':'timeout' if status=='ERROR' else None}
        events.append({'kind':'attempt_finished','call_id':cid,'record':record})
    events.append({'kind':'call_finished','call_id':'skipped','status':'SKIPPED'})
    rows=list(llm10_rows('r',events,{'calls':calls}))
    assert [r['call_id'] for r in rows]==['retry','empty']
    assert rows[0]['recovered'] is True
    assert len(rows[0]['responses_json'])==2
    assert rows[1]['failure_types']==['output_failure']


def test_nulls_have_specific_reasons_and_nonfractions_are_not_missing():
    data=dict(planned_calls=0,successful_calls=0,terminal_calls=0,skipped_calls=0,unfinished_calls=0,
              overall={'requests':0,'latency_mean':None,'total_tokens_mean':None},assessment={'findings':[], 'limitations':[]})
    with tempfile.TemporaryDirectory() as tmp:
        text=publish('llm10','r',{},data,{},tmp,tmp)
        doc=json.loads((Path(tmp)/'report.json').read_text())
        metrics={m['name']:m for m in doc['metrics']}
        assert 'latency' in metrics['latency_mean']['missing_reasons']['value']
        assert 'provider token usage' in metrics['total_tokens_mean']['missing_reasons']['value']
        assert metrics['requests']['missing_reasons']['numerator'].startswith('Not applicable')
        assert 'server quotas' in doc['assessment']['missing_reasons']['assessed']
        assert '| unknown |' not in text
