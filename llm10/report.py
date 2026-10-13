"""Private full-evidence CSV/JSONL and Markdown assessments from the durable journal."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile

from .files import write_json
from .metrics import metrics


def text_file(path,text):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,name=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def csv_file(path,rows,fields):
    out=io.StringIO(newline=''); w=csv.DictWriter(out,fieldnames=fields);w.writeheader()
    for row in rows:
        values={}
        for k in fields:
            v=row.get(k)
            if isinstance(v,(dict,list)):v=json.dumps(v,ensure_ascii=False)
            if isinstance(v,str) and (v.lstrip().startswith(('=','+','-','@')) or v.startswith(('\t','\n','\r'))):v="'"+v
            values[k]=v
        w.writerow(values)
    text_file(path,'\ufeff'+out.getvalue())


def write_reports(directory,reports,events,manifest,coverage,cfg,run_id):
    directory,reports=Path(directory),Path(reports)
    rows=[e['record'] for e in events if e['kind']=='attempt_finished']
    data=metrics(events,manifest);data.update(run_id=run_id,model=cfg['model'],coverage=coverage)
    analysis=data['assessment']
    csv_file(directory/'findings.csv',analysis['findings'],['finding_id','status','confirmed_vulnerability','observation','possible_impact','recommended_action','retest','evidence_attempt_ids'])
    csv_file(directory/'control_assessment.csv',analysis['controls'],['test_family','planned_calls','successful_calls','skipped_calls','unfinished_calls','attempts','disposition','rate_rejections','size_rejections','interpretation'])
    write_json(directory/'metrics.json',data)
    text_file(directory/'results.jsonl',''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    fields=['run_id','test_id','call_id','attempt_id','conversation_id','turn','dataset','source_sample_id','sample_id','task',
            'test_family','test_level','timestamp','model','mode','status','messages','content','reasoning','raw_response',
            'input_tokens','output_tokens','total_tokens','usage_status','requested_max_tokens','estimated_input_tokens',
            'latency','ttft_seconds','http_status','finish_reason','rate_limits','retry_count','error','retryable',
            'repetition','concurrency','in_flight_at_dispatch','estimated_cost','reserved_tokens','reserved_cost','transformation']
    csv_file(directory/'requests.csv',rows,fields)
    conversations=[]
    for r in rows:
        messages=[{**m,'channel':'request'} for m in r['messages']]
        # Blank final content is preserved, but annotated, not replaced with fake text.
        if r['status']=='SUCCESS':
            messages.append({'role':'assistant','content':r.get('content',''),'channel':'final_answer'})
            if r.get('reasoning'):messages.append({'role':'assistant','content':r['reasoning'],'channel':'returned_reasoning'})
        for index,m in enumerate(messages):
            conversations.append({**r,**m,'message_index':index,'content_json':json.dumps(m['content'],ensure_ascii=False),
                                  'content_status':'PRESENT' if m['content'] else 'EMPTY_FROM_PROVIDER',
                                  'usage_scope':'per API attempt, repeated on message rows; do not sum these rows'})
    csv_file(directory/'conversations.csv',conversations,['run_id','conversation_id','test_id','call_id','attempt_id','turn',
             'message_index','role','channel','content','content_json','content_status','input_tokens','output_tokens','latency','status','usage_scope'])
    group_fields=['test_family','test_level','dataset','task']
    for r in data['groups']:
        for key in r:
            if key not in group_fields:group_fields.append(key)
    csv_file(directory/'summary.csv',data['groups'],group_fields)
    decisions=[e for e in events if e['kind']=='call_finished']
    csv_file(directory/'call_status.csv',decisions,['call_id','family','level','status','reason'])
    from failure_reports import write_failures, llm10_rows
    write_failures(directory, llm10_rows(run_id,events,manifest,analysis['findings']))
    from reporting import publish
    publish('llm10', run_id, cfg['model'], data, coverage, directory, reports, configuration=cfg)
    return data


def rebuild(directory):
    directory=Path(directory).resolve()
    from .storage import Journal
    cfg=json.loads((directory/'config.json').read_text())
    manifest=json.loads((directory/'manifest.json').read_text())
    coverage=json.loads((directory/'coverage.json').read_text())
    reports=Path(cfg['paths']['reports'])/directory.name
    with Journal(directory) as j:write_reports(directory,reports,j.events,manifest,coverage,cfg,directory.name)
    print(f'Report: {reports / "report.md"}')


def snapshot(directory):
    """Read a bounded journal prefix without locking or overwriting an active run."""
    directory=Path(directory).resolve()
    events=[]
    with (directory/'events.jsonl').open('rb') as stream:
        remaining=os.fstat(stream.fileno()).st_size
        while remaining:
            line=stream.readline(remaining);remaining-=len(line)
            if not line.endswith(b'\n'):break
            event=json.loads(line)
            if event.get('seq')!=len(events):raise ValueError('Invalid journal sequence')
            events.append(event)
    cfg=json.loads((directory/'config.json').read_text())
    manifest=json.loads((directory/'manifest.json').read_text())
    coverage=json.loads((directory/'coverage.json').read_text())
    output=directory/'analysis'
    reports=Path(cfg['paths']['reports'])/directory.name/'analysis'
    write_reports(output,reports,events,manifest,coverage,cfg,directory.name)
    print(f'Analysis snapshot through journal sequence {len(events)-1}: {reports / "report.md"}')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Generate an evidence-based, read-only analysis snapshot; no model calls.')
    parser.add_argument('run_directory',type=Path)
    snapshot(parser.parse_args().run_directory)
