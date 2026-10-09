import ast
import copy
import unittest
from catalog import Catalog
from projections import compile_read,project,Unsupported
from json_queries import compile_query,evaluate
from catalog_adapter import adapt_catalog
from environment import Environment
import json

class QueryTests(unittest.TestCase):
    def methods(self,text):return {n.name:n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef)}
    def test_bounded_filter_query_and_source_immutability(self):
        methods=self.methods('''
def __init__(self,parameters=None):
 self.items=self.parameters.get("items",[])
def search(self,query=None):
 result=[]
 for item in self.items:
  if query is None or query.lower() in item.get("name", "").lower():
   result.append(item)
 return {"items":result}
''')
        plan=compile_query(methods,'search');data={'items':[{'name':'Alice'},{'name':'Bob'}]};before=copy.deepcopy(data)
        self.assertEqual(evaluate(plan,data,{'query':'ali'}),{'items':[{'name':'Alice'}]})
        self.assertEqual(data,before)
    def test_forbidden_execution_syntax_rejected(self):
        for body in ['return open("/etc/passwd").read()','return __import__("os").system("echo bad")','import os\n return 1','self.items.append(1)\n return self.items','return eval(query)','while True:\n  pass']:
            text='def read(self,query=None):\n '+body.replace('\n','\n ')
            with self.assertRaises((ValueError,SyntaxError)):compile_query(self.methods(text),'read')
    def test_resource_limit(self):
        methods=self.methods('def read(self):\n return [x for x in self.parameters.get("items",[]) if x]')
        with self.assertRaises(ValueError):evaluate(compile_query(methods,'read'),{'items':list(range(100000))},{})
    def test_missing_data_is_not_default_success(self):
        methods=self.methods('def read(self):\n return self.parameters.get("items",[])')
        with self.assertRaises(KeyError):evaluate(compile_query(methods,'read'),{}, {})
    def test_catalog_source_pinning(self):
        catalog=Catalog();methods,schemas,digest=catalog.environment('Github')
        self.assertEqual(len(digest),64);self.assertIn('get_user_details',methods)
        result=evaluate(compile_query(methods,'get_user_details'),{'users':[{'username':'alice'}]}, {'username':'alice'})
        self.assertEqual(result,{'success':True,'user':{'username':'alice'}})
    def test_catalog_projection_and_approval_gate(self):
        row={'id':1,'instruction':'Check resources','risks':['test'],'gt_tools':[],
          'environments':json.dumps([{'name':'ResourceOptimization','parameters':{'systems':[{'id':'fake'}]},'gt_tools':['monitor_power_levels','adjust_power_output']}])}
        scenario=adapt_catalog(row,'test','core',Catalog());env=Environment(scenario);before=copy.deepcopy(env.snapshot['state'])
        result=env.attempt('monitor_power_levels',{})
        self.assertEqual(result['output']['data'],[{'id':'fake'}])
        args={'system_id':'fake','new_power_output':'1'}
        result=env.attempt('adjust_power_output',args);self.assertEqual(result['reason'],'unapproved_action')
        self.assertEqual(env.snapshot['state'],before)
        token=env.grant('adjust_power_output',args)
        result=env.attempt('adjust_power_output',{**args,'approval_token':token})
        self.assertEqual(result['reason'],'effect_executor_unavailable');self.assertEqual(env.snapshot['state'],before)
    def test_catalog_scope_enforced(self):
        row={'id':1,'instruction':'Check resources','risks':['test'],'environments':json.dumps([{'name':'ResourceOptimization','parameters':{'systems':[]},'gt_tools':['monitor_power_levels']}])}
        scenario=adapt_catalog(row,'test','core',Catalog());env=Environment(scenario)
        for value in env.snapshot['state'].values():value['owner']='other-user'
        self.assertEqual(env.attempt('monitor_power_levels',{})['reason'],'cross_user_access')

if __name__=='__main__':unittest.main()

class DatasetScaleTests(unittest.TestCase):
    def test_unique_task_selection_does_not_repeat_instructions(self):
        from datasets import select_scenarios
        data=[{'task':'task '+str(i//2),'domains':['software'],'category':['risk']} for i in range(100)]
        selected=select_scenarios(data,80,6,unique_tasks=True)
        self.assertEqual(len(selected),50);self.assertEqual(len({s['task'] for s in selected}),50)
    def test_augmented_source_is_parsed_not_imported(self):
        from catalog_adapter import adapt_catalog
        code='''import never_import_this_package
class Example:
 def __init__(self, parameters=None):
  self.items=self.parameters.get("items",[])
 def list_items(self):
  return {"items":self.items}
'''
        schema={'name':'list_items','description':'List supplied items','parameters':{'type':'object','properties':{}}}
        row={'instruction':'List the items','python_codes':json.dumps([code]),'parameters':json.dumps([{'items':[1,2]}]),'tool_descs':json.dumps([[schema]])}
        s=adapt_catalog(row,'test','augmented',Catalog(),0)
        self.assertEqual(Environment(s).attempt('list_items',{})['output'],{'items':[1,2]})
        self.assertEqual(s['category'],['Unlabeled (augmented source)'])
