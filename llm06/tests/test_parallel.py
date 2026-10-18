import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from common import ROOT,load_config,identity
from journal import Journal
from scheduler import run_tests
from runner import execute
from tests.fixtures import scenario,response,call,Scripted
from report import build

class ParallelTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'.cache/tests').mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.cache/tests')
        self.config=load_config();self.config.update(concurrency=3,judge=None)
    def tearDown(self):self.temp.cleanup()
    def planned(self,n):
        result=[]
        for i in range(n):
            s=scenario();s['task']=f'Read note {i}';s['scenario_id']=f's{i}'
            s['initial_state']['files']['a']['content']=f'private-case-{i}'
            result.append({'test_id':str(i),'scenario':s})
        return result
    def test_workers_overlap_and_journal_stays_ordered_and_resumable(self):
        barrier=threading.Barrier(3);mutex=threading.Lock();live=0;peak=0
        def fake(j,tid,s,c,target,jc,**kwargs):
            nonlocal live,peak
            with mutex:live+=1;peak=max(peak,live)
            barrier.wait(timeout=5)
            j.append('test_result',test_id=tid,status='completed',evaluation={})
            with mutex:live-=1
        with Journal(self.temp.name) as j:
            planned=self.planned(6)
            j.append('run_start',run_id='parallel',config=self.config,coverage={},tests=planned)
            run_tests(j,planned,self.config,None,None,threading.Event(),lambda *a:None,execute_fn=fake)
            self.assertEqual(peak,3)
            snapshot=j.snapshot();self.assertEqual([e['seq'] for e in snapshot],list(range(len(snapshot))))
            self.assertEqual({e['test_id'] for e in snapshot if e['kind']=='test_result'},{str(i) for i in range(6)})
            n=len(snapshot)
            run_tests(j,planned,self.config,None,None,threading.Event(),lambda *a:None,execute_fn=fake)
            self.assertEqual(len(j.snapshot()),n)
        with Journal(self.temp.name) as j:
            for e in j.snapshot():
                checksum=e['checksum'];self.assertEqual(identity({k:v for k,v in e.items() if k!='checksum'}),checksum)
    def test_actual_tool_states_are_isolated_between_cases(self):
        class Target:
            def complete(self,messages,tools,key):
                if any(m['role']=='tool' for m in messages):return response(text='done')
                return response([call('files_read',{'id':'a'},key)])
        with Journal(self.temp.name) as j:
            planned=self.planned(9)
            j.append('run_start',run_id='isolated',config=self.config,coverage={},tests=planned)
            run_tests(j,planned,self.config,Target(),None,threading.Event(),lambda *a:None)
            for i in range(9):
                events=j.test_events(str(i));commits=[e for e in events if e['kind']=='tool_commit']
                self.assertEqual(len(commits),1)
                self.assertIn(f'private-case-{i}',json.dumps(commits[0]['result']['output']))
                self.assertEqual([e for e in events if e['kind']=='test_result'][-1]['status'],'completed')
    def test_graceful_stop_leaves_unscheduled_cases_for_resume(self):
        stop=threading.Event()
        def fake(j,tid,*args,**kwargs):
            j.append('test_result',test_id=tid,status='completed',evaluation={})
            stop.set()
        with Journal(self.temp.name) as j:
            planned=self.planned(100)
            j.append('run_start',run_id='stop',config=self.config,coverage={},tests=planned)
            run_tests(j,planned,self.config,None,None,stop,lambda *a:None,execute_fn=fake)
            completed=[e for e in j.snapshot() if e['kind']=='test_result']
            self.assertGreaterEqual(len(completed),1);self.assertLessEqual(len(completed),3)
    def test_report_uses_recorded_effective_concurrency_without_mutating_start(self):
        with Journal(self.temp.name) as j:
            config={**self.config,'concurrency':1}
            j.append('run_start',run_id='settings',config=config,coverage={},tests=self.planned(1))
            j.append('execution_settings',concurrency=4)
            _,path=build(j,j.directory/'reports')
            doc=json.loads(path.with_suffix('.json').read_text())
            self.assertEqual(doc['configuration']['concurrency'],4)
            self.assertEqual(j.events[0]['config']['concurrency'],1)

class ResumeCliTests(unittest.TestCase):
    def test_resume_keeps_original_ids_and_does_not_make_model_calls(self):
        import subprocess
        from evaluator import evaluate
        (ROOT/'.cache/tests').mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache/tests') as temp:
            from pathlib import Path
            base=Path(temp);directory=base/'results/saved-run'
            config=load_config();config.update(concurrency=1,judge=None,results_dir=str(base/'results'),reports_dir=str(base/'reports'))
            tests=[{'test_id':'saved-a','scenario':scenario()},{'test_id':'saved-b','scenario':scenario()}]
            with Journal(directory) as j:
                j.append('run_start',run_id='saved-run',config=config,coverage={'fixture':True},tests=tests)
                for test in tests:j.append('test_result',test_id=test['test_id'],status='completed',evaluation=evaluate(test['scenario'],[]))
            proc=subprocess.run([str(ROOT/'.venv/bin/python'),str(ROOT/'run.py'),'--resume-run',str(directory),'--concurrency','3'],cwd=ROOT,capture_output=True,text=True,timeout=30)
            self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
            with Journal(directory) as j:
                self.assertEqual([e['test_id'] for e in j.events if e['kind']=='test_result'],['saved-a','saved-b'])
                self.assertFalse(any(e['kind']=='target_request' for e in j.events))
                self.assertEqual([e for e in j.events if e['kind']=='execution_settings'][-1]['concurrency'],3)
                self.assertEqual(j.events[0]['config']['concurrency'],1)
