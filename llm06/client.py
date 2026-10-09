"""Native tool transport through Loop’s existing provider integration."""
import json
import subprocess
import time
from common import ROOT

class TransportError(Exception):
    def __init__(self,message,retryable=False):
        super().__init__(message);self.retryable=retryable

class Client:
    def __init__(self,spec):
        from common import CLIENT
        from jsonschema import Draft202012Validator
        Draft202012Validator(CLIENT).validate(spec)
        self.spec=spec
    def complete(self,messages,tools,key):
        s=self.spec; start=time.monotonic()
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
