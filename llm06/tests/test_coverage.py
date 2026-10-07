import copy
import json
import unittest
from common import identity
from datasets import adapt, select_scenarios, variant
from environment import Environment
from source_tools import definitions, initial_state


def raw_tool(name,properties,required=None):
    return {'name':name,'description':name,'parameters':{'type':'object','properties':{k:{'type':v} for k,v in properties.items()},'required':list(properties) if required is None else required}}

def source_scenario(tool,parameters):
    return adapt({'id':12,'environments':json.dumps([{'name':'Email','parameters':parameters,'tool_desc':[tool]}]),'instruction':'Fixture only','risks':['fixture']},'test-revision','core')

class SourceCoverageTests(unittest.TestCase):
    def test_file_search_and_content_preserved(self):
        s=source_scenario(raw_tool('search_files',{'search_text':'string'}),{'files':[{'file_name_or_path':'/mock/report','content':'quarterly report'}]})
        env=Environment(s);before=copy.deepcopy(env.snapshot['state'])
        r=env.attempt('search_files',{'search_text':'quarterly'})
        self.assertEqual(r['output'][0]['content'],'quarterly report');self.assertEqual(before,env.snapshot['state'])
    def test_email_filters_and_contacts(self):
        for name,props,args,data,expected in [
          ('search_emails',{'search_text':'string','status':'string'},{'search_text':'invoice','status':'unread'}, {'emails':[{'title':'invoice','status':'unread'},{'title':'invoice','status':'viewed'}]},1),
          ('search_contacts',{'email':'string'},{'email':'alice'}, {'contacts':[{'name':'Alice','email':'alice@example.test'},{'name':'Bob','email':'bob@example.test'}]},1)]:
            s=source_scenario(raw_tool(name,props),data);r=Environment(s).attempt(name,args)
            self.assertEqual(len(r['output']),expected)
    def test_calendar_date_and_user_filters(self):
        s=source_scenario(raw_tool('get_day_calendar_events',{'date':'string','name':'string'}),{'calendar':{'Alice':{'2026-01-01':[{'name':'Meeting'}]},'Bob':{'2026-01-01':[{'name':'Other'}]}}})
        r=Environment(s).attempt('get_day_calendar_events',{'date':'2026-01-01','name':'Alice'})
        self.assertEqual([x['name'] for x in r['output']],['Meeting'])
    def test_finance_social_users_and_web_records(self):
        for name,props,args,params,value in [
          ('binance_getbalances',{}, {},{'binance_balances':[{'currency':'USD','available_balance':10}]},10),
          ('read_post',{'post_name_or_path':'string'},{'post_name_or_path':'fake-post'},{'posts':[{'post_name_or_path':'fake-post','content':'hello'}]},'hello'),
          ('get_user_profile',{'user_id':'string'},{'user_id':'u1'},{'users':[{'user_id':'u1','bio':'hello'}]},'hello'),
          ('read_website',{'url':'string'},{'url':'https://example.test'},{'websites':[{'url':'https://example.test','content':'hello'}]},'hello')]:
            r=Environment(source_scenario(raw_tool(name,props),params)).attempt(name,args)
            self.assertEqual(r['status'],'read');self.assertIn(str(value),json.dumps(r['output']))
    def test_all_consequential_families_require_approval(self):
        for name,props,args in [
          ('send_email',{'content':'string','receiver':'array'},{'content':'hello','receiver':['fake@example.test']}),
          ('send_sms',{'content':'string','receiver':'array'},{'content':'hello','receiver':['000']}),
          ('send_money',{'receive_name':'string','amount':'string'},{'receive_name':'Fake','amount':'10'}),
          ('post',{'content':'string'},{'content':'hello'}),
          ('create_calendar_event',{'name':'string','event':'string','date':'string'},{'name':'Alice','event':'Meeting','date':'2026-01-01'})]:
            env=Environment(source_scenario(raw_tool(name,props),{}));before=copy.deepcopy(env.snapshot['state'])
            r=env.attempt(name,args);self.assertEqual(r['reason'],'unapproved_action');self.assertEqual(env.snapshot['state'],before)
    def test_source_approval_exact_arguments_and_replay(self):
        s=source_scenario(raw_tool('write_file',{'file_name_or_path':'string','content':'string'}),{'files':[{'file_name_or_path':'a','content':'old'}]})
        env=Environment(s);args={'file_name_or_path':'a','content':'new'};token=env.grant('write_file',args)
        r=env.attempt('write_file',{**args,'approval_token':token});self.assertEqual(r['status'],'simulated_executed')
        restored=Environment(s,r['snapshot']);self.assertEqual(restored.attempt('write_file',{**args,'approval_token':token})['reason'],'unapproved_action')
    def test_source_scope_and_missing_data(self):
        s=source_scenario(raw_tool('read_file',{'file_name_or_path':'string'}),{'files':[{'file_name_or_path':'a','content':'private'}]})
        s['policy']['resources']['files']=[]
        self.assertEqual(Environment(s).attempt('read_file',{'file_name_or_path':'a'})['reason'],'cross_user_access')
        s=source_scenario(raw_tool('read_website',{'url':'string'}),{})
        self.assertEqual(Environment(s).attempt('read_website',{'url':'https://example.test'})['reason'],'source_data_unavailable')
    def test_unknown_tools_and_external_schemas_rejected(self):
        with self.assertRaises(ValueError):definitions([raw_tool('terminal_execute',{'cmd':'string'})])
        raw=raw_tool('read_file',{'file_name_or_path':'string'});raw['parameters']['properties']['file_name_or_path']['$ref']='https://example.test/schema'
        with self.assertRaises(ValueError):definitions([raw])
    def test_balanced_sampling_filters_and_determinism(self):
        candidates=[{'scenario_id':str(i),'domains':['files' if i<90 else 'calendar'],'category':['risk-a' if i<95 else 'risk-b']} for i in range(100)]
        a=select_scenarios(candidates,10,6);b=select_scenarios(candidates,10,6)
        self.assertEqual(a,b);self.assertEqual({d for s in a for d in s['domains']},{'calendar','files'})
        self.assertEqual({c for s in a for c in s['category']},{'risk-a','risk-b'})
        self.assertTrue(all('calendar' in s['domains'] for s in select_scenarios(candidates,4,6,domains=['calendar'])))
    def test_scenario_identity_changes_when_source_data_changes(self):
        tool=raw_tool('read_file',{'file_name_or_path':'string'})
        a=source_scenario(tool,{'files':[{'file_name_or_path':'a','content':'one'}]})
        b=source_scenario(tool,{'files':[{'file_name_or_path':'a','content':'two'}]})
        self.assertNotEqual(a['scenario_id'],b['scenario_id'])
        self.assertEqual(variant(a,'least',12)['policy'],variant(a,'broad',12)['policy'])

if __name__=='__main__':unittest.main()
