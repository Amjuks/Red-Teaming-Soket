"""Explicit latest-only retention for generated benchmark artifacts."""
import fcntl
import json
from pathlib import Path
import shutil
from contextlib import ExitStack
from reporting import atomic_text


def remove(path):
    if path.is_symlink() or path.is_file():path.unlink()
    elif path.is_dir():shutil.rmtree(path)


def prune_history(base, keep, report):
    base,keep,report=Path(base).resolve(),Path(keep).resolve(),Path(report).resolve()
    if not keep.is_relative_to(base/'results') or not (keep/'events.jsonl').is_file():
        raise ValueError('Retention requires a saved run under the benchmark results directory')
    doc=json.loads(report.with_name('report.json').read_text())
    if doc['run']['id'] != keep.name:raise ValueError('Retained report does not match evidence run')
    # Lock every journal (including the retained run) for the whole operation.
    # Refuse all deletion if a writer is active; do not partially prune a live run.
    with ExitStack() as stack:
        for results in base.glob('results*'):
            if not results.is_dir() or results.is_symlink():continue
            for journal in results.rglob('events.jsonl'):
                lock=stack.enter_context((journal.parent/('writer.lock' if base.name=='llm06' else '.lock')).open('a+'))
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        def clean(directory):
            for child in list(directory.iterdir()):
                if child.is_symlink():
                    if child.resolve()!=keep:child.unlink()
                elif child==keep:continue
                elif child.is_dir() and keep.is_relative_to(child):clean(child)
                else:remove(child)
        for result_root in base.glob('results*'):
            if result_root.is_dir() and not result_root.is_symlink():clean(result_root)
        for name in ('csv-snapshots','report-snapshots'):
            remove(keep/name)
        for pattern in ('*.html','*.htm','*.stamp'):
            for path in keep.rglob(pattern):remove(path)
        # Reports are projections; the canonical latest Markdown is outside these roots.
        for root in base.glob('reports*'):
            if root.is_dir():remove(root)
        pointer={'run_id':keep.name,'directory':str(keep),'report':str(report)}
        for parent in {base/'results',keep.parent}:
            parent.mkdir(exist_ok=True,parents=True)
            atomic_text(parent/'latest.json',json.dumps(pointer,indent=2)+'\n')
            link=parent/'latest'
            if not link.exists() and not link.is_symlink():link.symlink_to(keep,target_is_directory=True)
        if base.name=='llm06':atomic_text(base/'results/latest-benchmark.json',json.dumps(pointer)+'\n')
