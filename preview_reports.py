#!/usr/bin/env python3
"""Independent, streaming previews of saved failure CSVs; no model or runner imports."""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parent
HARD_LIMIT=4_999_999  # Strictly below 5 decimal MB, including header and UTF-8 BOM.


def encoded_row(values):
    out=io.StringIO(newline='')
    csv.writer(out).writerow(values)
    return out.getvalue().encode('utf-8')


def labels(row):
    result=set()
    for field in ('failure_types','category','source','execution_status'):
        value=row.get(field,'')
        try: parsed=json.loads(value)
        except (ValueError,TypeError):parsed=value
        values=parsed if isinstance(parsed,list) else [parsed]
        for item in values:
            if item not in ('',None):result.add(field+':'+str(item))
    return result


def identity(path):
    s=path.stat()
    return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)


def preview(source, *, rows=20, max_bytes=1_000_000, seed=6):
    source=Path(source).resolve()
    if rows<1 or not 1<=max_bytes<=HARD_LIMIT:
        raise ValueError('rows must be positive and max_bytes must be between 1 and 4,999,999')
    csv.field_size_limit(sys.maxsize)
    before=identity(source)
    candidates=[];digest=hashlib.sha256()
    # Keep only row size, labels and selection metadata in memory, never conversations.
    with source.open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.reader(stream)
        try:header=next(reader)
        except StopIteration:raise ValueError('Source CSV has no header')
        if len(set(header))!=len(header):raise ValueError('Duplicate CSV headers')
        prefix=b'\xef\xbb\xbf'+encoded_row(header)
        if len(prefix)>max_bytes:raise ValueError('Byte limit is too small even for the CSV header')
        digest.update(encoded_row(header))
        for index,values in enumerate(reader):
            if len(values)!=len(header):raise ValueError(f'Malformed CSV record {index+1}')
            payload=encoded_row(values);digest.update(payload)
            candidates.append({'index':index,'bytes':len(payload),'labels':labels(dict(zip(header,values))),
                               'tie':hashlib.sha256(f'{seed}:{index}'.encode()).hexdigest()})
    if identity(source)!=before:raise RuntimeError('Source changed during scan; retry after export finishes')
    total=len(candidates);bins=min(5,total,rows);selected=[];seen=set();remaining=max_bytes-len(prefix)
    for c in candidates:c['bin']=min(bins-1,c['index']*bins//total)
    buckets=[[c for c in candidates if c['bin']==b and c['bytes']<=max_bytes-len(prefix)] for b in range(bins)]
    # Round-robin across equally sized regions of the entire file. Within each
    # region prefer new failure/category/source/status labels, with seeded ties.
    for slot in range(min(rows,total)):
        bucket=buckets[slot%bins]
        future_regions=min(bins-1,rows-slot-1)
        allowance=remaining//(future_regions+1)
        options=[c for c in bucket if c['bytes']<=allowance]
        if not options:options=[c for c in bucket if c['bytes']<=remaining]
        if not options:continue
        best=min(options,key=lambda c:(-len(c['labels']-seen),c['tie']))
        bucket.remove(best);selected.append(best);seen.update(best['labels']);remaining-=best['bytes']
    # Fill unused slots from any region when a region is empty or oversized.
    selected_ids={c['index'] for c in selected}
    for _ in range(rows-len(selected)):
        options=[c for c in candidates if c['index'] not in selected_ids and c['bytes']<=remaining]
        if not options:break
        best=min(options,key=lambda c:(-len(c['labels']-seen),c['tie']))
        selected.append(best);selected_ids.add(best['index']);seen.update(best['labels']);remaining-=best['bytes']
    chosen={c['index'] for c in selected}
    output=source.with_name(source.stem+'.preview.csv')
    metadata=source.with_name(source.stem+'.preview.json')
    fd,temp=tempfile.mkstemp(prefix='.preview-',dir=source.parent)
    try:
        second_digest=hashlib.sha256()
        with os.fdopen(fd,'wb') as out,source.open(encoding='utf-8-sig',newline='') as stream:
            out.write(prefix);reader=csv.reader(stream);second_header=next(reader)
            second_digest.update(encoded_row(second_header))
            if second_header!=header:raise RuntimeError('Source header changed; retry')
            for index,values in enumerate(reader):
                payload=encoded_row(values);second_digest.update(payload)
                if index in chosen:out.write(payload)
            out.flush();os.fsync(out.fileno())
        if identity(source)!=before or second_digest.digest()!=digest.digest():
            raise RuntimeError('Source changed between passes; existing preview was left untouched')
        size=Path(temp).stat().st_size
        if size>max_bytes:raise RuntimeError('Preview exceeded byte budget')
        os.replace(temp,output)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    info={'source':str(source),'source_bytes':before[2],'source_rows':total,
          'source_csv_content_sha256':digest.hexdigest(),'preview':str(output),'preview_bytes':size,
          'max_bytes':max_bytes,'requested_rows':rows,'selected_rows':len(chosen),'seed':seed,
          'source_record_numbers':[i+1 for i in sorted(chosen)],
          'represented_regions':sorted({c['bin']+1 for c in selected}),'total_regions':bins,
          'represented_labels':sorted(seen),'available_label_count':len(set().union(*(c['labels'] for c in candidates))) if candidates else 0,
          'oversized_records':sum(c['bytes']>max_bytes-len(prefix) for c in candidates),
          'method':'Spread across equal record-count regions, preferring different failure types, categories, sources and statuses; deterministic seeded selection. Output remains in original row order.',
          'limitations':'Illustrative preview, not a statistically representative sample. Whole records only: oversized records are omitted, never truncated. Diversity and row count depend on the byte budget. Coverage refers to the failure CSV, not unexecuted or passing dataset cases.'}
    fd,temp=tempfile.mkstemp(prefix='.preview-info-',dir=source.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(info,stream,indent=2,ensure_ascii=False);stream.write('\n')
        os.replace(temp,metadata)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return info


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark',choices=['all','llm02','llm06','llm10'],default='all')
    parser.add_argument('--input',type=Path,help='preview one explicit CSV instead of the risk reports')
    parser.add_argument('--rows',type=int,default=20)
    parser.add_argument('--max-bytes',type=int,default=1_000_000)
    parser.add_argument('--seed',type=int,default=6)
    args=parser.parse_args()
    paths=[args.input] if args.input else [ROOT/'runs'/b/'failed_instances.csv' for b in (['llm02','llm06','llm10'] if args.benchmark=='all' else [args.benchmark])]
    for path in paths:
        info=preview(path,rows=args.rows,max_bytes=args.max_bytes,seed=args.seed)
        print(f"{info['preview']}: {info['selected_rows']} rows, {info['preview_bytes']:,} bytes, regions {info['represented_regions']}/{info['total_regions']}")


if __name__=='__main__':main()
