"""Native tool transport. Only this module and datasets.py communicate externally."""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from common import ROOT, load_env

class TransportError(Exception):
    def __init__(self,message,retryable=False):
        super().__init__(message);self.retryable=retryable

class Client:
    def __init__(self,spec): self.spec=spec
    def complete(self,messages,tools,key):
        load_env(); s=self.spec; start=time.monotonic()
        if s['transport']=='loop':
            payload={'provider':s['provider'],'model':s['model'],'messages':messages,
                     'tools':[t['function'] for t in tools],'generation':{'max_tokens':s['max_tokens'],'temperature':0},
                     'timeout_seconds':s['timeout_seconds'],'request_key':key}
            try:
                p=subprocess.run([str(ROOT/'native/target/debug/llm06-loop-bridge')],input=json.dumps(payload),text=True,
                                 capture_output=True,timeout=s['timeout_seconds']+10,cwd=ROOT)
                envelope=json.loads(p.stdout)
            except subprocess.TimeoutExpired: raise TransportError('Loop bridge timed out; inference may have occurred',True)
            except (OSError,ValueError): raise TransportError('Loop bridge unavailable or invalid envelope')
            if not envelope.get('ok'): raise TransportError(envelope.get('error','Loop error'),envelope.get('retryable',False))
            r=envelope['response']; message={'role':'assistant','content':r['content']}
            if r.get('tool_calls'): message['tool_calls']=r['tool_calls']
            # Loop normalizes missing usage to zero and pricing defaults to zero.
            # Retain that raw evidence but do not claim provider-reported usage/cost.
            return {'message':message,'reasoning':r.get('reasoning'),'finish_reason':r['finish_reason'],
                    'usage':None,'transport_limitations':['Loop normalizes streamed tool argument JSON; exact wire argument bytes unavailable.','Empty text/reasoning fields may be normalized by Loop.'],'raw':r,'elapsed_seconds':time.monotonic()-start}
        payload={'model':s['model'],'messages':messages,'max_tokens':s['max_tokens'],'temperature':0}
        if tools: payload['tools']=tools
        headers={'Content-Type':'application/json','Idempotency-Key':key}
        env=s.get('api_key_env')
        if env:
            if not os.environ.get(env): raise TransportError('missing API credential: '+env)
            headers['Authorization']='Bearer '+os.environ[env]
        request=urllib.request.Request(s['base_url'].rstrip('/')+'/chat/completions',data=json.dumps(payload).encode(),headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=s['timeout_seconds']) as response: raw=json.load(response)
        except urllib.error.HTTPError as e: raise TransportError(f'provider HTTP {e.code}',e.code in (408,409,429) or e.code>=500)
        except (OSError,ValueError): raise TransportError('provider transport or JSON failure; inference may have occurred',True)
        try:
            c=raw['choices'][0]; m=c['message']
            if m.get('role')!='assistant': raise ValueError()
            return {'message':m,'reasoning':m.get('reasoning_content'),'finish_reason':c.get('finish_reason'),
                    'usage':raw.get('usage'),'raw':raw,'elapsed_seconds':time.monotonic()-start}
        except (KeyError,IndexError,TypeError,ValueError): raise TransportError('invalid completion envelope')
