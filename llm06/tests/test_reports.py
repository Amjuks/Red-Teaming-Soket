import copy
import json
import tempfile
import unittest
from pathlib import Path
from common import ROOT,load_config
from journal import Journal
from report import build
from runner import execute
from tests.fixtures import scenario,Scripted,response,call

class ReportTests(unittest.TestCase):
    def test_group_denominators_pairs_and_escaped_evidence(self):
        (ROOT/'.cache/tests').mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache/tests') as temp:
            config=load_config();config.update(judge=None,max_turns=2,retries=0)
            a=scenario();a.update(domains=['files','email'],category=['leak','loss'],task='<script>alert(1)</script>')
            b=copy.deepcopy(a);b['variant_id']='broad'
            with Journal(temp) as journal:
                journal.append('run_start',run_id='test-report',config=config,coverage={'dataset':'aradhye/agent-safety-bench'},tests=[{'test_id':'a','scenario':a},{'test_id':'b','scenario':b}])
                execute(journal,'a',a,config,Scripted([response([call('files_share',{'id':'a','to':'other'})]),response(text='<img src=x onerror=alert(1)>')]))
                execute(journal,'b',b,config,Scripted([response(text='finished')]))
                metrics,path=build(journal,Path(temp)/'reports')
                self.assertEqual(metrics['unique_scenarios'],1)
                self.assertEqual(metrics['by_domain']['files']['planned'],2)
                self.assertEqual(metrics['by_category']['leak']['risky']['denominator'],2)
                self.assertEqual(metrics['by_category']['leak']['risky']['numerator'],1)
                self.assertEqual(metrics['pairs'][0]['least_findings'],1)
                self.assertEqual(metrics['pairs'][0]['broad_findings'],0)
                self.assertEqual(metrics['pairs'][0]['added_tools'],0)
                self.assertEqual(metrics['finish_reasons']['stop'],2)
                html=path.read_text();self.assertNotIn('<script>alert(1)</script>',html)
                self.assertNotIn('<img src=x',html);self.assertIn('&lt;script&gt;',html)
                self.assertTrue((path.parent.parent/'index.html').exists())
                first=(Path(temp)/'metrics.json').read_bytes();build(journal,Path(temp)/'reports')
                self.assertEqual(first,(Path(temp)/'metrics.json').read_bytes())
    def test_demo_does_not_replace_benchmark_pointer(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache/tests') as temp:
            config=load_config();config['judge']=None
            with Journal(temp) as journal:
                journal.append('run_start',run_id='demo',config=config,coverage={'mode':'offline-fixture'},tests=[{'test_id':'a','scenario':scenario()}])
                build(journal,Path(temp)/'reports')
                self.assertFalse((Path(temp)/'reports/latest.json').exists())

if __name__=='__main__':unittest.main()
