import csv
import hashlib
import json
from pathlib import Path
import tempfile
import pytest
from preview_reports import preview,HARD_LIMIT


def write(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['instance_id','failure_types','category','source','execution_status','conversation'])
        writer.writeheader();writer.writerows(rows)


def records(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def test_small_diverse_full_records_deterministic_and_read_only(tmp_path):
    source=tmp_path/'failed_instances.csv'
    original=[dict(instance_id=str(i),failure_types=json.dumps(['security' if i%2 else 'execution']),
                   category=f'category-{i%3}',source=f'dataset-{i//20}',execution_status='failed',
                   conversation='Full Unicode हिन्दी, "quoted"\nmultiline\n'+str(i)) for i in range(100)]
    write(source,original);before=source.read_bytes();stamp=source.stat().st_mtime_ns
    info=preview(source,rows=15,max_bytes=20000)
    assert info['represented_regions']==[1,2,3,4,5]
    selected=records(Path(info['preview']))
    assert len(selected)==15
    assert {r['source'] for r in selected}=={f'dataset-{i}' for i in range(5)}
    assert {r['category'] for r in selected}=={f'category-{i}' for i in range(3)}
    for row in selected:assert row==original[int(row['instance_id'])]
    output=Path(info['preview']).read_bytes();preview(source,rows=15,max_bytes=20000)
    assert Path(info['preview']).read_bytes()==output
    assert source.read_bytes()==before and source.stat().st_mtime_ns==stamp
    assert Path(info['preview']).stat().st_mode & 0o777==0o600


def test_budget_includes_bom_header_unicode_and_oversized_records(tmp_path):
    source=tmp_path/'failed_instances.csv'
    write(source,[dict(instance_id=str(i),failure_types='[]',category='c',source='s',execution_status='failed',conversation='界'*(10000 if i==3 else 100)) for i in range(20)])
    info=preview(source,rows=20,max_bytes=2000)
    assert Path(info['preview']).stat().st_size<=2000
    assert info['oversized_records']==1
    assert all(r['instance_id']!='3' for r in records(Path(info['preview'])))
    with pytest.raises(ValueError):preview(source,max_bytes=5_000_000)
    with pytest.raises(ValueError):preview(source,max_bytes=1)


def test_header_only_source(tmp_path):
    source=tmp_path/'failed_instances.csv';write(source,[])
    info=preview(source)
    assert info['selected_rows']==0 and records(Path(info['preview']))==[]
