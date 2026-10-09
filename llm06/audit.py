"""Offline corpus audit: schema-valid calls, immutable reads, and blocked effects."""
import copy
from collections import Counter
from jsonschema import Draft202012Validator
from environment import Environment
from common import identity


def example_value(schema):
    if 'enum' in schema:return schema['enum'][0]
    if 'const' in schema:return schema['const']
    kind=schema.get('type','string')
    if isinstance(kind,list):kind=next((k for k in kind if k!='null'),kind[0])
    if kind=='object':return {k:example_value(schema.get('properties',{}).get(k,{})) for k in schema.get('required',[])}
    if kind=='array':return [example_value(schema.get('items',{})) for _ in range(max(1,schema.get('minItems',0)))]
    if kind=='integer':return max(1,schema.get('minimum',1))
    if kind=='number':return max(1.0,schema.get('minimum',1.0))
    if kind=='boolean':return True
    if kind=='null':return None
    return 'fixture'


def arguments(tool,scenario):
    schema=tool['parameters'];values={}
    candidates={}
    def visit(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if not isinstance(item,(dict,list)):candidates.setdefault(key,[]).append(item)
                visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    visit(scenario['initial_state'])
    for name in schema.get('required',[]):
        prop=schema.get('properties',{}).get(name,{})
        validator=Draft202012Validator(prop)
        matching=next((x for x in candidates.get(name,[]) if validator.is_valid(x)),None)
        values[name]=matching if matching is not None else example_value(prop)
    return values


def audit(scenarios):
    outcomes=Counter();issues=[];checks=0
    for s in scenarios:
        for tool in s['tools']:
            args=arguments(tool,s)
            if not Draft202012Validator(tool['parameters']).is_valid(args):
                issues.append({'sample_id':s['source']['sample_id'],'tool':tool['name'],'reason':'audit_argument_generator_unsupported'});continue
            env=Environment(s);before=identity(env.snapshot['state'])
            result=env.attempt(tool['name'],args);checks+=1
            if identity(env.snapshot['state'])!=before:raise AssertionError('Read or blocked action mutated state')
            if tool['approval_required'] and result['status']!='blocked':raise AssertionError('Unapproved effect executed')
            if result.get('reason') in ('source_query_error','source_data_unavailable'):
                issues.append({'sample_id':s['source']['sample_id'],'tool':tool['name'],'reason':result['reason']})
            outcomes[result.get('reason',result['status'])]+=1
    return {'scenarios':len(scenarios),'tool_checks':checks,'state_mutations':0,'outcomes':dict(outcomes),'issues':issues,
            'limitations':'Schema-valid example arguments exercise one path per tool; this is not exhaustive source equivalence or task completion validation.'}
