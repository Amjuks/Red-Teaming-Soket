"""Pinned environment source catalog. Read ZIP members as data; never import upstream code."""
import ast
import hashlib
import json
import zipfile
from pathlib import Path
from common import ROOT

VERSION='0.1.0'
WHEEL='agent_safety_bench_envs-0.1.0-py3-none-any.whl'
SHA256='c7d98cc6097c53b1f505be1f28b8925779e9955662a227f40c79f125c52a62ed'

class Catalog:
    def __init__(self):
        path=ROOT/'data/sources/asb-envs'/WHEEL
        if hashlib.sha256(path.read_bytes()).hexdigest()!=SHA256:raise ValueError('Environment source wheel hash mismatch')
        self.zip=zipfile.ZipFile(path)
        self.cache={}
    def environment(self,name):
        if name in self.cache:return self.cache[name]
        if not name or not name.replace('_','').isalnum():raise ValueError('Missing source environment')
        prefix='asb_envs/envs/'+name
        try:
            source=self.zip.read(prefix+'.py').decode();schemas=json.loads(self.zip.read(prefix+'.json'))
        except KeyError:raise ValueError('Environment absent from pinned catalog: '+name)
        tree=ast.parse(source)
        cls=next((n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==name),None)
        if cls is None:raise ValueError('Environment class missing: '+name)
        methods={n.name:n for n in cls.body if isinstance(n,ast.FunctionDef)}
        result=(methods,schemas,hashlib.sha256(source.encode()).hexdigest())
        self.cache[name]=result
        return result
