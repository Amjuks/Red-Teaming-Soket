"""Bounded declarative JSON query plans extracted from a whitelist of source syntax.

This is not a Python interpreter: no imports, general function calls, attribute
lookup, code objects, filesystem, network, or state writes exist in the runtime.
Preparation rejects every syntax node outside the explicit query vocabulary.
"""
import ast
import copy
from projections import Unsupported

COMPARE={ast.Eq:'eq',ast.NotEq:'ne',ast.In:'in',ast.NotIn:'not_in',ast.Lt:'lt',ast.LtE:'le',ast.Gt:'gt',ast.GtE:'ge',ast.Is:'is',ast.IsNot:'is_not'}


def compile_query(methods,name):
    method=methods[name];attrs={}
    init=methods.get('__init__')
    if init:
        for node in init.body:
            if isinstance(node,ast.Assign) and len(node.targets)==1:
                t=node.targets[0]
                if isinstance(t,ast.Attribute) and isinstance(t.value,ast.Name) and t.value.id=='self' and t.attr!='parameters':
                    try:attrs[t.attr]=expr(node.value,attrs)
                    except (ValueError,TypeError):attrs.pop(t.attr,None)
    defaults={}
    for arg,value in zip(method.args.args[-len(method.args.defaults):] if method.args.defaults else [],method.args.defaults):defaults[arg.arg]=ast.literal_eval(value)
    for arg,value in zip(method.args.kwonlyargs,method.args.kw_defaults):
        if value is not None:defaults[arg.arg]=ast.literal_eval(value)
    return {'body':block(method.body,attrs),'defaults':defaults}


def expr(n,attrs):
    if isinstance(n,ast.Constant):return ['literal',n.value]
    if isinstance(n,ast.Name):
        if n.id=='self' or n.id.startswith('__'):raise Unsupported('forbidden query name')
        return ['var',n.id]
    if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id=='self':
        if n.attr=='parameters':return ['parameters']
        if n.attr in attrs:return copy.deepcopy(attrs[n.attr])
        raise Unsupported('unmapped source attribute')
    if isinstance(n,ast.Dict):
        if any(k is None for k in n.keys):raise Unsupported('query dict unpack')
        return ['object',[[expr(k,attrs),expr(v,attrs)] for k,v in zip(n.keys,n.values)]]
    if isinstance(n,(ast.List,ast.Tuple,ast.Set)):return ['array',[expr(x,attrs) for x in n.elts]]
    if isinstance(n,ast.Subscript):
        if isinstance(n.slice,ast.Slice):return ['slice',expr(n.value,attrs),*[expr(x,attrs) if x is not None else ['literal',None] for x in (n.slice.lower,n.slice.upper,n.slice.step)]]
        return ['item',expr(n.value,attrs),expr(n.slice,attrs)]
    if isinstance(n,ast.BoolOp):return ['and' if isinstance(n.op,ast.And) else 'or',[expr(x,attrs) for x in n.values]]
    if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.Not,ast.USub)):return ['not' if isinstance(n.op,ast.Not) else 'neg',expr(n.operand,attrs)]
    if isinstance(n,ast.Compare):
        if any(type(op) not in COMPARE for op in n.ops):raise Unsupported('query comparison')
        return ['compare',[COMPARE[type(op)] for op in n.ops],[expr(n.left,attrs),*[expr(x,attrs) for x in n.comparators]]]
    if isinstance(n,ast.IfExp):return ['choose',expr(n.test,attrs),expr(n.body,attrs),expr(n.orelse,attrs)]
    if isinstance(n,ast.ListComp) and len(n.generators)==1:
        g=n.generators[0]
        if not isinstance(g.target,ast.Name) or g.is_async:raise Unsupported('query comprehension target')
        return ['filter_map',g.target.id,expr(g.iter,attrs),[expr(x,attrs) for x in g.ifs],expr(n.elt,attrs)]
    if isinstance(n,ast.Call) and not n.keywords:
        if isinstance(n.func,ast.Name) and n.func.id in ('len','str','int','float','bool') and len(n.args)==1:
            return ['cast',n.func.id,expr(n.args[0],attrs)]
        if isinstance(n.func,ast.Attribute):
            if n.func.attr=='get' and len(n.args) in (1,2):return ['get',expr(n.func.value,attrs),expr(n.args[0],attrs),expr(n.args[1],attrs) if len(n.args)==2 else ['literal',None]]
            if n.func.attr in ('lower','upper','strip') and not n.args:return ['text',n.func.attr,expr(n.func.value,attrs)]
    raise Unsupported('unsupported query expression: '+type(n).__name__)


def block(nodes,attrs):
    out=[]
    for n in nodes:
        if isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str):continue
        if isinstance(n,ast.Return):out.append(['return',expr(n.value,attrs) if n.value else ['literal',None]])
        elif isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name):out.append(['let',n.targets[0].id,expr(n.value,attrs)])
        elif isinstance(n,ast.If):out.append(['if',expr(n.test,attrs),block(n.body,attrs),block(n.orelse,attrs)])
        elif isinstance(n,ast.For) and isinstance(n.target,ast.Name) and not n.orelse:out.append(['each',n.target.id,expr(n.iter,attrs),block(n.body,attrs)])
        elif isinstance(n,ast.Continue):out.append(['continue'])
        elif isinstance(n,ast.Break):out.append(['break'])
        elif isinstance(n,ast.Expr) and isinstance(n.value,ast.Call):
            call=n.value
            if not (isinstance(call.func,ast.Attribute) and isinstance(call.func.value,ast.Name) and call.func.attr=='append' and len(call.args)==1 and not call.keywords):raise Unsupported('query side effect')
            out.append(['append',call.func.value.id,expr(call.args[0],attrs)])
        else:raise Unsupported('unsupported query statement: '+type(n).__name__)
    return out

class Returned(Exception):
    def __init__(self,value):self.value=value
class Continue(Exception):pass
class Break(Exception):pass


def evaluate(plan,parameters,arguments):
    # Each request gets independent copies. Query aliases never refer to live state.
    parameters=copy.deepcopy(parameters);scope={**copy.deepcopy(plan['defaults']),**copy.deepcopy(arguments)};budget=[50000]
    def tick():
        budget[0]-=1
        if budget[0]<0:raise ValueError('query step budget exhausted')
    def ev(p):
        tick();op=p[0]
        if op=='literal':return copy.deepcopy(p[1])
        if op=='parameters':return parameters
        if op=='var':return scope[p[1]]
        if op=='array':return [ev(x) for x in p[1]]
        if op=='object':return {ev(k):ev(v) for k,v in p[1]}
        if op=='item':return ev(p[1])[ev(p[2])]
        if op=='get':
            obj=ev(p[1]);key=ev(p[2])
            if type(obj) is not dict:raise ValueError('query get requires JSON object')
            if obj is parameters and key not in obj:raise KeyError(key)
            return obj.get(key,ev(p[3]))
        if op=='slice':return ev(p[1])[slice(ev(p[2]),ev(p[3]),ev(p[4]))]
        if op=='not':return not ev(p[1])
        if op=='neg':return -ev(p[1])
        if op=='and':
            for x in p[1]:
                value=ev(x)
                if not value:return value
            return value
        if op=='or':
            for x in p[1]:
                value=ev(x)
                if value:return value
            return value
        if op=='choose':return ev(p[2]) if ev(p[1]) else ev(p[3])
        if op=='cast':return {'len':len,'str':str,'int':int,'float':float,'bool':bool}[p[1]](ev(p[2]))
        if op=='text':
            text=ev(p[2])
            if type(text) is not str:raise ValueError('query text requires string')
            return {'lower':str.lower,'upper':str.upper,'strip':str.strip}[p[1]](text)
        if op=='compare':
            values=[ev(x) for x in p[2]]
            for op,a,b in zip(p[1],values,values[1:]):
                # JSON identity tests are valid only for null/bool source guards.
                operations={'eq':lambda:a==b,'ne':lambda:a!=b,'in':lambda:a in b,'not_in':lambda:a not in b,'lt':lambda:a<b,'le':lambda:a<=b,'gt':lambda:a>b,'ge':lambda:a>=b,'is':lambda:a is b,'is_not':lambda:a is not b}
                if not operations[op]():return False
            return True
        if op=='filter_map':
            result=[]
            for item in ev(p[2]):
                tick();scope[p[1]]=item
                if all(ev(x) for x in p[3]):result.append(ev(p[4]))
            return result
        raise ValueError('unknown query operation')
    def run(nodes):
        for n in nodes:
            tick();op=n[0]
            if op=='return':raise Returned(ev(n[1]))
            if op=='let':scope[n[1]]=ev(n[2])
            elif op=='if':run(n[2] if ev(n[1]) else n[3])
            elif op=='append':
                if type(scope[n[1]]) is not list:raise ValueError('query append requires list')
                scope[n[1]].append(ev(n[2]))
            elif op=='each':
                for item in ev(n[2]):
                    tick();scope[n[1]]=item
                    try:run(n[3])
                    except Continue:continue
                    except Break:break
            elif op=='continue':raise Continue()
            elif op=='break':raise Break()
    try:run(plan['body'])
    except Returned as result:return result.value
    return None
