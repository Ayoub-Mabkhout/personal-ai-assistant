"""Real model answer deltas, isolated from reasoning, tools and structured metadata.

Codex protocol: https://learn.chatgpt.com/docs/app-server
The adapter emits full text snapshots so reconnecting consumers need no delta replay.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import threading
import time


_sink = ContextVar('answer_stream', default=None)


@contextmanager
def answer_stream(callback, field=None):
    """Install a per-execution sink; callback(snapshot) runs on the model's thread."""
    token = _sink.set((callback, field))
    try:
        yield
    finally:
        _sink.reset(token)


def current_stream():
    return _sink.get()


def _partial_string(text, start):
    """Decode a possibly incomplete JSON string without leaking incomplete escapes."""
    output=[]; index=start
    escapes={'n':'\n','r':'\r','t':'\t','b':'\b','f':'\f','"':'"','\\':'\\','/':'/'}
    while index<len(text):
        char=text[index]
        if char=='"':return ''.join(output), index+1, True
        if char!='\\':
            if ord(char)<32:return ''.join(output),index,False
            output.append(char);index+=1;continue
        if index+1>=len(text):break
        escaped=text[index+1]
        if escaped in escapes:
            output.append(escapes[escaped]);index+=2;continue
        if escaped!='u' or index+6>len(text):break
        try:code=int(text[index+2:index+6],16)
        except ValueError:break
        index+=6
        if 0xD800<=code<=0xDBFF:
            if text[index:index+2]!='\\u' or index+6>len(text):break
            try:low=int(text[index+2:index+6],16)
            except ValueError:break
            if not 0xDC00<=low<=0xDFFF:break
            code=0x10000+((code-0xD800)<<10)+(low-0xDC00);index+=6
        elif 0xDC00<=code<=0xDFFF:break
        output.append(chr(code))
    return ''.join(output),index,False


def text_field(document, field):
    """Extract ONLY a named top-level string, even while its JSON is arriving."""
    index=0;depth=0
    while index<len(document):
        char=document[index]
        if char in '{[':depth+=1;index+=1;continue
        if char in '}]':depth-=1;index+=1;continue
        if char!='"':index+=1;continue
        value,end,complete=_partial_string(document,index+1)
        if not complete:return ''
        index=end
        if depth!=1 or value!=field:continue
        while index<len(document) and document[index].isspace():index+=1
        if index>=len(document) or document[index]!=':':continue
        index+=1
        while index<len(document) and document[index].isspace():index+=1
        if index<len(document) and document[index]=='"':return _partial_string(document,index+1)[0]
        return ''
    return ''


def _value_start(document, field):
    index=0;depth=0
    while index<len(document):
        char=document[index]
        if char in '{[':depth+=1;index+=1;continue
        if char in '}]':depth-=1;index+=1;continue
        if char!='"':index+=1;continue
        value,index,complete=_partial_string(document,index+1)
        if not complete:return None
        if depth!=1 or value!=field:continue
        while index<len(document) and document[index].isspace():index+=1
        if index>=len(document) or document[index]!=':':continue
        index+=1
        while index<len(document) and document[index].isspace():index+=1
        return index
    return None


def reply_text(document, job_seq):
    """Banking's partial replies array, selected by its explicit numeric job ID."""
    index=_value_start(document,'replies')
    if index is None or index>=len(document) or document[index]!='[':return ''
    index+=1;decoder=json.JSONDecoder()
    while index<len(document):
        while index<len(document) and (document[index].isspace() or document[index]==','):index+=1
        if index>=len(document) or document[index]!='{':return ''
        start=index
        try:
            value,index=decoder.raw_decode(document,index)
        except ValueError:
            item=document[start:];identifier=_value_start(item,'job_seq')
            if identifier is None:return ''
            match=re.match(r'(-?[0-9]+)(?=[,}\s])',item[identifier:])
            return text_field(item,'text') if match and int(match[1])==job_seq else ''
        if isinstance(value,dict) and value.get('job_seq')==job_seq and isinstance(value.get('text'),str):return value['text']
    return ''


class AnswerCapture:
    """One readable answer item at a time; callbacks never see raw JSON metadata."""
    def __init__(self, sink=None, structured=False):
        self.sink=current_stream() if sink is None else sink
        self.structured=structured
        self.buffers={};self.phases={};self.last='';self.marks={}

    def snapshot(self, text):
        if not self.sink:return
        callback,field=self.sink
        readable=text_field(text,field) if field else text
        if readable==self.last:return
        self.last=readable
        if readable:self.marks.setdefault('first_text',time.monotonic())
        try:callback(readable)
        except Exception:logging.exception('Answer stream delivery failed; model execution continues')

    def codex(self,event):
        method=event.get('method');params=event.get('params') or {}
        if method=='item/started':
            self.marks.setdefault('first_output',time.monotonic())
            item=params.get('item') or {};self.phases[item.get('id')]=item.get('phase')
        elif method=='item/agentMessage/delta':
            key=params.get('itemId');self.buffers[key]=self.buffers.get(key,'')+str(params.get('delta') or '')
            if self.phases.get(key)!='commentary':self.snapshot(self.buffers[key])
        elif method=='item/completed':
            item=params.get('item') or {}
            if item.get('type')=='agentMessage' and item.get('phase')!='commentary':self.snapshot(item.get('text',''))

    def claude(self,event):
        # Only text deltas. Thinking, tool input JSON and tool results are excluded.
        if event.get('type')!='stream_event':return
        item=event.get('event') or {};kind=item.get('type')
        if kind=='content_block_start':
            self.marks.setdefault('first_output',time.monotonic())
            block=item.get('content_block') or {};key=item.get('index')
            self.phases[key]='structured' if self.structured and block.get('type')=='tool_use' and block.get('name')=='StructuredOutput' else block.get('type')
            self.buffers[key]=block.get('text','') if block.get('type')=='text' else ''
        elif kind=='content_block_delta':
            delta=item.get('delta') or {};key=item.get('index')
            if delta.get('type')=='text_delta' and self.phases.get(key)=='text':
                self.buffers[key]=self.buffers.get(key,'')+str(delta.get('text') or '')
                self.snapshot(self.buffers[key])
            elif delta.get('type')=='input_json_delta' and self.phases.get(key)=='structured':
                self.buffers[key]=self.buffers.get(key,'')+str(delta.get('partial_json') or '')
                self.snapshot(self.buffers[key])


class AppServerError(RuntimeError):
    pass


@dataclass
class CodexResult:
    text:str
    session_id:str
    stdout:bytes
    stderr:bytes
    usage:dict
    marks:dict
    returncode:int=0


def terminate(process):
    if process.poll() is not None:return
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    process.wait(timeout=15)


def codex_turn(prefix,prompt,workspace,model,effort,*,session=None,schema=None,instructions=None,
               features=None,config=None,images=(),environment=None,cancelled=None,timeout=1800,
               on_start=None,on_thread=None,raw_trace=None,event_trace=None,result_file=None,sink=None):
    """One app-server turn with existing subscription auth and the same saved thread ID.

    The process is dedicated to this call. No global daemon or session migration is needed.
    User-config MCP servers are explicitly disabled before the requested tools are enabled.
    """
    features=features or {};config=dict(config or {});cancelled=cancelled or threading.Event()
    args=list(prefix)
    for name,enabled in features.items():args+=['--enable' if enabled else '--disable',name]
    args+=['-c','model_provider="openai"','app-server','--stdio']
    process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        cwd=workspace,env=environment,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
        start_new_session=os.name!='nt')
    capture=AnswerCapture(sink);incoming=queue.Queue();errors=[];legacy=[];usage={};answer='';turn_id=None;thread_id=None;terminal=None
    raw=event_output=None
    try:
        raw=open(raw_trace,'wb') if raw_trace else None
        event_output=open(event_trace,'wb') if event_trace else None
    except BaseException:
        if raw:raw.close()
        terminate(process)
        raise
    deadline=time.monotonic()+timeout
    def stdout_reader():
        try:
            for line in iter(process.stdout.readline,b''):
                try:incoming.put(json.loads(line))
                except ValueError:continue
        finally:incoming.put(None)
    def stderr_reader():errors.append(process.stderr.read())
    readers=[threading.Thread(target=stdout_reader,daemon=True),threading.Thread(target=stderr_reader,daemon=True)]
    for reader in readers:reader.start()
    def send(body):process.stdin.write((json.dumps(body,ensure_ascii=False)+'\n').encode());process.stdin.flush()
    def emit(event):
        line=json.dumps(event,ensure_ascii=False)+'\n';legacy.append(line)
        if event_output:event_output.write(line.encode());event_output.flush()
    def notification(event):
        nonlocal answer,usage,turn_id,terminal
        if raw:raw.write((json.dumps(event,ensure_ascii=False)+'\n').encode());raw.flush()
        capture.codex(event)
        method=event.get('method');params=event.get('params') or {}
        if method=='thread/tokenUsage/updated':
            reported=(params.get('tokenUsage') or {}).get('last') or {}
            usage={key:reported.get(value,0) for key,value in (
                ('input_tokens','inputTokens'),('cached_input_tokens','cachedInputTokens'),
                ('output_tokens','outputTokens'),('reasoning_output_tokens','reasoningOutputTokens'))}
        elif method in ('item/started','item/completed'):
            item=params.get('item') or {}
            if method=='item/completed' and item.get('type')=='agentMessage' and item.get('phase')!='commentary':answer=item.get('text','')
            if item.get('type') not in ('userMessage','hookPrompt'):
                emit({'type':'item.started' if method=='item/started' else 'item.completed',
                      'item':{**item,'type':'agent_message' if item.get('type')=='agentMessage' else item.get('type')}})
        elif method=='turn/started':turn_id=(params.get('turn') or {}).get('id')
        elif method=='turn/completed':terminal=params.get('turn') or {}
        elif method=='error':
            emit({'type':'error','message':str((params.get('error') or {}).get('message') or 'Codex app-server error')})
    def receive():
        if cancelled.is_set() or time.monotonic()>deadline:
            if thread_id and turn_id:
                try:send({'id':'interrupt','method':'turn/interrupt','params':{'threadId':thread_id,'turnId':turn_id}})
                except OSError:pass
            raise AppServerError('Agent cancelled, disconnected or timed out; inspect its trace before resuming work.')
        try:event=incoming.get(timeout=.1)
        except queue.Empty:return {}
        if event is None:raise AppServerError('Codex app-server ended before completing the answer')
        if 'method' in event:
            # No tools or approvals are implemented by this bridge. Required MCP tools run in Codex.
            if 'id' in event:
                send({'id':event['id'],'error':{'code':-32601,'message':'Interactive client requests are not available in this headless worker'}})
                raise AppServerError('Codex requested an unsupported interactive client action; task was not replayed')
            notification(event)
        return event
    def rpc(identifier,method,params):
        send({'id':identifier,'method':method,'params':params})
        while True:
            event=receive()
            if event.get('id')==identifier:
                if event.get('error'):
                    message=str((event['error'] or {}).get('message') or 'Codex request failed')
                    emit({'type':'error','message':message});raise AppServerError(message)
                return event.get('result') or {}
    try:
        if on_start:on_start(process.pid)
        rpc(1,'initialize',{'clientInfo':{'name':'personal_assistant_stream','version':'1'}})
        send({'method':'initialized'})
        loaded=rpc(2,'config/read',{'includeLayers':False}).get('config') or {}
        wanted=config.pop('mcp_servers',{})
        config['mcp_servers']={name:{'enabled':False} for name in (loaded.get('mcp_servers') or {})}
        for name,value in wanted.items():config['mcp_servers'][name]={**value,'enabled':True}
        thread={'model':model,'cwd':str(workspace),'approvalPolicy':'never',
                'sandbox':config.get('sandbox_mode','danger-full-access'),'config':config,
                'developerInstructions':instructions}
        if session:thread.update(threadId=session,excludeTurns=True)
        started=rpc(3,'thread/resume' if session else 'thread/start',thread)
        thread_id=started['thread']['id']
        if session and thread_id!=session:raise AppServerError('Codex resumed a different session')
        if on_thread:on_thread(thread_id)
        emit({'type':'thread.started','thread_id':thread_id})
        turn={'threadId':thread_id,'input':[{'type':'text','text':prompt}]+
              [{'type':'localImage','path':str(path)} for path in images],
              'model':model,'effort':effort,'approvalPolicy':'never','cwd':str(workspace)}
        if schema:turn['outputSchema']=schema
        turn_id=(rpc(4,'turn/start',turn).get('turn') or {}).get('id') or turn_id
        while True:
            if terminal is not None:
                finished=terminal
                if finished.get('id')!=turn_id:
                    terminal=None;continue
                if finished.get('status')!='completed':
                    error=finished.get('error') or {};message=str(error.get('message') or 'Codex turn did not complete')
                    emit({'type':'error','message':message});raise AppServerError(message)
                if not answer:raise AppServerError('Codex completed without a final answer')
                if result_file:Path(result_file).write_text(answer,encoding='utf-8')
                emit({'type':'turn.completed','usage':usage});break
            receive()
        if not answer:raise AppServerError('Codex completed without a final answer')
        return CodexResult(answer,thread_id,''.join(legacy).encode(),b''.join(errors),usage,capture.marks)
    except BaseException as error:
        # Expose partial trace to callers even when the turn fails, without replaying effects.
        if isinstance(error,AppServerError):
            error.stdout=''.join(legacy).encode();error.stderr=b''.join(errors);error.session_id=thread_id
        raise
    finally:
        terminate(process)
        for reader in readers:reader.join(timeout=2)
        for stream in (process.stdin,process.stdout,process.stderr):
            try:stream.close()
            except OSError:pass
        if raw:raw.close()
        if event_output:event_output.close()
