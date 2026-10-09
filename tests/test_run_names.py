import json
from pathlib import Path
import tempfile
import unittest
from html.parser import HTMLParser
from run_names import register, run_name
from reporting import envelope


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.extend(v for k,v in attrs if k=='href')


class RunNameTests(unittest.TestCase):
    def test_readable_stable_safe_names(self):
        self.assertEqual(run_name('llm06', {'model':'sarvam-30b'}, 'b0cf3bf06370', 4000, 'scenario_variant'),
                         'llm06-sarvam-30b-4000-tests-b0cf3bf0')
        name = run_name('llm10', {'model':'../../Model <script>', 'mode':'mock'}, 'abcdefgh1', 12, 'workload_call')
        self.assertEqual(name,'llm10-model-script-mock-12-calls-abcdefgh')
        self.assertNotIn('/',name)

    def test_catalog_links_refresh_collision_and_original_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/'original'
            source.mkdir()
            (source/'events.jsonl').write_text('evidence\n')
            for number, identity in enumerate(['abcdefgh-one','abcdefgh-two','abcdefgh-one']):
                report=root/f'snapshot-{number}'
                report.mkdir()
                (report/'report.html').write_text('report')
                doc=envelope('llm06',identity,{'model':'test'},dict(unit='scenario_variant',planned=10,
                    completed=number,errored=0,skipped=0,pending=10-number),{}, {}, [], [], [])
                (report/'report.json').write_text(json.dumps(doc))
                page=register(root/'runs',report/'report.html',source)
                links=Links();links.feed(page.read_text())
                self.assertTrue(all((page.parent/link).exists() for link in links.links))
                self.assertIn(str(report/'report.html'),(page.parent/'run.json').read_text())
            self.assertEqual(len(list((root/'runs').glob('*/run.json'))),2)
            self.assertEqual((source/'events.jsonl').read_text(),'evidence\n')
            self.assertFalse(page.is_symlink())

    def test_rejects_unsafe_catalog_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            doc=envelope('llm02','r',{},dict(unit='test',planned=0,completed=0,errored=0,skipped=0,pending=0),{},{},[],[],[])
            doc['run']['name']='../escape'
            (root/'report.json').write_text(json.dumps(doc))
            with self.assertRaises(ValueError):
                register(root/'runs',root/'report.html',root)
