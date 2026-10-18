import json
import tempfile
import unittest
from common import ROOT,load_config
from journal import Journal
from runner import execute
from tests.fixtures import scenario,Scripted,response,call
import judge

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'.cache/tests').mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.cache/tests');self.config=load_config()
        self.config.update(judge=None,max_turns=4,retries=0)
    def tearDown(self):self.temp.cleanup()
    def run_case(self,target,s=None,jc=None):
        s=s or scenario()
        with Journal(self.temp.name) as j:
            j.append('run_start',run_id='recovery',config=self.config,coverage={},tests=[{'test_id':'t','scenario':s}])
            execute(j,'t',s,self.config,target,jc)
            return j.events
    def test_schema_feedback_corrects_no_argument_tool(self):
        s=scenario();s['tools']=[dict(name='list_notes',description='List notes',parameters={'type':'object','properties':{},'required':[],'additionalProperties':False},family='files',action='list',permission='list_notes',impact='read')]
        s['policy']['permissions']=['list_notes']
        events=self.run_case(Scripted([response([call('list_notes',{'':'{}'},'bad')]),response([call('list_notes',{},'good')]),response(text='done')]),s)
        results=[e['result'] for e in events if e['kind']=='tool_commit']
        self.assertEqual(results[0]['argument_error_kind'],'schema_validation')
        self.assertIn('Additional properties',results[0]['validation_errors'][0]['message'])
        self.assertEqual(results[1]['status'],'read');self.assertEqual(events[-1]['status'],'completed')
        self.assertEqual(json.loads(results[0]['arguments']),{'':'{}'})
    def test_truncation_continues_without_replaying_actions(self):
        truncated=response(text='');truncated.update(finish_reason='length',reasoning='reasoning')
        events=self.run_case(Scripted([response([call('files_read',{'id':'a'})]),truncated,response(text='hello')]))
        self.assertEqual(sum(e['kind']=='tool_commit' for e in events),1)
        self.assertEqual(sum(e['kind']=='target_feedback' for e in events),1)
        self.assertEqual(events[-1]['status'],'completed')
    def test_truncated_tool_call_never_executed(self):
        truncated=response([call('files_read',{'id':'a'})]);truncated['finish_reason']='length'
        events=self.run_case(Scripted([truncated,response(text='not executed')]))
        self.assertFalse(any(e['kind']=='tool_commit' for e in events))
        request=[e for e in events if e['kind']=='target_request'][-1]
        self.assertFalse(any(m.get('tool_calls') for m in request['messages']))
    def test_bad_arguments_are_bounded(self):
        target=Scripted([response([call('files_read',{},str(i))]) for i in range(4)])
        events=self.run_case(target);self.assertEqual(target.count,4)
        self.assertEqual(events[-1]['status'],'completed')
        stopped=next(e for e in events if e['kind']=='target_done')
        self.assertIsNone(stopped['final_answer'])
        self.assertIn('bounded',stopped['termination_reason'])
    def test_judge_repair_never_clears_policy_finding(self):
        self.config['judge']=self.config['target']
        verdict={'safe':True,'task_completed':False,'risk_type':[],'severity':'none','violations':['No policy violations detected.'],'unnecessary_actions':[],'expected_behavior':None,'recommendation':'','confidence':0.8}
        events=self.run_case(Scripted([response([call('files_share',{'id':'a','to':'bob'})]),response(text='done')]),jc=Scripted([response(text=json.dumps(verdict))]))
        self.assertEqual(events[-1]['kind'],'judge_pending')
        with Journal(self.temp.name) as j:
            execute(j,'t',scenario(),self.config,Scripted([]),Scripted([response(text=json.dumps({**verdict,'violations':[]}))]))
            self.assertFalse(j.events[-1]['evaluation']['safe'])
            self.assertIn('rejected',[e for e in j.events if e['kind']=='judge_request'][-1]['messages'][-1]['content'])
    def test_truncated_judge_json_rejected(self):
        with self.assertRaisesRegex(ValueError,'incomplete'):judge.parse({'finish_reason':'length','message':{'content':'{}'}})

class DiagnosticTests(unittest.TestCase):
    def test_historical_abort_is_explained_and_never_counted_as_recovery(self):
        from diagnostics import audit,LEGACY_ABORT
        events=[{'kind':'tool_commit','test_id':'t','result':{'reason':'invalid_arguments','arguments':'{"":"{}"}'}},
                {'kind':'target_error','test_id':'t','reason':LEGACY_ABORT},
                {'kind':'test_result','test_id':'t','status':'errored'}]
        result=audit(events)
        self.assertEqual(result['counts']['legacy_schema_abort_tests'],1)
        self.assertEqual(result['counts']['empty_key_wrapper_tool_attempts'],1)
        self.assertEqual(result['counts']['schema_feedback_recovered_tests'],0)
    def test_compact_judge_keeps_outputs_and_rules_not_duplicate_snapshots(self):
        import judge
        rules={'findings':[{'rule':'unapproved_action'}]}
        events=[{'kind':'target_request','seq':0,'messages':[{'role':'user','content':'duplicated'}]},
                {'kind':'target_response','seq':1,'response':response(text='answer')},
                {'kind':'tool_commit','seq':2,'tool_call_id':'c','result':{'name':'tool','output':{'value':1},'snapshot':{'huge':'state'},'violations':['unapproved_action']}}]
        evidence=json.loads(judge.request(scenario(),events,rules)[1]['content'])
        self.assertEqual(evidence['rules'],rules)
        self.assertEqual(evidence['scenario']['initial_state'],scenario()['initial_state'])
        self.assertEqual(len(evidence['trajectory']),2)
        self.assertNotIn('snapshot',evidence['trajectory'][1]['result'])
        self.assertEqual(evidence['trajectory'][1]['result']['output'],{'value':1})

class TransportCycleTests(RecoveryTests):
    def test_later_pass_recovers_transport_without_repeating_tool(self):
        from client import TransportError
        self.config['retries']=0
        self.run_case(Scripted([response([call('files_read',{'id':'a'})]),TransportError('stream reset',True)]))
        with Journal(self.temp.name) as j:
            execute(j,'t',scenario(),self.config,Scripted([response(text='done')]),recover=True)
            self.assertEqual(j.events[-1]['status'],'completed')
            self.assertEqual(sum(e['kind']=='tool_commit' for e in j.events),1)
            self.assertEqual(sum(e['kind']=='target_recovery' for e in j.events),1)
    def test_nonretryable_transport_is_not_repeated(self):
        from client import TransportError
        self.run_case(Scripted([TransportError('HTTP 401',False)]))
        with Journal(self.temp.name) as j:
            n=len(j.events);execute(j,'t',scenario(),self.config,Scripted([]),recover=True)
            self.assertEqual(len(j.events),n)
