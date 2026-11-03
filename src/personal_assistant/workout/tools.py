"""Read-only MCP tools for the persistent trainer; writes are owner-approved proposals."""
import argparse
import json
import re
from pathlib import Path
import sys
from urllib.parse import urlencode, quote
from ..relay.client import OwnerClient
from .models import MODELS


def workout_path(user_id=None):
    if user_id is None:
        return '/relay/v1/workout'
    if not re.fullmatch(r'[a-f0-9]{32}', user_id):
        raise ValueError('Invalid Train member ID')
    return '/relay/v1/train/users/'+user_id+'/workout'


def serve(config, source=sys.stdin, target=sys.stdout, *, user_id=None):
    client = OwnerClient(config)
    base = workout_path(user_id)
    tools = [dict(name='workout_read',description='Read actual workout context. overview is aggregate evidence; entities pages all history; entity reads exact record/revision. No writes.',
        inputSchema={'type':'object','properties':{'view':{'type':'string','enum':['overview','entities','entity']},
            'kind':{'type':'string','enum':list(MODELS)},'id':{'type':'string','pattern':'^[A-Za-z0-9_-]{1,100}$'},'offset':{'type':'integer'},'limit':{'type':'integer'}},
            'required':['view'],'additionalProperties':False},annotations={'readOnlyHint':True,'destructiveHint':False})]
    for line in source:
        request = None
        try:
            request = json.loads(line)
            if 'id' not in request: continue
            method, params = request.get('method'), request.get('params',{})
            if method=='initialize': result={'protocolVersion':params.get('protocolVersion','2024-11-05'),'capabilities':{'tools':{}},'serverInfo':{'name':'workout-specialist','version':'1.0'}}
            elif method=='ping': result={}
            elif method=='tools/list': result={'tools':tools}
            elif method=='tools/call':
                try:
                    args = params.get('arguments') or {}
                    if params['name']!='workout_read': raise ValueError('Unknown workout tool')
                    view = args.get('view')
                    if view in ('entities','entity') and args.get('kind') is not None and args['kind'] not in MODELS:
                        raise ValueError('Read a known workout entity kind')
                    if view=='overview': path='/overview'
                    elif view=='entities':
                        limit, offset = int(args.get('limit',20)), int(args.get('offset',0))
                        if not 1<=limit<=100 or offset<0: raise ValueError('Invalid page')
                        query={'offset':offset,'limit':limit}
                        if args.get('kind'): query['kind']=args['kind']
                        path='/entities?'+urlencode(query)
                    elif view=='entity':
                        if args.get('kind') not in MODELS or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',args.get('id','')):
                            raise ValueError('Read a known workout entity with a valid ID')
                        path='/entities/'+quote(args['kind'],safe='')+'/'+quote(args['id'],safe='')
                    else: raise ValueError('Invalid view')
                    value=client.call(base+path)
                    if view=='overview':
                        value={k:value.get(k) for k in ('completed_workouts','body_metrics','body_rank','next_workout','sprints',
                            'lift_ranks','aggregate_score','trainer','next_session_brief','scheduled_sprints')}
                        # Full exercise histories remain available through paged entity reads.
                        # A dashboard payload must not fill an agent context with every chart point.
                        value['detail_access']='Read exact workout/template/sprint entities only when needed.'
                    result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}],'isError':False}
                except Exception as error:
                    result={'content':[{'type':'text','text':type(error).__name__+': '+str(error)}],'isError':True}
            else:
                target.write(json.dumps({'jsonrpc':'2.0','id':request['id'],'error':{'code':-32601,'message':'Method not found'}})+'\n');target.flush();continue
            response={'jsonrpc':'2.0','id':request['id'],'result':result}
        except Exception:
            response={'jsonrpc':'2.0','id':request.get('id') if isinstance(request,dict) else None,'error':{'code':-32700,'message':'Invalid request'}}
        target.write(json.dumps(response,ensure_ascii=False)+'\n');target.flush()


def main():
    sys.stdin.reconfigure(encoding='utf-8');sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--user')
    args=parser.parse_args()
    serve(json.loads(args.config.read_text(encoding='utf-8-sig')), user_id=args.user)


if __name__=='__main__': main()
