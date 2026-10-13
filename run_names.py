"""Readable labels and a local run index, separate from immutable run identity."""
import json
import os
from pathlib import Path
import re
from reporting import atomic_text


def run_name(benchmark, model, run_id, planned, unit):
    slug = re.sub(r'[^a-z0-9]+', '-', str(model.get('model', 'model')).lower()).strip('-')[:64] or 'model'
    mode = model.get('mode')
    suffix = '-mock' if mode == 'mock' else ''
    count_unit = 'calls' if unit == 'workload_call' else 'tests'
    identity = re.sub(r'[^a-zA-Z0-9-]', '-', str(run_id))[:8] or 'run'
    return f'{benchmark}-{slug}{suffix}-{planned}-{count_unit}-{identity}'


def register(root, report, source):
    """Publish the complete latest assessment under a stable risk directory."""
    from reporting import overview
    root, report, source = Path(root).resolve(), Path(report).resolve(), Path(source).resolve()
    doc = json.loads(report.with_name('report.json').read_text())
    benchmark = doc['benchmark']['id']
    if benchmark not in ('llm02', 'llm06', 'llm10'):
        raise ValueError('Unknown benchmark')
    expected = run_name(benchmark, doc['run']['model'], doc['run']['id'], doc['progress']['planned'], doc['progress']['unit'])
    if doc['run']['name'] != expected:
        raise ValueError('Invalid readable run name')
    directory = root/benchmark
    directory.mkdir(parents=True, exist_ok=True)
    for artifact in doc['artifacts']:
        artifact['path'] = os.path.relpath((report.parent/artifact['path']).resolve(), directory)
    # Snapshots expose all original artifacts without copying or modifying journals.
    for name in ('events.jsonl', 'config.json', 'cases.json', 'manifest.json', 'coverage.json'):
        path=source/name
        if path.is_file() and not any(a['name']==name for a in doc['artifacts']):
            doc['artifacts'].append(dict(name=name,path=os.path.relpath(path,directory),media_type='application/x-ndjson' if name.endswith('.jsonl') else 'application/json',sensitivity='private'))
    # Keep the requested failure CSV next to the actual risk report.
    import shutil
    for artifact in doc['artifacts']:
        if artifact['name']=='failed_instances.csv':
            source_csv=(directory/artifact['path']).resolve()
            if source_csv != directory/'failed_instances.csv':
                import tempfile
                fd,temporary=tempfile.mkstemp(prefix='.failures-',dir=directory)
                os.close(fd)
                try:
                    shutil.copyfile(source_csv,temporary)
                    os.replace(temporary,directory/'failed_instances.csv')
                finally:
                    if os.path.exists(temporary):os.unlink(temporary)
            artifact['path']='failed_instances.csv'
    atomic_text(directory/'report.json',json.dumps(doc,indent=2,ensure_ascii=False)+'\n')
    atomic_text(directory/'report.md',overview(doc))
    atomic_text(directory/'run.json', json.dumps(dict(name=expected,run_id=doc['run']['id'],benchmark=benchmark,
                source_directory=str(source),report=str(directory/'report.md'),progress=doc['progress']),indent=2)+'\n')
    from reporting import table
    entries=[json.loads(p.read_text()) for p in sorted(root.glob('llm*/run.json'))]
    rows=[[e['benchmark'],e['name'],e['progress']['completed'],e['progress']['errored'],e['progress']['skipped'],e['progress']['pending']] for e in entries]
    atomic_text(root/'README.md','# Latest benchmark assessments\n\n'+table(['Risk','Run','Completed','Errored','Skipped','Pending'],rows)+
                '\nEach risk has a complete report.md and matching report.json, with the same schema. Refresh with `python3 export_reports.py`.\n\n'+
                '\n'.join(f"- [{e['benchmark'].upper()} assessment]({e['benchmark']}/report.md)" for e in entries)+'\n')
    return directory/'report.md'
