#!/usr/bin/env python3
"""LLM06 entry point. Full benchmark execution is an explicit user launch."""
import argparse
import json
import signal
from common import ROOT, atomic_json, identity, load_config, local_path
from client import Client
from datasets import prepare,variant
from journal import Journal
from report import build
from runner import execute

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='config.yaml')
    p.add_argument('--sample-limit',type=int,help='Number of unique source scenarios before variants')
    p.add_argument('--domains',nargs='+',help='Include scenarios matching any of these domains')
    p.add_argument('--categories',nargs='+',help='Include exact source risk labels (quote each label)')
    group=p.add_mutually_exclusive_group()
    group.add_argument('--validate-config',action='store_true')
    group.add_argument('--prepare',action='store_true')
    group.add_argument('--offline-demo',action='store_true')
    group.add_argument('--smoke',action='store_true',help='One native read-tool roundtrip through configured target')
    group.add_argument('--report-run',metavar='RUN_DIRECTORY')
    group.add_argument('--status',nargs='?',const='latest',metavar='RUN_DIRECTORY')
    group.add_argument('--background',action='store_true',help='Start a detached benchmark and return immediately')
    group.add_argument('--stop',nargs='?',const='latest',metavar='RUN_DIRECTORY')
    args=p.parse_args();config=load_config(args.config)
    for key in ('sample_limit','domains','categories'):
        if getattr(args,key) is not None:config[key]=getattr(args,key)
    from common import CONFIG
    from jsonschema import Draft202012Validator
    Draft202012Validator(CONFIG).validate(config)
    for key in ('status','report_run','stop'):
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
    if args.prepare:
        _,m=prepare(config);print(json.dumps({k:m[k] for k in ('source_counts','usable','selected','selected_by_domain','selected_by_category','exclusion_counts')},indent=2));return
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
    run_id=identity([config,planned]);directory=local_path(config['results_dir'])/run_id
    if args.background:
        from background import launch
        # Publish the selected run before starting; child opens its journal normally.
        atomic_json(local_path(config['results_dir'])/'latest-benchmark.json',{'run_id':run_id,'directory':str(directory)})
        import sys
        launch(directory,[arg for arg in sys.argv[1:] if arg!='--background']);return
    with Journal(directory) as journal:
        if not journal.events:journal.append('run_start',run_id=run_id,config=config,coverage=coverage,tests=planned)
        atomic_json(local_path(config['results_dir'])/'latest.json',{'run_id':run_id,'directory':str(directory)})
        if coverage.get('dataset')=='aradhye/agent-safety-bench':
            atomic_json(local_path(config['results_dir'])/'latest-benchmark.json',{'run_id':run_id,'directory':str(directory)})
        judge_client=Client(config['judge']) if config['judge'] else None
        def stop(signum,frame):raise KeyboardInterrupt
        signal.signal(signal.SIGTERM,stop)
        try:
            for index,test in enumerate(planned,1):
                execute(journal,test['test_id'],test['scenario'],config,client,judge_client)
                progress={'run_id':run_id,'processed':index,'planned':len(planned),'test_id':test['test_id']}
                atomic_json(directory/'progress.json',progress)
                print(json.dumps(progress),flush=True)
                if index % 10==0:build(journal,config['reports_dir'])
        except KeyboardInterrupt:
            journal.append('interrupted',reason='User/process interruption; resume with identical configuration')
            print('Interrupted safely; unresolved inference is recorded on resume.')
        finally:
            metrics,path=build(journal,config['reports_dir']);print(json.dumps(metrics,indent=2));print(path)
        if args.smoke:
            reads=[e for e in journal.events if e['kind']=='tool_commit' and e['result']['status']=='read']
            finished=any(e['kind']=='target_done' for e in journal.events)
            if not reads or not finished:raise ValueError('Native tool roundtrip NOT verified; inspect recorded smoke evidence')
            print('Native tool request/result/final-answer roundtrip verified.')

if __name__=='__main__':
    try:main()
    except (ValueError,FileNotFoundError) as e:raise SystemExit(str(e))
    except Exception as e:
        from jsonschema import ValidationError
        if isinstance(e,ValidationError):raise SystemExit('Invalid configuration at '+e.json_path+': '+e.message)
        raise
