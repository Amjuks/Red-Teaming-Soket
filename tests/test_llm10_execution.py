import asyncio
import csv
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from llm10.config import load_config
from llm10.datasets import normalize
from llm10.runner import execute, Executor, usage
from llm10.storage import Journal
from llm10.tests import build_manifest
from llm10.report import write_reports
from llm10 import client

ROOT=Path(__file__).resolve().parents[1]


def fixture(tmp_path):
    c=load_config(ROOT/'llm10/config.mock.yaml')
    c['datasets'].update(alpaca=3,instruct_v3=0)
    c['tests']={k:3 if k=='baseline' else 1 for k in c['tests']}
    c['execution'].update(retry_backoff_seconds=.01,max_backoff_seconds=.02)
    c['safety'].update(cooldown_seconds=.001,max_tokens=1000000,max_requests=100)
    c['paths']={k:str(tmp_path/k) for k in ('data','results','reports')}
    samples=[normalize('alpaca',{'instruction':f'Question {i}','input':'context'},i) for i in range(3)]
    return c,build_manifest(c,samples)


def success(content='answer',reasoning=''):
    return {'ok':True,'response':{'content':content,'reasoning':reasoning,'usage':{'input':10,'output':4},'status_code':200,'finish_reason':'stop'}}


def test_all_families_replay_and_exact_csv(tmp_path):
    cfg,m=fixture(tmp_path); sent=[]
    async def transport(model,messages,*args):
        sent.append(messages)
        return success('=formula\nहिन्दी, "quoted"','Returned reasoning')
    assert asyncio.run(execute(cfg,m,{}, {'transport':'test'},transport))==0
    count=len(sent)
    assert count==len(m['calls'])
    latest=json.loads((Path(cfg['paths']['results'])/'latest.json').read_text())
    out=Path(latest['directory']); before=(out/'events.jsonl').read_bytes()
    assert (Path(cfg['paths']['results'])/'latest').resolve()==out
    assert (Path(cfg['paths']['reports'])/'latest/report.html').is_file()
    assert asyncio.run(execute(cfg,m,{}, {'transport':'test'},transport))==0
    assert len(sent)==count and (out/'events.jsonl').read_bytes()==before
    with (out/'requests.csv').open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    assert len(rows)==count
    assert json.loads(rows[0]['messages'])==sent[0]
    assert json.loads(rows[0]['raw_response'])['response']['content']=='=formula\nहिन्दी, "quoted"'
    assert rows[0]['content'].startswith("'=formula")
    assert any(len(msg)>1 for msg in sent)
    assert all(p.stat().st_mode & 0o777==0o600 for p in out.glob('*.csv'))


def test_retry_persisted_and_failure_branches(tmp_path):
    cfg,m=fixture(tmp_path); attempts=[]
    cfg['safety']['consecutive_rate_limits']=2
    async def transport(*args):
        attempts.append(args)
        return {'ok':False,'error':'HTTP 429','status_code':429,'retryable':True,'retry_after':'0'}
    asyncio.run(execute(cfg,m,{}, {'transport':'test'},transport))
    n=len(attempts)
    asyncio.run(execute(cfg,m,{}, {'transport':'test'},transport))
    assert len(attempts)==n
    latest=json.loads((Path(cfg['paths']['results'])/'latest.json').read_text())
    stats=json.loads((Path(latest['directory'])/'metrics.json').read_text())
    assert stats['overall']['http_429s']==n
    assert stats['branch_stops'] and stats['skipped_calls']


def test_concurrent_budget_reservations_and_unknown_usage(tmp_path):
    cfg,m=fixture(tmp_path)
    # Four independent calls in a two-worker group; only one budget slot available.
    m['calls']=[{**m['calls'][i], 'family':'concurrency','level':2,'concurrency':2} for i in range(3)]
    cfg['safety']['max_requests']=1
    seen=[]
    async def transport(*args):
        seen.append(1); await asyncio.sleep(.01)
        return {'ok':True,'response':{'content':'done','reasoning':'','status_code':200,'usage':{'input':0,'output':0}}}
    asyncio.run(execute(cfg,m,{}, {'transport':'test'},transport))
    assert len(seen)==1
    assert usage({'usage':{'input':0,'output':0}})==(None,None,None)


def test_crash_between_attempt_and_call_commit_does_not_resend(tmp_path):
    cfg,m=fixture(tmp_path);call=m['calls'][0]
    async def exercise():
        with Journal(tmp_path/'run') as j:
            start=j.append('attempt_started',attempt_id='a',call_id=call['call_id'],reserved_tokens=100,reserved_cost=None,
                           record={'test_family':'baseline','call_id':call['call_id']})
            j.append('attempt_finished',attempt_id='a',call_id=call['call_id'],record={'test_family':'baseline','status':'SUCCESS','latency':1,'content':'saved'})
            async def never(*a): pytest.fail('durable response repeated')
            runner=Executor(cfg,m,j,'test',never)
            await runner.run_call(call)
            assert runner.done[call['call_id']]['record']['content']=='saved'
    asyncio.run(exercise())


@pytest.mark.parametrize('sig',[signal.SIGINT,signal.SIGKILL])
def test_real_process_interrupt_resume(tmp_path,sig):
    cfg,m=fixture(tmp_path)
    cfg['safety']['cooldown_seconds']=.001
    setup=tmp_path/'setup.json';setup.write_text(json.dumps([cfg,m]))
    code='''import asyncio,json,sys
from pathlib import Path
from llm10.runner import execute
from llm10.client import complete
cfg,m=json.loads(Path(sys.argv[1]).read_text())
async def slow(*args):
    await asyncio.sleep(.15)
    return await complete(*args)
sys.exit(asyncio.run(execute(cfg,m,{}, {'transport':'interrupt-test'},slow)))
'''
    args=[sys.executable,'-c',code,str(setup)]
    p=subprocess.Popen(args,cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        deadline=time.monotonic()+15
        journal=None
        while time.monotonic()<deadline:
            journals=list((tmp_path/'results').glob('*/events.jsonl'))
            if journals and '"kind": "call_finished"' in journals[0].read_text():journal=journals[0];break
            time.sleep(.01)
        assert journal is not None
        os.kill(p.pid,sig);p.wait(timeout=10)
        events=[json.loads(x) for x in journal.read_text().splitlines()]
        before={e['call_id'] for e in events if e['kind']=='call_finished'}
        start_counts={k:sum(e['kind']=='attempt_started' and e['call_id']==k for e in events) for k in before}
        result=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,timeout=15)
        assert result.returncode in (0,2),result.stderr
        after=[json.loads(x) for x in journal.read_text().splitlines()]
        assert all(sum(e['kind']=='attempt_started' and e['call_id']==k for e in after)==v for k,v in start_counts.items())
        assert len({e['call_id'] for e in after if e['kind']=='call_finished'})==len(m['calls'])
    finally:
        if p.poll() is None:p.kill();p.wait()


def test_cost_cap_before_dispatch(tmp_path):
    cfg,m=fixture(tmp_path)
    cfg['pricing'].update(input_per_million=10,output_per_million=10)
    cfg['safety']['max_cost']=.000001
    async def never(*args):pytest.fail('cost reservation bypassed')
    assert asyncio.run(execute(cfg,m,{}, {'transport':'test'},never))==2


def test_token_cap_before_dispatch(tmp_path):
    cfg,m=fixture(tmp_path);cfg['safety']['max_tokens']=1
    async def never(*args):pytest.fail('token reservation bypassed')
    assert asyncio.run(execute(cfg,m,{}, {'transport':'test'},never))==2


def test_503_recovers_and_both_attempts_recorded(tmp_path):
    cfg,m=fixture(tmp_path);m['calls']=m['calls'][:1]; seen=[]
    async def transport(*args):
        seen.append(1)
        return {'ok':False,'error':'unavailable','status_code':503,'retryable':True} if len(seen)==1 else success()
    assert asyncio.run(execute(cfg,m,{}, {'transport':'test'},transport))==0
    assert len(seen)==2
    latest=json.loads((Path(cfg['paths']['results'])/'latest.json').read_text())
    metrics=json.loads((Path(latest['directory'])/'metrics.json').read_text())
    assert metrics['overall']['requests']==2 and metrics['overall']['errors']==1


def test_latency_circuit_and_replay(tmp_path):
    cfg,m=fixture(tmp_path)
    cfg['safety'].update(latency_min_seconds=.01,latency_multiplier=2)
    with Journal(tmp_path/'run') as j:
        j.append('attempt_finished',attempt_id='baseline',call_id='base',record={'test_family':'baseline','status':'SUCCESS','latency':.005})
        j.append('attempt_finished',attempt_id='stress',call_id='stress',record={'test_family':'input_growth','status':'SUCCESS','latency':.05})
        # Simulate crash before branch_stopped could be persisted.
        runner=Executor(cfg,m,j,'test')
        assert runner.branches['input_growth']=='severe_latency_degradation'
        assert any(e['kind']=='branch_stopped' for e in j.events)


def test_permanent_error_and_timeout_metrics(tmp_path):
    cfg,m=fixture(tmp_path);m['calls']=m['calls'][:2];seen=[]
    async def transport(*args):
        seen.append(1)
        return {'ok':False,'status_code':401,'error':'unauthorized','retryable':False}
    asyncio.run(execute(cfg,m,{}, {'transport':'test'},transport))
    assert len(seen)==2


def test_missing_usage_no_output_limit_claim(tmp_path):
    from llm10.metrics import metrics
    cfg,m=fixture(tmp_path)
    data=metrics([],m)
    assert data['groups']
    assert all(r['input_limit_status']=='TEST INCONCLUSIVE' for r in data['groups'])
    assert data['overall']['input_tokens_mean'] is None


def test_oversized_retry_after_stops_without_wait(tmp_path):
    cfg,m=fixture(tmp_path);m['calls']=m['calls'][:1]
    seen=[]
    async def transport(*args):
        seen.append(1)
        return {'ok':False,'status_code':429,'error':'throttle','retryable':True,'retry_after':'3600'}
    begin=time.monotonic()
    asyncio.run(execute(cfg,m,{}, {'transport':'test'},transport))
    assert len(seen)==1 and time.monotonic()-begin<1


def test_timeout_attempts_bounded(tmp_path):
    cfg,m=fixture(tmp_path);m['calls']=m['calls'][:1]
    seen=[]
    async def transport(*args):
        seen.append(1)
        return {'ok':False,'error':'timeout','retryable':True}
    asyncio.run(execute(cfg,m,{}, {'transport':'test'},transport))
    assert len(seen)==cfg['execution']['retries']+1


def test_stop_during_retry_does_not_dispatch_again(tmp_path):
    cfg,m=fixture(tmp_path); cfg['execution']['retry_backoff_seconds']=.5
    cfg['execution']['max_backoff_seconds']=1
    calls=[]
    async def exercise():
        with Journal(tmp_path/'run') as j:
            async def transport(*args):
                calls.append(1)
                asyncio.get_running_loop().call_later(.01,runner.stop.set)
                return {'ok':False,'error':'timeout','retryable':True}
            runner=Executor(cfg,m,j,'test',transport)
            await runner.run_call(m['calls'][0])
    asyncio.run(exercise()); assert len(calls)==1


def test_background_mock_completes_and_status(tmp_path):
    import yaml
    from llm10.datasets import prepare
    cfg,m=fixture(tmp_path)
    # True mock endpoint with fixture dataset, never a hand-written live corpus.
    cfg['execution']['retry_backoff_seconds']=.01
    cfg['safety']['cooldown_seconds']=.01
    def loader(source,cache):
        for i in range(3):yield 'train',i,{'instruction':f'Question {i}','input':'context'}
    prepare(cfg,loader)
    path=tmp_path/'config.yaml';path.write_text(yaml.safe_dump(cfg))
    logs=tmp_path/'logs'
    command=[sys.executable,str(ROOT/'llm10/background.py')]
    p=subprocess.run(command+['start','--config',str(path),'--logs',str(logs)],capture_output=True,text=True,timeout=10)
    assert p.returncode==0,p.stderr
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        state=json.loads((logs/'background.json').read_text())
        if state['status']!='running':break
        time.sleep(.05)
    assert state['status']=='finished',(logs/'latest.log').read_text()
    assert state['exit_code']==0
    status=subprocess.run(command+['status','--config',str(path),'--logs',str(logs)],capture_output=True,text=True,timeout=10)
    assert status.returncode==0,status.stderr
    assert '"process_alive": false' in status.stdout


def test_background_stop_and_resume(tmp_path):
    import yaml
    from llm10.datasets import prepare
    cfg,m=fixture(tmp_path);cfg['safety']['cooldown_seconds']=.15
    def loader(source,cache):
        for i in range(3):yield 'train',i,{'instruction':f'Question {i}','input':'context'}
    prepare(cfg,loader)
    path=tmp_path/'config.yaml';path.write_text(yaml.safe_dump(cfg))
    logs=tmp_path/'logs'
    command=[sys.executable,str(ROOT/'llm10/background.py')]
    options=['--config',str(path),'--logs',str(logs)]
    def invoke(action):return subprocess.run(command+[action]+options,capture_output=True,text=True,timeout=10)
    assert invoke('start').returncode==0
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        journals=list((tmp_path/'results').glob('*/events.jsonl'))
        if journals and '"kind": "call_finished"' in journals[0].read_text():break
        time.sleep(.01)
    assert journals
    assert invoke('stop').returncode==0
    while time.monotonic()<deadline:
        state=json.loads((logs/'background.json').read_text())
        if state['status']!='running':break
        time.sleep(.02)
    assert state['status']=='stopped'
    before=[json.loads(l) for l in journals[0].read_text().splitlines()]
    completed={e['call_id'] for e in before if e['kind']=='call_finished'}
    assert invoke('start').returncode==0
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        state=json.loads((logs/'background.json').read_text())
        if state['status']!='running':break
        time.sleep(.05)
    assert state['status']=='finished'
    after=[json.loads(l) for l in journals[0].read_text().splitlines()]
    assert all(sum(e['kind']=='attempt_started' and e['call_id']==c for e in after)==1 for c in completed)


def test_native_loop_telemetry(loop_provider,tmp_path,monkeypatch):
    model,captured,mode=loop_provider
    monkeypatch.setenv('LOOP_CODING_AGENT_DIR',model['agent_directory'])
    if not client.BRIDGE.exists(): pytest.skip('build LLM10 bridge')
    async def run():
        r=await client.complete(model,[{'role':'user','content':'exact'}],100,'key',5)
        assert r['response']['status_code']==200
        assert r['response']['content']=='BRIDGE_OK'
        assert usage(r['response'])==(11,3,14)
        mode['status']=429
        e=await client.complete(model,[{'role':'user','content':'exact'}],100,'key',5)
        assert e['status_code']==429 and e['retry_after']=='0'
        assert e['rate_limits']['retry-after']=='0'
    asyncio.run(run())


from llm02.tests.test_loop_transport import loop_provider
