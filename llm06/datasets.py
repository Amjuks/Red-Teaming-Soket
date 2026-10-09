"""Pinned downloads and explicit multi-domain scenario adaptation; no upstream execution."""
import copy
import hashlib
import json
import random
import urllib.request
from collections import Counter
import pyarrow.parquet as parquet
from common import ROOT, atomic_json, identity
from tools import REGISTRY

ADAPTER='asb-declarative-v3'

def ensure_catalog(download):
    from catalog import WHEEL,SHA256
    directory=ROOT/'data/sources/asb-envs';directory.mkdir(parents=True,exist_ok=True)
    path=directory/WHEEL
    if not path.exists():
        if not download:raise ValueError('Environment catalog missing; run --prepare')
        url='https://files.pythonhosted.org/packages/eb/e7/756652f3aab9f7b8486476dd03f9a92114a0f878f00d6e6cab28eaa7ce1f/agent_safety_bench_envs-0.1.0-py3-none-any.whl'
        with urllib.request.urlopen(url,timeout=60) as response:data=response.read()
        if hashlib.sha256(data).hexdigest()!=SHA256:raise ValueError('Downloaded catalog hash mismatch')
        tmp=path.with_suffix('.download');tmp.write_bytes(data);tmp.replace(path)
    from catalog import Catalog
    catalog=Catalog()
    for name in catalog.zip.namelist():
        if name.endswith(('/LICENSE','/NOTICE')):(directory/name.rsplit('/',1)[-1]).write_bytes(catalog.zip.read(name))
    return catalog


def prepare(config, download=True):
    rev=config['revision']; directory=ROOT/'data'/'sources'/'agent-safety-bench'/rev
    directory.mkdir(parents=True,exist_ok=True)
    files=['README.md','data/train-00000-of-00001.parquet','data/augmented-00000-of-00001.parquet']
    hashes={}
    for name in files:
        p=directory/name
        if not p.exists():
            if not download: raise ValueError('dataset missing; run --prepare first')
            p.parent.mkdir(parents=True,exist_ok=True)
            request=urllib.request.Request(f'https://huggingface.co/datasets/aradhye/agent-safety-bench/resolve/{rev}/{name}')
            with urllib.request.urlopen(request,timeout=60) as r: data=r.read()
            tmp=p.with_suffix('.download'); tmp.write_bytes(data); tmp.replace(p)
        hashes[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    catalog=ensure_catalog(download)
    from catalog_adapter import adapt_catalog
    candidates=[]; excluded=[]; duplicates=[]; seen=set(); counts={}
    for split,file in [('core',files[1]),('augmented',files[2])]:
        rows=parquet.read_table(directory/file).to_pylist(); counts[split]=len(rows)
        for index,row in enumerate(rows):
            sid=f'{split}:{row.get("id",index)}'
            try:
                scenario=adapt_catalog(row,rev,split,catalog,index)
            except (ValueError,KeyError,TypeError,SyntaxError) as error:
                if split=='core':
                    try:scenario=adapt(row,rev,split)
                    except (ValueError,KeyError,TypeError):
                        excluded.append({'sample_id':sid,'reason':str(error)});continue
                else:
                    excluded.append({'sample_id':sid,'reason':str(error)});continue
            from audit import audit
            preflight=audit([scenario])
            if preflight['issues']:
                excluded.append({'sample_id':sid,'reason':'preflight read/schema check failed','details':preflight['issues']});continue
            fingerprint=identity([scenario['task'],scenario['initial_state'],scenario['tools']])
            if fingerprint in seen: duplicates.append(sid);continue
            seen.add(fingerprint); candidates.append(scenario)
    all_candidates=candidates
    candidates=[s for s in candidates if s['source']['sample_id'].split(':')[0] in config.get('splits',['core','augmented'])]
    selected=select_scenarios(candidates,config['sample_limit'],config['seed'],config.get('domains'),config.get('categories'),config.get('unique_tasks',False))
    manifest={'dataset':'aradhye/agent-safety-bench','revision':rev,'adapter':ADAPTER,
        'license':'apache-2.0 (dataset card; retained README.md)', 'hashes':hashes,'source_counts':counts,
        'usable':len(all_candidates),'eligible_after_split_filter':len(candidates),
        'usable_by_split':dict(Counter(s['source']['sample_id'].split(':')[0] for s in all_candidates)),
        'unique_task_texts':len({s['task'] for s in all_candidates}),
        'usable_by_mode':dict(Counter('approval_only' if all(t['approval_required'] for t in s['tools']) else 'has_read_tools' for s in all_candidates)),
        'environment_catalog':{'version':'0.1.0','sha256':__import__('catalog').SHA256},
        'selected':len(selected),'selected_unique_task_texts':len({s['task'] for s in selected}),'selected_by_split':dict(Counter(s['source']['sample_id'].split(':')[0] for s in selected)),'not_sampled':len(candidates)-len(selected),
        'excluded':excluded,'exclusion_counts':dict(Counter(x['reason'] for x in excluded)),
        'duplicates':duplicates,'sampling':'seeded balanced domain/risk selection',
        'usable_by_domain':dict(Counter(d for s in all_candidates for d in s['domains'])),
        'selected_by_domain':dict(Counter(d for s in selected for d in s['domains'])),
        'usable_by_category':dict(Counter(c for s in all_candidates for c in s['category'])),
        'usable_source_environments':len({e for s in all_candidates for e in s.get('source_environments',[])}),
        'selected_by_mode':dict(Counter('approval_only' if all(t['approval_required'] for t in s['tools']) else 'has_read_tools' for s in selected)),
        'selected_by_category':dict(Counter(c for s in selected for c in s['category'])),'selected_ids':[s['source']['sample_id'] for s in selected],
        'additional_sources':'ToolEmu, AgentDojo, AgentHarm and R-Judge public pages verified; adapters/calibration not implemented'}
    atomic_json(ROOT/'data'/'coverage.json',manifest)
    atomic_json(ROOT/'data'/'scenarios.json',selected)
    return selected,manifest

def adapt(row,revision,split):
    from source_tools import ENVIRONMENTS, definitions, initial_state
    envs=json.loads(row['environments'])
    if not envs or any(e.get('name') not in ENVIRONMENTS for e in envs):
        raise ValueError('unsupported environment combination')
    raw_tools={}
    for env in envs:
        for raw in env.get('tool_desc',[]):
            name=raw['name']
            if name in raw_tools and raw_tools[name]!=raw:raise ValueError('conflicting tool schemas: '+name)
            raw_tools[name]=raw
    if not raw_tools:raise ValueError('missing tool schemas')
    tools=definitions(raw_tools.values())
    state,notes=initial_state(envs)
    domains=sorted({tool['family'] for tool in tools})
    source={'dataset':'aradhye/agent-safety-bench','revision':revision,'sample_id':f'{split}:{row["id"]}',
            'adapter':ADAPTER,'labels':{k:row.get(k) for k in ('risks','failure_modes','fulfillable','gt_label','gt_tools')},
            'transformations':['Supplied resources assigned to simulated-user under explicit local scope; source ownership retained as data.',
             'Only source-provided tool schemas are exposed; missing schemas are never invented.',
             'Search uses deterministic lexical matching, not an upstream relevance model.',
             'URLs/paths are inert JSON identifiers. Missing source collections return source_data_unavailable.',
             'Local approval policy requires simulator grant for every write; gt_tools is not a completion oracle.']+notes}
    scenario={'source':source,'task':row['instruction'],'category':row.get('risks') or ['Unlabeled'],
        'domains':domains,'adversarial':None,'initial_state':state,'tools':tools,
        'policy':{'actor':'simulated-user','permissions':sorted({d['permission'] for d in tools}),
                  'resources':{key:list(value) for key,value in state.items()},'action_budget':12,
                  'forbidden_tools':[],'approval':'deny'},'expected':None,'original':row}
    scenario['scenario_id']=identity(scenario)
    return scenario


def select_scenarios(candidates,limit,seed,domains=None,categories=None,unique_tasks=False):
    """Seeded greedy stratification across domains and overlapping source risk labels."""
    pool=[s for s in candidates if (not domains or set(s['domains']) & set(domains))
          and (not categories or set(s['category']) & set(categories))]
    random.Random(seed).shuffle(pool)
    counts=Counter();selected=[]
    def labels(s):return [('domain',d) for d in s['domains']]+[('risk',c) for c in s['category']]
    while pool and len(selected)<limit:
        best=max(range(len(pool)),key=lambda i:sum(1/(1+counts[label]) for label in labels(pool[i]))/len(labels(pool[i])))
        scenario=pool.pop(best);selected.append(scenario);counts.update(labels(scenario))
        if unique_tasks:pool=[s for s in pool if s['task']!=scenario['task']]
    return selected

def variant(scenario,name,budget):
    s=copy.deepcopy(scenario);s['variant_id']=name;s['policy']['action_budget']=budget
    if name=='broad':
        names={d['name'] for d in s['tools']}
        # Extra capabilities are explicit local probes, never extra authorization.
        mapping={'healthcare':['users','calendar'],'security':['users','files'],
                 'infrastructure':['database','files'],'commerce':['database','finance'],
                 'travel':['calendar','finance'],'workplace':['users','calendar'],
                 'communications':['email'],'software':['files','database'],
                 'specialized_operations':['database']}
        families=set(s.get('domains',['files']))
        for domain in s.get('domains',[]):families.update(mapping.get(domain,[]))
        s['tools'] += [copy.deepcopy(d) for n,d in REGISTRY.items() if d['family'] in families and n not in names]
    # Deliberately preserve authorization. Advertised extra tools do not grant permission.
    return s
