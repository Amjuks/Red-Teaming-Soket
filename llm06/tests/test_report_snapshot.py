import json
from pathlib import Path
import tempfile
import unittest
from common import ROOT, load_config
from export_reports import export_snapshot
from journal import Journal
from tests.fixtures import scenario


class SnapshotTests(unittest.TestCase):
    def test_active_writer_and_torn_tail_are_not_modified(self):
        (ROOT/'.cache/tests').mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache/tests') as tmp:
            directory = Path(tmp)
            with Journal(directory) as journal:
                journal.append('run_start', run_id='snapshot', config=load_config(), coverage={},
                               tests=[{'test_id':'one', 'scenario':scenario()}])
                with journal.path.open('ab') as stream:
                    stream.write(b'{"incomplete":')
                before = journal.path.read_bytes()
                report = export_snapshot(directory)
                self.assertEqual(journal.path.read_bytes(), before)
                self.assertFalse((directory/'metrics.json').exists())
                doc = json.loads((report.parent/'report.json').read_text())
                self.assertEqual(doc['progress']['pending'], 1)
                self.assertNotEqual(report.parent, directory)

    def test_checksum_failure_aborts_without_writing(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache/tests') as tmp:
            directory = Path(tmp)
            with Journal(directory) as journal:
                journal.append('example', value='original')
            raw = (directory/'events.jsonl').read_bytes().replace(b'original', b'modified')
            (directory/'events.jsonl').write_bytes(raw)
            with self.assertRaisesRegex(ValueError, 'integrity'):
                export_snapshot(directory)
            self.assertEqual((directory/'events.jsonl').read_bytes(), raw)
            self.assertFalse((directory/'report-snapshots').exists())
