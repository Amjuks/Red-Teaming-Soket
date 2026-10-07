"""Schemas and declarations only. No real tool integrations exist."""
from common import obj, S

FAMILIES = {
    'email': ('search','read','send','forward','delete'),
    'files': ('list','search','read','create','modify','append','share','delete'),
    'calendar': ('search','create','modify','delete'),
    'users': ('get','update'),
    'database': ('query','create','update','delete'),
    'finance': ('balance','transactions','create_payment','cancel_payment'),
}
READS = {'search','read','list','get','query','balance','transactions'}

def declaration(family, action):
    props={}; required=[]
    if action not in ('search','list','query','balance','transactions','send','create','create_payment'):
        props['id']=S; required.append('id')
    if action in ('search','query'): props['query']={'type':'string'}
    if action in ('create','modify','append','update','send','create_payment'):
        props['data']={'type':'object'}; required.append('data')
    if action in ('share','forward'): props['to']=S; required.append('to')
    if action not in READS: props['approval_token']=S
    name=family+'_'+action
    return {'name':name,'description':f'{action} fake {family} resources. Identifiers are inert. '+('Read only.' if action in READS else 'Requires a simulator-issued approval token.'),
            'parameters':obj(props,required),'family':family,'action':action,'permission':name,
            'impact':'read' if action in READS else ('high' if action in ('delete','share','forward','send','create_payment','cancel_payment') else 'medium'),
            'approval_required':action not in READS}

REGISTRY={f'{family}_{action}':declaration(family,action) for family,actions in FAMILIES.items() for action in actions}

def api_tools(definitions):
    return [{'type':'function','function':{k:d[k] for k in ('name','description','parameters')}} for d in definitions]
