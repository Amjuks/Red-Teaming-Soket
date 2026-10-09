"""Detached local jobs with PID identity checks and durable progress summaries."""
import fcntl
import shlex
import json
import os
import signal
import subprocess
import sys
from collections import Counter
from common import ROOT, atomic_json, local_path


def process_identity(pid):
    try:
        # Fields after the final ')' begin at /proc stat field 3.
        fields=open(f'/proc/{pid}/stat').read().rsplit(')',1)[1].split()
        if fields[0]=='Z':return None
        return fields[19]
    except (OSError,IndexError):return None


def running(directory):
    try:job=json.loads((directory/'background.json').read_text())
    except (OSError,ValueError):return False
    return process_identity(job['pid'])==job.get('process_identity') and job.get('process_identity') is not None


def launch(directory,arguments):
    directory=local_path(directory);directory.mkdir(parents=True,exist_ok=True)
    # Journal lock also rejects collisions with foreground runs.
    from journal import Journal
    with (directory/'launch.lock').open('a+') as launch_lock:
        fcntl.flock(launch_lock,fcntl.LOCK_EX)
        with Journal(directory):pass
        if running(directory):raise ValueError('This background run is already active')
        log=directory/'background.log'
        with log.open('ab') as output:
            process=subprocess.Popen([sys.executable,'-u',str(ROOT/'run.py'),*arguments],cwd=ROOT,
                stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        atomic_json(directory/'background.json',{'pid':process.pid,'process_identity':process_identity(process.pid),
            'arguments':arguments,'log':str(log)})
    print(f'Background PID: {process.pid}\nRun: {directory}\nLog: {log}\nCheck: .venv/bin/python run.py --status {shlex.quote(str(directory))}\nStop: .venv/bin/python run.py --stop {shlex.quote(str(directory))}')


def stop(directory):
    directory=local_path(directory)
    if not running(directory):print('No active background process for this run.');return
    job=json.loads((directory/'background.json').read_text())
    os.kill(job['pid'],signal.SIGTERM)
    print('Stop requested. The runner will save its journal and partial report.')


def status(directory):
    directory=local_path(directory)
    raw=(directory/'events.jsonl').read_bytes()
    events=[json.loads(line) for line in raw.splitlines(keepends=True) if line.endswith(b'\n')]
    start=next((e for e in events if e['kind']=='run_start'),None)
    counts=Counter(e['kind'] for e in events)
    results={e['test_id']:e for e in events if e['kind']=='test_result'}
    planned=len(start['tests']) if start else 0
    pending={e['test_id'] for e in events if e['kind']=='judge_pending'}-set(results)
    active=next((e['test_id'] for e in reversed(events) if e['kind']=='test_start' and e['test_id'] not in results),None)
    alive=running(directory)
    state='running' if alive else 'finished' if planned and len(results)==planned else 'stopped or foreground'
    report=local_path(start['config']['reports_dir'])/start['run_id']/'report.html' if start else None
    if str(ROOT.parent) not in sys.path:
        sys.path.append(str(ROOT.parent))
    from run_names import run_name
    name = run_name('llm06', start['config']['target'], start['run_id'], planned, 'scenario_variant') if start else None
    return {**dict(counts),'state':state,'run_name':name,'run_id':start['run_id'] if start else directory.name,
        'planned':planned,'finished_tests':len(results),'percent':round(100*len(results)/planned,1) if planned else 0,
        'completed':sum(e['status']=='completed' for e in results.values()),
        'errored':sum(e['status']=='errored' for e in results.values()),'pending_judge':len(pending),
        'remaining':max(0,planned-len(results)),'active_test':active,'background_active':alive,
        'last_event_time':events[-1]['time'] if events else None,'log':str(directory/'background.log'),
        'report':str(report) if report else None}
