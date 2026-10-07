"""Bounded execution with durable attempts, replay and branch circuit breakers."""
import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
from pathlib import Path
import signal
import statistics
import time

from . import client
from .files import digest, write_json, publish_latest
from .storage import Journal
from .tests import estimated_tokens


def usage(response):
    u = response.get('usage') or {}
    def val(*keys):
        for k in keys:
            n = u.get(k)
            if isinstance(n,int) and not isinstance(n,bool) and n>=0: return n
        return None
    inp,out = val('input','prompt_tokens','input_tokens'),val('output','completion_tokens','output_tokens')
    # Loop initializes absent usage to zeros; empty zero totals are not measured usage.
    if inp == 0 and out == 0: inp=out=None
    return inp,out,None if inp is None or out is None else inp+out


def cost(cfg, inp, out):
    p=cfg['pricing']
    if inp is None or out is None or p['input_per_million'] is None: return None
    return (inp*p['input_per_million'] + out*p['output_per_million'])/1_000_000


def retry_delay(value, fallback):
    try:
        n=float(value)
        return max(fallback,n) if math.isfinite(n) else float('inf')
    except (TypeError,ValueError):
        try: return max(fallback,(parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds())
        except (TypeError,ValueError,OverflowError): return fallback


class Executor:
    def __init__(self,cfg,manifest,journal,run_id,transport=client.complete):
        self.cfg,self.manifest,self.j,self.run_id,self.transport=cfg,manifest,journal,run_id,transport
        self.stop=asyncio.Event()
        self.active=0
        self.done=journal.completed_calls()
        self.finishes=journal.attempts()
        self.starts=defaultdict(list)
        self.branches={}
        self.failures=defaultdict(int); self.rates=defaultdict(int)
        self.baseline=[]
        self.reserved_tokens=0; self.reserved_cost=0; self.request_count=0
        for e in journal.events:
            if e['kind']=='attempt_started':
                self.starts[e['call_id']].append(e); self.request_count+=1
                self.reserved_tokens+=e['reserved_tokens']; self.reserved_cost+=e.get('reserved_cost') or 0
            elif e['kind']=='branch_stopped': self.branches[e['branch']]=e['reason']
            elif e['kind']=='attempt_finished': self.observe(e['record'],persist=False)
        persisted={e['branch'] for e in journal.events if e['kind']=='branch_stopped'}
        for branch,reason in self.branches.items():
            if branch not in persisted:
                self.j.append('branch_stopped',branch=branch,reason=reason)
        # Persist ambiguous outcomes; never silently repeat completed remote work.
        for start in journal.unresolved():
            record={**start['record'],'status':'UNCERTAIN','error':'process stopped before durable outcome',
                    'content':'','reasoning':'','input_tokens':None,'output_tokens':None,'total_tokens':None,
                    'latency':None,'http_status':None,'retryable':cfg['execution']['uncertain_policy']=='retry'}
            self.finish_attempt(start,record)

    def branch_stop(self,branch,reason):
        if branch not in self.branches:
            self.branches[branch]=reason
            self.j.append('branch_stopped',branch=branch,reason=reason)

    def observe(self,r,persist=True):
        family=r['test_family']
        bad=r['status']!='SUCCESS'
        self.failures[family]=self.failures[family]+1 if bad else 0
        self.rates[family]=self.rates[family]+1 if r.get('http_status')==429 else 0
        if family=='baseline' and not bad and r.get('latency') is not None: self.baseline.append(r['latency'])
        reason=None
        s=self.cfg['safety']
        if self.failures[family]>=s['consecutive_failures']: reason='repeated_failures'
        if self.rates[family]>=s['consecutive_rate_limits']: reason='strong_rate_limiting'
        if family!='baseline' and self.baseline and r.get('latency') is not None:
            if r['latency']>max(s['latency_min_seconds'],statistics.median(self.baseline)*s['latency_multiplier']):
                reason='severe_latency_degradation'
        if r.get('http_status')==413: reason='endpoint_input_limit'
        if persist and reason: self.branch_stop(family,reason)
        elif reason: self.branches.setdefault(family,reason)

    def finish_attempt(self,start,r):
        event=self.j.append('attempt_finished',attempt_id=start['attempt_id'],call_id=start['call_id'],record=r)
        self.finishes[start['attempt_id']]=event
        self.observe(r)
        return r

    def finish_call(self,call,status,record=None,reason=None):
        e=self.j.append('call_finished',call_id=call['call_id'],status=status,record=record,reason=reason,
                        family=call['family'],level=call['level'])
        self.done[call['call_id']]=e
        print(f'[{len(self.done)}/{len(self.manifest["calls"])}] {call["family"]} level={call["level"]} {status}',flush=True)

    def messages(self,call):
        result=[]
        if call['family']=='context_growth':
            previous=[c for c in self.manifest['calls'] if c['conversation_id']==call['conversation_id'] and c['turn']<call['turn']]
            for c in sorted(previous,key=lambda c:c['turn']):
                e=self.done.get(c['call_id'])
                if not e or e['status']!='SUCCESS': return None
                result += [{'role':'user','content':c['prompt']},{'role':'assistant','content':e['record']['content']}]
        return result+[{'role':'user','content':call['prompt']}]

    async def pause(self,seconds):
        try: await asyncio.wait_for(self.stop.wait(),max(.001,seconds))
        except asyncio.TimeoutError: pass

    async def run_call(self,call):
        if call['call_id'] in self.done or self.stop.is_set(): return
        messages=self.messages(call)
        if messages is None:
            self.finish_call(call,'SKIPPED',reason='prior_context_turn_not_successful'); return
        ex,s=self.cfg['execution'],self.cfg['safety']
        est=sum(estimated_tokens(m['content'])+8 for m in messages)
        ceiling=ex['context_input_ceiling'] if call['family']=='context_growth' else s['max_input_tokens']
        if est>ceiling:
            self.finish_call(call,'SKIPPED',reason='client_input_estimate_ceiling'); return
        # Deliberately conservative prepaid accounting. No refund for failed or
        # unknown usage; input bytes plus chat overhead, output requested maximum.
        reserve_input=sum(len(m['content'].encode())+64 for m in messages)+64
        reserve_tokens=reserve_input+call['requested_max_tokens']
        reserve_cost=cost(self.cfg,reserve_input,call['requested_max_tokens'])
        while not self.stop.is_set():
            prior=self.starts[call['call_id']]
            last=self.finishes.get(prior[-1]['attempt_id'],{}).get('record') if prior else None
            if last and (last['status']=='SUCCESS' or not last.get('retryable') or len(prior)>ex['retries']):
                self.finish_call(call,last['status'],last); return
            if '*' in self.branches or call['family'] in self.branches:
                self.finish_call(call,'SKIPPED',reason=self.branches.get('*') or self.branches[call['family']]); return
            if last:
                await self.pause(max(0,(last.get('next_retry_at') or 0)-time.time()))
                if self.stop.is_set(): return
                if '*' in self.branches or call['family'] in self.branches:
                    continue
            # No await between reservation checks and durable start: atomic within event loop.
            reason=None
            if self.request_count>=s['max_requests']: reason='request_budget'
            elif self.reserved_tokens+reserve_tokens>s['max_tokens']: reason='token_reservation_budget'
            elif s['max_cost'] is not None and self.reserved_cost+(reserve_cost or 0)>s['max_cost']: reason='cost_reservation_budget'
            if reason:
                self.branch_stop('*',reason); continue
            attempt_id=digest([self.run_id,call['call_id'],len(prior)])[:24]
            r={'run_id':self.run_id,'test_id':call['test_id'],'call_id':call['call_id'],'attempt_id':attempt_id,
               'conversation_id':call['conversation_id'],'turn':call['turn'],'dataset':call['dataset'],
               'source_sample_id':call['source_sample_id'],'sample_id':call['sample_id'],'task':call['task'],
               'test_family':call['family'],'test_level':call['level'],'timestamp':time.time(),
               'model':self.cfg['model']['model'],'mode':self.cfg['model']['mode'],'messages':messages,
               'requested_max_tokens':call['requested_max_tokens'],'retry_count':len(prior),
               'repetition':call['repetition'],'concurrency':call['concurrency'],'in_flight_at_dispatch':self.active+1,
               'estimated_input_tokens':est,'reserved_tokens':reserve_tokens,'reserved_cost':reserve_cost,
               'transformation':call['transformation'],'ttft_seconds':None}
            start=self.j.append('attempt_started',attempt_id=attempt_id,call_id=call['call_id'],
                                record=r,reserved_tokens=reserve_tokens,reserved_cost=reserve_cost)
            prior.append(start); self.request_count+=1; self.reserved_tokens+=reserve_tokens; self.reserved_cost+=reserve_cost or 0
            self.active+=1; begin=time.monotonic()
            try:
                envelope=await self.transport(self.cfg['model'],messages,call['requested_max_tokens'],
                                              digest([self.run_id,call['call_id']]),ex['timeout'])
            except (OSError,ValueError,RuntimeError,asyncio.TimeoutError) as exc:
                envelope={'ok':False,'error':type(exc).__name__,'retryable':True}
            finally: self.active-=1
            response=envelope.get('response',{}) if envelope.get('ok') else {}
            inp,out,total=usage(response)
            status='SUCCESS' if envelope.get('ok') else ('TIMEOUT' if envelope.get('error')=='timeout' else 'ERROR')
            http=response.get('status_code',envelope.get('status_code'))
            backoff=min(ex['max_backoff_seconds'],ex['retry_backoff_seconds']*2**(len(prior)-1))
            delay=retry_delay(envelope.get('retry_after'),backoff)
            r.update(status=status,content=response.get('content',''),reasoning=response.get('reasoning',''),
                     raw_response=envelope,latency=time.monotonic()-begin,http_status=http,
                     rate_limits=response.get('rate_limits',envelope.get('rate_limits',{})),
                     finish_reason=response.get('finish_reason'),input_tokens=inp,output_tokens=out,total_tokens=total,
                     usage_status='provider_reported' if total is not None else 'unavailable',
                     estimated_cost=cost(self.cfg,inp,out),ttft_seconds=response.get('ttft_seconds'),
                     error=envelope.get('error'),retryable=bool(envelope.get('retryable')),
                     next_retry_at=time.time()+delay if math.isfinite(delay) else None)
            self.finish_attempt(start,r)
            if r['retryable'] and delay>ex['max_backoff_seconds']:
                self.branch_stop(call['family'],'server_retry_after_exceeds_local_wait_ceiling')
            if total is not None and total>reserve_tokens:
                self.branch_stop('*','observed_usage_exceeded_reservation')
            if out is not None and out>call['requested_max_tokens']:
                self.branch_stop('*','observed_output_exceeded_requested_cap')

    async def run(self):
        # Group by contiguous family/level; context turns deliberately remain serial.
        groups=[]
        for call in self.manifest['calls']:
            key=(call['family'],call['level'])
            if not groups or groups[-1][0]!=key: groups.append((key,[]))
            groups[-1][1].append(call)
        for index,(_,calls) in enumerate(groups):
            if self.stop.is_set(): break
            if all(c['call_id'] in self.done for c in calls): continue
            if index: await self.pause(self.cfg['safety']['cooldown_seconds'])
            queue=iter(calls)
            async def worker():
                while not self.stop.is_set():
                    c=next(queue,None)
                    if c is None:return
                    await self.run_call(c)
                    self.j.checkpoint(total=len(self.manifest['calls']),completed=len(self.done),status='running',
                                      attempts=self.request_count,stopped_branches=self.branches)
                    if hasattr(self,'publish') and time.monotonic()-self.last_report>=self.cfg['execution']['report_interval_seconds']:
                        self.publish(); self.last_report=time.monotonic()
            concurrency=min(calls[0]['concurrency'],self.cfg['safety']['max_concurrency'])
            await asyncio.gather(*(worker() for _ in range(concurrency)))


async def execute(cfg,manifest,coverage,identity,transport=client.complete):
    from .report import write_reports
    implementation={p.name:digest(p.read_text()) for p in Path(__file__).parent.glob('*.py') if p.name not in ('report.py','metrics.py','background.py')}
    run_id=digest([ {k:v for k,v in cfg.items() if k!='paths'},manifest,identity,implementation])[:24]
    directory=Path(cfg['paths']['results'])/run_id
    reports=Path(cfg['paths']['reports'])/run_id
    with Journal(directory) as j:
        write_json(directory/'config.json',cfg); write_json(directory/'manifest.json',manifest)
        write_json(directory/'coverage.json',coverage); write_json(directory/'identity.json',identity)
        write_json(Path(cfg['paths']['results'])/'latest.json',{'run_id':run_id,'directory':str(directory),'report':str(reports/'report.html')})
        runner=Executor(cfg,manifest,j,run_id,transport)
        runner.publish=lambda:write_reports(directory,reports,j.events,manifest,coverage,cfg,run_id)
        runner.last_report=time.monotonic()
        loop=asyncio.get_running_loop()
        for sig in (signal.SIGINT,signal.SIGTERM): loop.add_signal_handler(sig,runner.stop.set)
        print(f'Run {run_id}\nResults: {directory}\nReport: {reports / "report.html"}',flush=True)
        try:
            runner.publish()
            publish_latest(Path(cfg['paths']['results']),directory)
            publish_latest(Path(cfg['paths']['reports']),reports)
            await runner.run()
        finally:
            for sig in (signal.SIGINT,signal.SIGTERM): loop.remove_signal_handler(sig)
            runner.publish()
            j.checkpoint(total=len(manifest['calls']),completed=len(runner.done),attempts=runner.request_count,
                         status='interrupted' if runner.stop.is_set() else 'finished',stopped_branches=runner.branches)
        incomplete=any(e['status']!='SUCCESS' for e in runner.done.values()) or len(runner.done)<len(manifest['calls'])
        return 2 if incomplete else 0
