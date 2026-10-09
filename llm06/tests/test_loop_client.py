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
