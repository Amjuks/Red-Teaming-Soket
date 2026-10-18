#!/usr/bin/env python3
"""LLM06 entry point. Full benchmark execution is an explicit user launch."""
import argparse
import json
import signal
import threading
import time
from scheduler import run_tests
from common import ROOT, atomic_json, identity, load_config, local_path
from client import Client
from datasets import prepare,variant
from journal import Journal
from report import build
from runner import execute

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='config.yaml')
    p.add_argument('--concurrency',type=int,choices=range(1,9),help='Parallel test workers (1-8)')
    p.add_argument('--resume-run',metavar='RUN_DIRECTORY',help='Resume saved test IDs; concurrency may change without rerunning completed tests')
    p.add_argument('--sample-limit',type=int,help='Number of unique source scenarios before variants')
    p.add_argument('--splits',nargs='+',choices=['core','augmented'],help='Source splits to include')
    p.add_argument('--domains',nargs='+',help='Include scenarios matching any of these domains')
    p.add_argument('--categories',nargs='+',help='Include exact source risk labels (quote each label)')
    group=p.add_mutually_exclusive_group()
    group.add_argument('--validate-config',action='store_true')
    group.add_argument('--prepare',action='store_true')
    group.add_argument('--audit',action='store_true',help='Audit selected mock tools offline without inference')
    group.add_argument('--offline-demo',action='store_true')
    group.add_argument('--smoke',action='store_true',help='One native read-tool roundtrip through configured target')
    group.add_argument('--report-run',metavar='RUN_DIRECTORY')
    group.add_argument('--status',nargs='?',const='latest',metavar='RUN_DIRECTORY')
    group.add_argument('--background',action='store_true',help='Start a detached benchmark and return immediately')
    group.add_argument('--stop',nargs='?',const='latest',metavar='RUN_DIRECTORY')
    args=p.parse_args();config=load_config(args.config)
    for key in ('sample_limit','domains','categories','splits','concurrency'):
        if getattr(args,key) is not None:config[key]=getattr(args,key)
    from common import CONFIG
    from jsonschema import Draft202012Validator
    Draft202012Validator(CONFIG).validate(config)
    for key in ('status','report_run','stop','resume_run'):
        if getattr(args,key)=='latest':
            pointer=json.loads((local_path(config['results_dir'])/'latest-benchmark.json').read_text())
            setattr(args,key,pointer['directory'])
    if args.validate_config: print('Configuration valid; no inference.');return
    if args.stop:
        from background import stop
        stop(args.stop);return
    if args.status:
        from background import status
        print(json.dumps(status(args.status),indent=2));return
    if args.report_run:
        with Journal(args.report_run) as journal:
            start=next(e for e in journal.events if e['kind']=='run_start')
            _,path=build(journal,start['config']['reports_dir']);print(path);return
    if args.audit:
        from audit import audit
        scenarios,_=prepare(config,download=False)
        result=audit(scenarios);atomic_json(ROOT/'logs/audit-selected.json',result)
        print(json.dumps(result,indent=2));return
    if args.prepare:
        _,m=prepare(config);print(json.dumps({k:m[k] for k in ('source_counts','usable','usable_by_split','unique_task_texts','selected','selected_unique_task_texts','selected_by_split','selected_by_mode','selected_by_domain','selected_by_category','exclusion_counts')},indent=2));return
    if args.resume_run:
        if args.offline_demo or args.smoke or args.sample_limit is not None or args.domains or args.categories or args.splits:
            p.error('--resume-run retains the saved sample set; do not combine it with sample selection or demo options')
        directory=local_path(args.resume_run)
        with (directory/'events.jsonl').open() as stream:saved=json.loads(next(stream))
        if saved['kind']!='run_start':raise ValueError('Saved journal has no run_start')
        runtime=config
        config={**saved['config'],'concurrency':args.concurrency or runtime['concurrency'],
                'report_interval':runtime.get('report_interval',20)}
        Draft202012Validator(CONFIG).validate(config)
        run_id=saved['run_id'];planned=saved['tests'];coverage=saved['coverage']
        client=Client(config['target'])
        import hashlib
        implementation={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('runner.py','client.py','environment.py','judge.py','tools.py','journal.py','scheduler.py')}
        bridge=ROOT/'native/target/debug/llm06-loop-bridge'
        if bridge.exists():implementation['loop_bridge']=hashlib.sha256(bridge.read_bytes()).hexdigest()
    else:
        if args.offline_demo or args.smoke:
            from tests.fixtures import scenario,Scripted,response,call
            s=scenario()
            if args.smoke:
                s['task']='Use files_read to read file a, then report its content. You must call the native tool before answering.'
                s['tools']=[d for d in s['tools'] if d['name']=='files_read'];s['source']['dataset']='live-smoke'
                s['scenario_id']='live-native-smoke'
            scenarios=[s];coverage={'mode':'live-smoke' if args.smoke else 'offline-fixture','benchmark_dataset':False}
            config={**config,'judge':None,'variants':['least'],'max_turns':3,'retries':0}
            client=Client(config['target']) if args.smoke else Scripted([response([call('files_read',{'id':'a'})]),response(text='Your note says hello.')])
        else:
            scenarios,coverage=prepare(config,download=False);client=Client(config['target'])
        if not scenarios:raise ValueError('No supported scenarios selected; inspect data/coverage.json')
        planned=[]
        for s in scenarios:
            for name in config['variants']:
                item=variant(s,name,config['action_budget']);planned.append({'test_id':identity([item,config]),'scenario':item})
        import hashlib
        implementation={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('runner.py','client.py','environment.py','judge.py','tools.py','journal.py','scheduler.py')}
        bridge=ROOT/'native/target/debug/llm06-loop-bridge'
        if bridge.exists():implementation['loop_bridge']=hashlib.sha256(bridge.read_bytes()).hexdigest()
        run_id=identity([config,planned,implementation]);directory=local_path(config['results_dir'])/run_id
    if args.background:
        from background import launch
        # Publish the selected run before starting; child opens its journal normally.
        atomic_json(local_path(config['results_dir'])/'latest-benchmark.json',{'run_id':run_id,'directory':str(directory)})
        import sys
        launch(directory,[arg for arg in sys.argv[1:] if arg!='--background']);return
    with Journal(directory) as journal:
        if not journal.events:journal.append('run_start',run_id=run_id,config=config,coverage=coverage,tests=planned,implementation=implementation)
        atomic_json(local_path(config['results_dir'])/'latest.json',{'run_id':run_id,'directory':str(directory)})
        if coverage.get('dataset')=='aradhye/agent-safety-bench':
            atomic_json(local_path(config['results_dir'])/'latest-benchmark.json',{'run_id':run_id,'directory':str(directory)})
        judge_client=Client(config['judge']) if config['judge'] else None
        stop_event=threading.Event()
        def stop(signum,frame):stop_event.set()
        signal.signal(signal.SIGTERM,stop)
        signal.signal(signal.SIGINT,stop)
        journal.append('execution_settings',concurrency=config['concurrency'],report_interval=config.get('report_interval',20),implementation=implementation,resumed=bool(args.resume_run))
        last_report=time.monotonic();last_count=0;last_logged=-1
        def progress(processed,scheduled,active):
            nonlocal last_report,last_count,last_logged
            outcomes={e['test_id']:e for e in journal.snapshot() if e['kind']=='test_result'}
            current={'run_id':run_id,'planned':len(planned),'processed':len(outcomes),
                     'completed':sum(e['status']=='completed' for e in outcomes.values()),
                     'errored':sum(e['status']=='errored' for e in outcomes.values()),
                     'concurrency':config['concurrency'],'active_tests':active,
                     'phase_processed':processed,'phase_scheduled':scheduled}
            atomic_json(directory/'progress.json',current)
            if len(outcomes)!=last_logged:
                print(json.dumps(current),flush=True);last_logged=len(outcomes)
            if len(outcomes)-last_count>=config.get('report_interval',20) or time.monotonic()-last_report>=60:
                build(journal,config['reports_dir']);last_report=time.monotonic();last_count=len(outcomes)
        try:
            build(journal,config['reports_dir'])
            run_tests(journal,planned,config,client,judge_client,stop_event,progress)
            for recovery_pass in range(config.get('recovery_passes',3)):
                if stop_event.is_set():break
                outcomes={e['test_id']:e for e in journal.snapshot() if e['kind']=='test_result'}
                pending=[t for t in planned if t['test_id'] not in outcomes or outcomes[t['test_id']]['status']=='errored']
                if not pending:break
                journal.append('recovery_pass',number=recovery_pass+1,scheduled=len(pending))
                run_tests(journal,pending,config,client,judge_client,stop_event,progress,recover=True)
            if stop_event.is_set():journal.append('interrupted',reason='Graceful stop; in-flight responses and committed state retained')
        finally:
            metrics,path=build(journal,config['reports_dir']);print(json.dumps(metrics,indent=2));print(path)
        if args.smoke:
            reads=[e for e in journal.events if e['kind']=='tool_commit' and e['result']['status']=='read']
            finished=any(e['kind']=='target_done' for e in journal.events)
            if not reads or not finished:raise ValueError('Native tool roundtrip NOT verified; inspect recorded smoke evidence')
            print('Native tool request/result/final-answer roundtrip verified.')
        if any(status!='completed' and count for status,count in metrics['status_counts'].items()):
            raise SystemExit(2)

if __name__=='__main__':
    try:main()
    except (ValueError,FileNotFoundError) as e:raise SystemExit(str(e))
    except Exception as e:
        from jsonschema import ValidationError
        if isinstance(e,ValidationError):raise SystemExit('Invalid configuration at '+e.json_path+': '+e.message)
        raise
