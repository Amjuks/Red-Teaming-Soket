import json
from pathlib import Path
import tempfile
import unittest
from run_names import register, run_name
from reporting import envelope, normalize

class RunNameTests(unittest.TestCase):
    def test_readable_safe_names(self):
        self.assertEqual(run_name('llm06',{'model':'sarvam-30b'},'b0cf3bf06370',4000,'scenario_variant'),
                         'llm06-sarvam-30b-4000-tests-b0cf3bf0')
        self.assertNotIn('/',run_name('llm10',{'model':'../../Model'},'abcdefgh1',12,'workload_call'))

    def test_latest_is_full_report_and_links_preserve_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'original';source.mkdir()
            (source/'events.jsonl').write_text('evidence\n')
            for i in range(2):
                report=root/f'snapshot-{i}';report.mkdir()
                doc=envelope('llm02',f'run-{i}',{'model':'test'},dict(unit='test',planned=10,
                    completed=i,errored=0,skipped=0,pending=10-i),{}, {'overall':{}}, [], [], [])
                doc=normalize(doc,{})
                (report/'report.json').write_text(json.dumps(doc))
                path=register(root/'runs',report/'report.md',source)
                self.assertIn('## Assessment',path.read_text())
                self.assertIn('## Findings',path.read_text())
                stored=json.loads(path.with_suffix('.json').read_text())
                self.assertTrue(all((path.parent/a['path']).exists() for a in stored['artifacts']))
            self.assertEqual(len(list((root/'runs').glob('*/run.json'))),1)
            self.assertEqual(stored['run']['id'],'run-1')
            self.assertEqual((source/'events.jsonl').read_text(),'evidence\n')
            self.assertFalse(list(root.rglob('*.html')))
