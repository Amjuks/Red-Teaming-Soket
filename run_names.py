"""Readable labels and a local run index, separate from immutable run identity."""
import html
import hashlib
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
    """Create real landing pages: symlinked HTML would break relative downloads."""
    root, report, source = Path(root).resolve(), Path(report).resolve(), Path(source).resolve()
    doc = json.loads(report.with_name('report.json').read_text())
    name = doc['run']['name']
    # The catalog is derived only from validated names created by our formatter.
    expected = run_name(doc['benchmark']['id'], doc['run']['model'], doc['run']['id'],
                        doc['progress']['planned'], doc['progress']['unit'])
    if name != expected:
        raise ValueError('Invalid readable run name')
    directory = root/name
    if (directory/'run.json').exists():
        previous = json.loads((directory/'run.json').read_text())
        if previous['run_id'] != doc['run']['id']:
            # Preserve both runs even if their short identity prefixes collide.
            directory = root/(name + '-' + hashlib.sha256(doc['run']['id'].encode()).hexdigest()[:12])
    directory.mkdir(parents=True, exist_ok=True)
    entry = dict(name=directory.name, run_id=doc['run']['id'], benchmark=doc['benchmark']['id'],
                 report=str(report), source_directory=str(source), progress=doc['progress'])
    atomic_text(directory/'run.json', json.dumps(entry, indent=2)+'\n')
    esc = lambda value: html.escape(str(value), quote=True)
    report_link = esc(os.path.relpath(report, directory))
    source_link = esc(os.path.relpath(source, directory)) + '/'
    atomic_text(directory/'index.html', f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{esc(directory.name)}</title>'
                f'<h1>{esc(directory.name)}</h1><p><a href="{report_link}">Open report</a></p>'
                f'<p><a href="{source_link}">Original run evidence</a></p><p>Run ID: {esc(doc["run"]["id"])}</p>'
                '<p>This is a saved report snapshot. Run export_reports.py again to refresh.</p></html>')
    entries = [json.loads(path.read_text()) for path in sorted(root.glob('*/run.json'))]
    rows = ''.join(f'<tr><td><a href="{esc(e["name"])}/index.html">{esc(e["name"])}</a></td>'
                   f'<td>{e["progress"]["completed"]}</td><td>{e["progress"]["errored"]}</td>'
                   f'<td>{e["progress"]["pending"]}</td></tr>' for e in entries)
    atomic_text(root/'index.html', '<!doctype html><html lang="en"><meta charset="utf-8"><title>OWASP runs</title>'
                '<style>body{font:16px/1.6 system-ui;margin:32px}td,th{text-align:left;padding:10px}</style>'
                '<h1>OWASP benchmark runs</h1><p>Saved snapshots; refresh with python3 export_reports.py.</p>'
                '<table><tr><th>Run</th><th>Completed</th><th>Errored</th><th>Pending</th></tr>'+rows+'</table></html>')
    return directory/'index.html'
