import json
from pathlib import Path
import tempfile
import unittest
from reporting import envelope, overview, publish


class CommonReportingTests(unittest.TestCase):
    def test_accounting_rejects_invalid_counts(self):
        for pending in (-1, 2):
            with self.assertRaises(ValueError):
                envelope('llm02', 'r', {}, dict(unit='test', planned=1, completed=0,
                         errored=0, skipped=0, pending=pending), {}, {}, [], [], [])

    def test_escaping_and_model_allowlist(self):
        doc = envelope('llm02', '<script>x</script>', {'model':'<img>', 'api_key':'SECRET'},
                       dict(unit='test', planned=1, completed=0, errored=0, skipped=0, pending=1),
                       {}, {}, [], ['<script>bad</script>'], [])
        page = overview(doc)
        self.assertNotIn('SECRET', json.dumps(doc))
        self.assertNotIn('<script>', page)
        self.assertIn('&lt;script&gt;', page)
        self.assertEqual(doc['run']['execution_state'], 'partial')

    def test_native_data_preserved_and_progress_units(self):
        inputs = {
            'llm02': {'overall':{'completed':2,'errors':1},'total_tests':5,'unexecuted':2,'findings':[]},
            'llm06': {'status_counts':{'completed':2,'errored':1,'pending_judge':1,'planned':1},'planned':5},
            'llm10': {'planned_calls':5,'successful_calls':2,'terminal_calls':4,'skipped_calls':1,
                      'unfinished_calls':1,'overall':{'requests':8},'assessment':{'findings':[], 'limitations':[]}}}
        with tempfile.TemporaryDirectory() as tmp:
            for benchmark, metrics in inputs.items():
                directory = Path(tmp)/benchmark
                directory.mkdir()
                (directory/'metrics.json').write_text('{}')
                report_dir = directory/'html'
                metrics['unknown_measurement'] = None
                page = publish(benchmark, 'run', {'model':'test'}, metrics, {'source':'fixture'}, directory, report_dir)
                doc = json.loads((report_dir/'report.json').read_text())
                self.assertEqual(doc['metrics'], metrics)
                self.assertEqual(doc['coverage'], {'source':'fixture'})
                self.assertEqual(doc['progress']['completed'], 2)
                self.assertEqual(doc['progress']['errored'], 1)
                self.assertEqual(doc['progress']['pending'], 1 if benchmark=='llm10' else 2)
                self.assertEqual((report_dir/doc['artifacts'][0]['path']).resolve(), (directory/'metrics.json').resolve())
                self.assertEqual(len(doc['artifacts']), 1)  # No links to nonexistent evidence.
                self.assertIn('common-downloads', page)
                self.assertEqual((report_dir/'report.json').stat().st_mode & 0o777, 0o600)

    def test_findings_keep_evidence_and_unknown_severity(self):
        raw = {'finding_id':'f','observation':'obs','status':'NOT ASSESSED', 'evidence_attempt_ids':['a'], 'extra':'preserved'}
        metrics = dict(planned_calls=1,successful_calls=1,terminal_calls=1,skipped_calls=0,unfinished_calls=0,
                       assessment={'findings':[raw], 'limitations':[]})
        with tempfile.TemporaryDirectory() as tmp:
            publish('llm10','r',{},metrics,{},tmp,tmp)
            doc=json.loads((Path(tmp)/'report.json').read_text())
            self.assertEqual(doc['findings'][0]['details'], raw)
            self.assertIsNone(doc['findings'][0]['severity'])
            self.assertEqual(doc['findings'][0]['evidence'], [{'attempt_id':'a'}])
            self.assertEqual(doc['run']['execution_state'],'finished')
