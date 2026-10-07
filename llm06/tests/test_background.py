import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from common import ROOT
from background import process_identity,running,stop,status
from journal import Journal
from tests.fixtures import scenario
from common import load_config

class BackgroundTests(unittest.TestCase):
    def test_pid_reuse_guard_and_stop(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache/tests') as temp:
            path=Path(temp)
            process=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-c','import time; time.sleep(30)'])
            try:
                (path/'background.json').write_text(json.dumps({'pid':process.pid,'process_identity':'wrong'}))
                self.assertFalse(running(path));stop(path);self.assertIsNone(process.poll())
                (path/'background.json').write_text(json.dumps({'pid':process.pid,'process_identity':process_identity(process.pid)}))
                self.assertTrue(running(path));stop(path);process.wait(timeout=5)
                self.assertFalse(running(path))
            finally:
                if process.poll() is None:process.kill();process.wait()
    def test_progress_from_journal_ignores_partial_tail(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.cache/tests') as temp:
            path=Path(temp)
            with Journal(path) as journal:
                journal.append('run_start',run_id='fixture',config=load_config(),tests=[{'test_id':'a','scenario':scenario()},{'test_id':'b','scenario':scenario()}])
                journal.append('test_start',test_id='a')
                journal.append('test_result',test_id='a',status='completed')
                with (path/'events.jsonl').open('ab') as f:f.write(b'{')
                result=status(path)
                self.assertEqual(result['finished_tests'],1);self.assertEqual(result['percent'],50)
                self.assertEqual(result['remaining'],1);self.assertEqual(result['completed'],1)

if __name__=='__main__':unittest.main()
