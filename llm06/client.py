"""Native tool transport through Loop’s existing provider integration."""
import json
import subprocess
import time
from common import ROOT

class TransportError(Exception):
    def __init__(self,message,retryable=False,details=None):
        super().__init__(message);self.retryable=retryable;self.details=details or {}

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
        except OSError as error: raise TransportError('Loop bridge unavailable',False,{'detail':type(error).__name__})
        except ValueError: raise TransportError('Loop bridge returned invalid JSON',True)
        if not isinstance(envelope,dict):raise TransportError('Loop bridge returned a non-object envelope',True)
        if not envelope.get('ok'):
            status=envelope.get('status_code')
            broken_stream=isinstance(status,int) and 200<=status<300
            message='Loop stream failed after HTTP '+str(status) if broken_stream else envelope.get('error','Loop error')
            raise TransportError(message,envelope.get('retryable',False) or broken_stream,
                {k:envelope[k] for k in ('status_code','retry_after','detail') if k in envelope})
        r=envelope.get('response')
        if not isinstance(r,dict) or not isinstance(r.get('finish_reason'),str) or not isinstance(r.get('content'),(str,type(None))) or not isinstance(r.get('tool_calls',[]),list):
            raise TransportError('Loop bridge returned an invalid completion structure',True)
        message={'role':'assistant','content':r.get('content')}
        if r.get('tool_calls'): message['tool_calls']=r['tool_calls']
        # Loop normalizes missing usage to zero and pricing defaults to zero.
        # Retain that raw evidence but do not claim provider-reported usage/cost.
        return {'message':message,'reasoning':r.get('reasoning'),'finish_reason':r['finish_reason'],
                'usage':None,'transport_limitations':['Loop normalizes streamed tool argument JSON; exact wire argument bytes unavailable.','Empty text/reasoning fields may be normalized by Loop.'],'raw':r,'elapsed_seconds':time.monotonic()-start}
