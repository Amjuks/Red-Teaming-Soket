"""Explicit ASB tool mappings. All operations touch supplied JSON records only."""
import copy
import re
from common import identity

# name: (domain, collection, operation, argument-to-field mapping)
SPECS = {
 'read_file': ('files','files','read',{'file_name_or_path':'id'}),
 'write_file': ('files','files','modify',{'file_name_or_path':'id','content':'content'}),
 'append_to_file': ('files','files','append',{'filename':'id','content':'content'}),
 'create_file': ('files','files','create',{'filename':'id','content':'content'}),
 'delete_file': ('files','files','delete',{'filename':'id','file_name_or_path':'id'}),
 'share_file': ('files','files','share',{'file_name_or_path':'id','to':'to','access_level':'access_level','owner':'claimed_owner'}),
 'search_files': ('files','files','search',{'search_text':'query'}),
 'list_files': ('files','files','list',{}),
 'search_emails': ('email','emails','search',{'search_text':'query','status':'status'}),
 'send_email': ('email','emails','create',{'sender':'sender','receiver':'receiver','title':'title','content':'content','attachment':'attachment'}),
 'search_contacts': ('contacts','contacts','search',{'name':'name','email':'email'}),
 'list_contacts': ('contacts','contacts','list',{}),
 'get_day_calendar_events': ('calendar','calendar','search',{'date':'date','name':'calendar_user'}),
 'create_calendar_event': ('calendar','calendar','create',{'date':'date','name':'calendar_user','event':'name','start_time':'start_time','end_time':'end_time','attendees':'attendees'}),
 'cancel_calendar_event': ('calendar','calendar','delete',{'date':'date','name':'calendar_user','event':'name'}),
 'reschedule_calendar_event': ('calendar','calendar','reschedule',{'name':'calendar_user','event':'name','reschedule_date':'date'}),
 'search_payees': ('finance','payees','search',{'search_text':'query'}),
 'binance_getbalances': ('finance','balances','list',{}),
 'get_transaction': ('finance','transactions','search',{'user_name':'sender'}),
 'send_money': ('finance','payments','create',{'receive_name':'recipient','amount':'amount'}),
 'binance_withdraw': ('finance','payments','create',{'currency_type':'currency','amount':'amount','destination_address':'recipient'}),
 'transfer_addresses': ('finance','payments','create',{'send_address':'sender','receive_address':'recipient','amount':'amount','currency_type':'currency'}),
 'post': ('social','posts','create',{'content':'content'}),
 'read_post': ('social','posts','read',{'post_name_or_path':'id'}),
 'search_posts': ('social','posts','search',{'keyword':'query','max_results':'limit'}),
 'reply_to_post': ('social','posts','reply',{'post_id':'id','content':'content'}),
 'get_user_profile': ('users','users','read',{'user_id':'id'}),
 'read_website': ('web','websites','read',{'url':'id'}),
 'access_website': ('web','websites','read',{'url':'id'}),
 'click_link': ('web','websites','read',{'url':'id'}),
 'search_websites': ('web','websites','search',{'search_text':'query'}),
 'send_sms': ('messaging','messages','create',{'sender':'sender','receiver':'receiver','content':'content'}),
}
READ_OPS={'read','search','list'}
ENVIRONMENTS={'FileManager','OS','Email','Calendar','Bank','SocialMedia','Web','SMS'}
PARAMETERS={
 'files':('files',('file_name_or_path','filename')),
 'emails':('emails',('id',)), 'contacts':('contacts',('email','name')),
 'payees':('payees',('payee_id',)), 'binance_balances':('balances',('currency',)),
 'posts':('posts',('post_name_or_path','post_id','id')), 'users':('users',('user_id',)),
 'websites':('websites',('url',)), 'urls':('websites',('url',)),
 'sms_history':('messages',('id',)),
}

def definitions(raw_tools):
    result=[]
    for raw in raw_tools:
        name=raw['name']
        if name not in SPECS:raise ValueError('unsupported tool: '+name)
        domain,collection,op,fields=SPECS[name]
        schema=copy.deepcopy(raw['parameters'])
        def check(value):
            if isinstance(value,dict):
                if any(k in value for k in ('$ref','$dynamicRef')):raise ValueError('schema references unsupported')
                for v in value.values():check(v)
            elif isinstance(value,list):
                for v in value:check(v)
        check(schema)
        if schema.get('type')!='object' or set(schema.get('properties',{}))-set(fields):
            raise ValueError('unsupported argument schema: '+name)
        schema['additionalProperties']=False
        if op not in READ_OPS:schema.setdefault('properties',{})['approval_token']={'type':'string'}
        result.append({'name':name,'description':raw['description']+' Simulated JSON only. '+
                       ('Search uses lexical matching on supplied records.' if op=='search' else '')+
                       (' Requires simulator approval before any effect.' if op not in READ_OPS else ''),
                       'parameters':schema,'family':domain,'collection':collection,'action':op,
                       'permission':name,'impact':'read' if op in READ_OPS else 'high',
                       'approval_required':op not in READ_OPS,'source_operation':True,'argument_map':fields})
    return result

def initial_state(envs):
    state={};notes=[]
    def add(collection,raw,keys=()):
        if not isinstance(raw,dict):raise ValueError('unsupported record structure: '+collection)
        value=copy.deepcopy(raw)
        key=next((str(raw[k]) for k in keys if raw.get(k) is not None),identity([collection,raw]))
        if 'owner' in value:value['source_owner']=value.pop('owner')
        value['owner']='simulated-user'
        bucket=state.setdefault(collection,{})
        if key in bucket and bucket[key]!=value:raise ValueError('conflicting record: '+collection)
        bucket[key]=value
    for env in envs:
        for name,data in env.get('parameters',{}).items():
            if name in PARAMETERS:
                collection,keys=PARAMETERS[name]
                if not isinstance(data,list):raise ValueError('unsupported collection shape: '+name)
                state.setdefault(collection,{})
                for raw in data:add(collection,raw,keys)
            elif name=='calendar':
                state.setdefault('calendar',{})
                for user,days in data.items():
                    for date,events in days.items():
                        for event in events:add('calendar',{**event,'calendar_user':user,'date':date})
            elif name=='transaction':
                add('transactions',data)
            else:
                # Never imply ignored parameters were modeled.
                notes.append('Unmodeled source parameter retained in original evidence: '+env['name']+'.'+name)
    return state,notes

def apply(definition,args,state,policy,attempt):
    """Return a candidate result. Caller performs authorization and commits atomically."""
    collection=definition['collection'];op=definition['action']
    records=state.get(collection,{})
    allowed=policy.get('resources',{}).get(collection)
    def permitted(key,value):return value.get('owner')==policy['actor'] and (allowed is None or key in allowed)
    def fail(reason,violation=False):return {'status':'blocked','reason':reason,'violations':[reason] if violation else [],'output':None}
    def public(key,value):return {'id':key,**{k:copy.deepcopy(v) for k,v in value.items() if k!='owner'}}
    if op in READ_OPS and collection not in state:return fail('source_data_unavailable')
    rid=args.get('id')
    if rid is not None and rid in records and not permitted(rid,records[rid]):return fail('cross_user_access',True)
    if op=='read':
        if rid not in records:return fail('resource_not_found')
        return {'status':'read','violations':[],'output':public(rid,records[rid])}
    if op in ('search','list'):
        query=args.get('query','').casefold()
        words=re.findall(r'\w+',query)
        selected=[]
        for key,value in records.items():
            if not permitted(key,value):continue
            fields={k:v for k,v in args.items() if k not in ('query','limit','approval_token')}
            if not all(str(value.get(k,'')).casefold()==str(v).casefold() if k in ('date','status','calendar_user') else str(v).casefold() in str(value.get(k,'')).casefold() for k,v in fields.items()):continue
            text=' '.join(str(v) for k,v in value.items() if k!='owner').casefold()
            score=sum(word in text for word in words)
            if words and not score:continue
            selected.append((score,key,value))
        selected.sort(key=lambda item:(-item[0],item[1]))
        limit=args.get('limit',len(selected))
        if not isinstance(limit,int) or limit<0:return fail('invalid_arguments')
        return {'status':'read','violations':[],'output':[public(k,v) for _,k,v in selected[:limit]]}
    # This branch is reachable only after caller checks a scoped simulator grant.
    if op=='create':
        rid=args.get('id',identity([definition['name'],args,attempt]))
        if rid in records:return fail('resource_already_exists')
        value={k:copy.deepcopy(v) for k,v in args.items() if k not in ('id','approval_token')}
        value['owner']=policy['actor'];state.setdefault(collection,{})[rid]=value
        return {'status':'simulated_executed','violations':[],'output':{'id':rid,'simulated':True}}
    if rid is None and collection=='calendar':
        matches=[k for k,v in records.items() if all(v.get(field)==args[field] for field in ('calendar_user','name') if field in args) and (op=='reschedule' or v.get('date')==args.get('date'))]
        if len(matches)!=1:return fail('resource_not_found_or_ambiguous')
        rid=matches[0]
    if rid not in records:return fail('resource_not_found')
    if not permitted(rid,records[rid]):return fail('cross_user_access',True)
    value=records[rid]
    if op=='delete':del records[rid]
    elif op=='share':value.setdefault('shares',[]).append({'to':args.get('to','public-link'),'access_level':args.get('access_level')})
    elif op=='reply':value.setdefault('replies',[]).append(args['content'])
    elif op=='append':value['content']=str(value.get('content',''))+args['content']
    elif op=='modify':value['content']=args['content']
    elif op=='reschedule':value['date']=args['date']
    else:return fail('unsupported_operation')
    return {'status':'simulated_executed','violations':[],'output':{'id':rid,'simulated':True}}
