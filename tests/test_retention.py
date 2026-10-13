import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from retention import prune_history

class RetentionTests(unittest.TestCase):
    def test_keeps_journal_and_analysis_removes_old_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'llm06';keep=base/'results/nested/new';old=base/'results/old'
            keep.mkdir(parents=True);old.mkdir()
            for p in (keep,old):(p/'events.jsonl').write_text('original')
            (keep/'analysis').mkdir();(keep/'analysis/results.jsonl').write_text('evidence')
            (keep/'report-snapshots').mkdir();(keep/'report-snapshots/old.html').write_text('old')
            (base/'reports').mkdir();(base/'reports/old.html').write_text('old')
            report=Path(tmp)/'runs/llm06/report.md';report.parent.mkdir(parents=True)
            report.with_suffix('.json').write_text(json.dumps({'run':{'id':'new'}}));report.write_text('assessment')
            prune_history(base,keep,report)
            self.assertEqual((keep/'events.jsonl').read_text(),'original')
            self.assertTrue((keep/'analysis/results.jsonl').exists())
            self.assertFalse(old.exists());self.assertFalse((keep/'report-snapshots').exists())
            self.assertEqual((base/'results/latest').resolve(),keep)
            self.assertEqual(json.loads((base/'results/latest.json').read_text())['report'],str(report))

    def test_active_writer_blocks_all_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'llm06';keep=base/'results/new';old=base/'results/old'
            keep.mkdir(parents=True);old.mkdir();(keep/'events.jsonl').write_text('evidence')
            report=Path(tmp)/'report.md';report.with_suffix('.json').write_text(json.dumps({'run':{'id':'new'}}))
            with (keep/'writer.lock').open('w') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):prune_history(base,keep,report)
                self.assertTrue(old.exists())
