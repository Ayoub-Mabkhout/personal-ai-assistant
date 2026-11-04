"""Protocol fixtures exercise real deltas; no model calls or network access."""
import io
import json
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch

from personal_assistant.orchestrator.streaming import (
    AnswerCapture,AppServerError,answer_stream,codex_turn,current_stream,text_field,reply_text,
)


class Input:
    def __init__(self,process):self.process=process
    def write(self,data):
        for line in data.splitlines():self.process.request(json.loads(line))
    def flush(self):pass
    def close(self):pass


class Output:
    def __init__(self,process):self.process=process
    def readline(self):return self.process.lines.get()
    def close(self):pass


class Server:
    def __init__(self,*,failure=False,cancel=None):
        self.lines=queue.Queue();self.stdin=Input(self);self.stdout=Output(self);self.stderr=io.BytesIO()
        self.requests=[];self.pid=991;self.returncode=None;self.failure=failure;self.cancel=cancel
    def event(self,body):self.lines.put((json.dumps(body)+'\n').encode())
    def request(self,message):
        self.requests.append(message);method=message.get('method');identifier=message.get('id')
        if method=='initialized':return
        if method=='initialize':body={}
        elif method=='config/read':body={'config':{'mcp_servers':{'unrelated':{'command':'private','env':{'SECRET':'never-log'}}}}}
        elif method in ('thread/start','thread/resume'):body={'thread':{'id':'same-session'}}
        elif method=='turn/start':
            self.event({'method':'turn/started','params':{'turn':{'id':'turn-1'}}})
            if self.cancel:self.cancel.set()
            self.event({'method':'item/started','params':{'item':{'id':'answer','type':'agentMessage','phase':'final_answer'}}})
            self.event({'method':'item/reasoning/summaryTextDelta','params':{'delta':'PRIVATE REASONING'}})
            self.event({'method':'item/agentMessage/delta','params':{'itemId':'answer','delta':'Hel'}})
            self.event({'method':'item/agentMessage/delta','params':{'itemId':'answer','delta':'lo'}})
            self.event({'method':'item/completed','params':{'item':{'id':'answer','type':'agentMessage','text':'Hello','phase':'final_answer'}}})
            self.event({'method':'thread/tokenUsage/updated','params':{'tokenUsage':{'last':{'inputTokens':12,'cachedInputTokens':8,'outputTokens':2,'reasoningOutputTokens':0}}}})
            self.event({'method':'turn/completed','params':{'turn':{'id':'turn-1','status':'failed' if self.failure else 'completed',
                'error':{'message':'usage limit reached'} if self.failure else None}}})
            body={'turn':{'id':'turn-1'}}
        elif method=='turn/interrupt':body={}
        else:raise AssertionError('Unexpected protocol method '+str(method))
        self.event({'id':identifier,'result':body})
    def poll(self):return self.returncode
    def stop(self):self.returncode=0;self.lines.put(b'')


class StreamingTests(unittest.TestCase):
    def test_only_top_level_text_is_decoded_during_structured_generation(self):
        self.assertEqual(text_field('{"memory_summary":"private text", "proposals":[{"text":"wrong"}],"text":"Hello\\nwo','text'),'Hello\nwo')
        self.assertEqual(text_field('{"memory_summary":"\\\"text\\\":\\\"secret\\\"", "proposals":[]','text'),'')
        self.assertEqual(text_field('{"text":"x\\uD83D','text'),'x')
        self.assertEqual(text_field('{"text":"x\\uD83D\\uDE00','text'),'x😀')
        self.assertEqual(text_field('{"text":"x\\','text'),'x')

    def test_scopes_are_isolated_and_restored(self):
        outer=[];inner=[]
        self.assertIsNone(current_stream())
        with answer_stream(outer.append):
            AnswerCapture().snapshot('outer')
            with answer_stream(inner.append,field='text'):
                AnswerCapture().snapshot('{"memory_summary":"private","text":"inside"}')
            AnswerCapture().snapshot('back')
        self.assertIsNone(current_stream());self.assertEqual(outer,['outer','back']);self.assertEqual(inner,['inside'])

    def test_money_replies_are_fenced_to_the_requested_job(self):
        document='{"decisions":[{"text":"private"}],"replies":[{"job_seq":7,"text":"first"},{"job_seq":8,"text":"sec'
        self.assertEqual(reply_text(document,7),'first')
        self.assertEqual(reply_text(document,8),'sec')
        self.assertEqual(reply_text(document,9),'')
        self.assertEqual(reply_text('{"replies":[{"text":"unknown","job_seq":8',8),'')

    def test_claude_ignores_thinking_and_tool_arguments(self):
        captured=[];capture=AnswerCapture((captured.append,None))
        for kind,delta in [('thinking','thinking_delta'),('tool_use','input_json_delta')]:
            capture.claude({'type':'stream_event','event':{'type':'content_block_start','index':0,'content_block':{'type':kind}}})
            capture.claude({'type':'stream_event','event':{'type':'content_block_delta','index':0,'delta':{'type':delta,'text':'private'}}})
        capture.claude({'type':'stream_event','event':{'type':'content_block_start','index':1,'content_block':{'type':'text'}}})
        capture.claude({'type':'stream_event','event':{'type':'content_block_delta','index':1,'delta':{'type':'text_delta','text':'Hello'}}})
        self.assertEqual(captured,['Hello'])

    def test_claude_structured_output_streams_only_its_readable_text_field(self):
        captured=[];capture=AnswerCapture((captured.append,'text'),structured=True)
        capture.claude({'type':'stream_event','event':{'type':'content_block_start','index':0,
            'content_block':{'type':'tool_use','name':'StructuredOutput'}}})
        for part in ('{"memory_summary":"private",','"text":"Hel','lo","proposals":[]}'):
            capture.claude({'type':'stream_event','event':{'type':'content_block_delta','index':0,
                'delta':{'type':'input_json_delta','partial_json':part}}})
        self.assertEqual(captured,['Hel','Hello'])

    def test_codex_resumes_same_thread_with_real_deltas_and_isolated_tools(self):
        server=Server();captured=[]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch('personal_assistant.orchestrator.streaming.subprocess.Popen',return_value=server), \
                 patch('personal_assistant.orchestrator.streaming.terminate',side_effect=lambda p:p.stop()), \
                 answer_stream(captured.append):
                result=codex_turn(['codex'],'Hi',root,'gpt-6.1-terra','medium',session='same-session',
                    config={'sandbox_mode':'read-only','mcp_servers':{'workout':{'command':'python','args':['tool']}}},
                    schema={'type':'object'},event_trace=root/'events.jsonl',raw_trace=root/'raw.jsonl',result_file=root/'result.txt')
            self.assertEqual(captured,['Hel','Hello']);self.assertEqual(result.text,'Hello')
            self.assertEqual(result.session_id,'same-session');self.assertEqual(result.usage['input_tokens'],12)
            resume=next(r for r in server.requests if r['method']=='thread/resume')['params']
            self.assertFalse(resume['config']['mcp_servers']['unrelated']['enabled'])
            self.assertTrue(resume['config']['mcp_servers']['workout']['enabled'])
            self.assertEqual(resume['sandbox'],'read-only')
            self.assertNotIn('never-log',(root/'raw.jsonl').read_text())
            self.assertEqual((root/'result.txt').read_text(),'Hello')
            self.assertEqual([json.loads(l)['type'] for l in (root/'events.jsonl').read_text().splitlines()][-1],'turn.completed')

    def test_cancel_interrupts_without_replaying_turn(self):
        cancel=threading.Event();server=Server()
        with patch('personal_assistant.orchestrator.streaming.subprocess.Popen',return_value=server), \
             patch('personal_assistant.orchestrator.streaming.terminate',side_effect=lambda p:p.stop()), \
             answer_stream(lambda _:cancel.set()):
            with self.assertRaises(AppServerError):
                codex_turn(['codex'],'Hi',Path.cwd(),'gpt-6-luna','low',cancelled=cancel)
        self.assertEqual(sum(r['method']=='turn/start' for r in server.requests),1)
        self.assertTrue(any(r['method']=='turn/interrupt' for r in server.requests))

    def test_provider_failure_keeps_error_trace_and_never_returns_success(self):
        server=Server(failure=True)
        with patch('personal_assistant.orchestrator.streaming.subprocess.Popen',return_value=server), \
             patch('personal_assistant.orchestrator.streaming.terminate',side_effect=lambda p:p.stop()):
            with self.assertRaises(AppServerError) as error:
                codex_turn(['codex'],'Hi',Path.cwd(),'gpt-6-luna','low')
        self.assertIn(b'usage limit reached',error.exception.stdout)


if __name__=='__main__':unittest.main()
