"""Static conversion of simple source read methods into a bounded JSON expression tree.

Only constant/object/list construction and parameter lookup are accepted. Source
imports, calls, control flow and writes are never executed. Unknown expressions
fail closed during preparation.
"""
import ast
import copy

class Unsupported(ValueError):pass


def expression(node,bindings):
    if isinstance(node,ast.Constant) and isinstance(node.value,(str,int,float,bool,type(None))):return {'op':'literal','value':node.value}
    if isinstance(node,ast.Name) and node.id in bindings:return copy.deepcopy(bindings[node.id])
    if isinstance(node,ast.Attribute) and isinstance(node.value,ast.Name) and node.value.id=='self' and node.attr in bindings:return copy.deepcopy(bindings[node.attr])
    if isinstance(node,ast.Dict):
        if any(k is None or not isinstance(k,ast.Constant) or not isinstance(k.value,str) for k in node.keys):raise Unsupported('nonliteral object key')
        return {'op':'object','items':{k.value:expression(v,bindings) for k,v in zip(node.keys,node.values)}}
    if isinstance(node,(ast.List,ast.Tuple)):return {'op':'array','items':[expression(v,bindings) for v in node.elts]}
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='get' and 1<=len(node.args)<=2 and not node.keywords:
        if isinstance(node.func.value,ast.Attribute) and isinstance(node.func.value.value,ast.Name) and node.func.value.value.id=='self' and node.func.value.attr=='parameters':
            key=ast.literal_eval(node.args[0])
            if not isinstance(key,str):raise Unsupported('nonliteral parameter key')
            # Missing source state is not replaced by upstream placeholder defaults.
            return {'op':'parameter','key':key}
    if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Attribute) and isinstance(node.value.value,ast.Name) and node.value.value.id=='self' and node.value.attr=='parameters':
        key=ast.literal_eval(node.slice)
        if isinstance(key,str):return {'op':'parameter','key':key}
    raise Unsupported('unsupported read expression: '+type(node).__name__)


def compile_read(methods,name):
    bindings={'parameters':{'op':'all_parameters'}}
    init=methods.get('__init__')
    if init:
        for node in init.body:
            if isinstance(node,ast.Assign) and len(node.targets)==1:
                target=node.targets[0]
                if isinstance(target,ast.Attribute) and isinstance(target.value,ast.Name) and target.value.id=='self':
                    if target.attr=='parameters':continue
                    try:bindings[target.attr]=expression(node.value,bindings)
                    except (Unsupported,ValueError):bindings.pop(target.attr,None)
    method=methods.get(name)
    if method is None:raise Unsupported('source method absent')
    result=None
    for node in method.body:
        if isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):continue
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            bindings[node.targets[0].id]=expression(node.value,bindings)
        elif isinstance(node,ast.Return):
            result=expression(node.value,bindings);break
        else:raise Unsupported('unsupported read statements')
    if result is None:raise Unsupported('read has no static return')
    return result


def keys(plan):
    if plan['op']=='parameter':return {plan['key']}
    if plan['op']=='object':return set().union(*(keys(p) for p in plan['items'].values()))
    if plan['op']=='array':return set().union(*(keys(p) for p in plan['items']))
    return set()


def project(plan,parameters):
    op=plan['op']
    if op=='literal':return copy.deepcopy(plan['value'])
    if op=='parameter':
        if plan['key'] not in parameters:raise KeyError(plan['key'])
        return copy.deepcopy(parameters[plan['key']])
    if op=='all_parameters':return copy.deepcopy(parameters)
    if op=='object':return {k:project(v,parameters) for k,v in plan['items'].items()}
    if op=='array':return [project(v,parameters) for v in plan['items']]
    raise ValueError('Unknown projection operation')
