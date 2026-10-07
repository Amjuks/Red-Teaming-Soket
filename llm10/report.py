"""Private full-evidence CSV/JSONL and escaped HTML from the durable journal."""
import csv
import html
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
    e=lambda x:html.escape(str(x))
    cards=''.join(f'<p><b>{e(k)}:</b> {e(data[k])}</p>' for k in ('planned_calls','terminal_calls','successful_calls','skipped_calls','unfinished_calls'))
    summaries=''.join('<tr>'+''.join('<td>'+e(r.get(k,''))+'</td>' for k in group_fields)+'</tr>' for r in data['groups'])
    # Representative per family + errors and 429s, not a claim to contain every row.
    representatives={}
    for r in rows:
        representatives.setdefault((r['test_family'],r['status'],r.get('http_status')),r)
    evidence=''.join('<details><summary>'+e(f'{r["test_family"]} / {r["status"]} / {r["attempt_id"]}')+'</summary><pre>'+e(json.dumps(r,ensure_ascii=False,indent=2))+'</pre></details>' for r in representatives.values())
    links=' '.join(f'<a href="{e(os.path.relpath(directory/name,reports))}">{name}</a>' for name in ['findings.csv','control_assessment.csv','requests.csv','conversations.csv','summary.csv','call_status.csv','results.jsonl','metrics.json'])
    findings_html=''.join('<section><h3>'+e(f['finding_id']+' — '+f['status'])+'</h3>'+''.join('<p><b>'+e(label)+':</b> '+e(f[key])+'</p>' for label,key in [('Observed','observation'),('Possible impact','possible_impact'),('Action','recommended_action'),('Retest','retest'),('Evidence attempt IDs','evidence_attempt_ids')])+'</section>' for f in analysis['findings'])
    page=f'''<!doctype html><meta charset="utf-8"><title>LLM10 {e(run_id)}</title>
<style>body{{font:15px/1.5 system-ui;margin:30px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:6px}}.scroll{{overflow:auto}}</style>
<h1>OWASP LLM10:2025 — Unbounded Consumption</h1><p>{e(cfg['model']['mode'].upper())} · {e(cfg['model']['model'])} · {e(run_id)}</p>
<p>Private, unredacted benchmark evidence. Keep these files local. This report measures the tested range only, never unlimited capacity.</p>
{cards}<p>{links}</p><h2>Security interpretation</h2><p>{e(analysis['verdict'])}</p>
<p>Inference requires a repeatable workload → measured consumption/degradation → violation of a declared server policy or service objective. A large token count alone is not a vulnerability. Findings below distinguish observations from unproven causes; no OWASP severity score is invented.</p>
{findings_html}<h3>Assessment limitations</h3><ul>{''.join('<li>'+e(x)+'</li>' for x in analysis['limitations'])}</ul>
<p>See control_assessment.csv for successful, skipped and unfinished coverage per family. Evidence IDs join to requests.csv and conversations.csv.</p>
<h2>Overall consumption and latency</h2><pre>{e(json.dumps(data['overall'],indent=2))}</pre>
<h2>Methodology and caveats</h2><pre>{e(json.dumps(data['methodology'],indent=2))}</pre>
<p>TTFT is unavailable through the current Loop completion API. Final answers and returned reasoning are separate. Missing usage is not zero. Client safety skips do not prove endpoint protection. For input/context, a 400 alone is inconclusive; 413 records a size rejection. Output length finish reason demonstrates the requested cap only.</p>
<h2>Coverage</h2><pre>{e(json.dumps(coverage,indent=2))}</pre>
<h2>Baseline and all workload families</h2><div class="scroll"><table><tr>{''.join('<th>'+e(k)+'</th>' for k in group_fields)}</tr>{summaries}</table></div>
<h2>Client safety stops (not server controls)</h2><pre>{e(json.dumps(data['branch_stops'],indent=2))}</pre>
<p>Observed high latency/token amplification warrants review against matched baselines. Failure-driven stops are inconclusive about endpoint limits unless explicit rejection evidence is present. Same endpoint activity from other users can confound latency/rate observations.</p>
<h2>Representative full conversations and responses</h2>{evidence}
<h2>Mitigations</h2><p>Enforce input/output/context caps server-side, per-tenant request/token/cost budgets, bounded concurrency, deadlines and backpressure. Monitor unusual repetition and expensive workloads; enforce admission control before generation and verify policies with authorized retests.</p>'''
    text_file(reports/'report.html',page)
    return data


def rebuild(directory):
    directory=Path(directory).resolve()
    from .storage import Journal
    cfg=json.loads((directory/'config.json').read_text())
    manifest=json.loads((directory/'manifest.json').read_text())
    coverage=json.loads((directory/'coverage.json').read_text())
    reports=Path(cfg['paths']['reports'])/directory.name
    with Journal(directory) as j:write_reports(directory,reports,j.events,manifest,coverage,cfg,directory.name)
    print(f'Report: {reports / "report.html"}')


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
    print(f'Analysis snapshot through journal sequence {len(events)-1}: {reports / "report.html"}')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Generate an evidence-based, read-only analysis snapshot; no model calls.')
    parser.add_argument('run_directory',type=Path)
    snapshot(parser.parse_args().run_directory)
