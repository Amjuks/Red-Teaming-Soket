import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from jsonschema import ValidationError
from client import Client
from common import load_config

class LoopClientTests(unittest.TestCase):
    def test_routes_native_messages_through_loop_bridge(self):
        spec=load_config()['target']
        reply={'ok':True,'response':{'content':'','tool_calls':[{'id':'one','type':'function','function':{'name':'read_file','arguments':'{}'}}],'finish_reason':'tool_calls','raw':{}}}
        with patch('client.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps(reply))) as call:
            result=Client(spec).complete([{'role':'user','content':'read'}],[{'type':'function','function':{'name':'read_file','parameters':{'type':'object'}}}],'request')
        payload=json.loads(call.call_args.kwargs['input'])
        self.assertEqual(payload['provider'],'soket')
        self.assertEqual(payload['model'],'sarvam-30b')
        self.assertEqual(payload['tools'][0]['name'],'read_file')
        self.assertEqual(result['message']['tool_calls'][0]['id'],'one')
        self.assertNotIn('api_key',payload)
    def test_direct_api_settings_rejected(self):
        spec=load_config()['target']
        for changes in [{'transport':'openai'},{'api_key_env':'SOME_KEY'},{'base_url':'https://example.test/v1'}]:
            with self.assertRaises(ValidationError):Client({**spec,**changes})

if __name__=='__main__':unittest.main()

class StreamRecoveryTests(unittest.TestCase):
    def test_http_200_stream_failure_retries_but_auth_errors_do_not(self):
        from client import TransportError
        for status,retryable in [(200,True),(401,False),(400,False)]:
            reply={'ok':False,'status_code':status,'error':'provider failed','retryable':False,'detail':'sse stream interrupted'}
            with patch('client.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps(reply))):
                with self.assertRaises(TransportError) as error:Client(load_config()['target']).complete([],[],'test')
            self.assertEqual(error.exception.retryable,retryable)
            self.assertEqual(error.exception.details['detail'],'sse stream interrupted')

class EnvelopeValidationTests(unittest.TestCase):
    def test_malformed_envelopes_are_retryable_transport_errors(self):
        from client import TransportError
        for reply in [None,[],{'ok':True},{'ok':True,'response':{'content':'x'}},{'ok':True,'response':{'content':'x','finish_reason':'stop','tool_calls':{}}}]:
            with patch('client.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps(reply))):
                with self.assertRaises(TransportError) as error:Client(load_config()['target']).complete([],[],'test')
            self.assertTrue(error.exception.retryable)
