"""Coalesced background uploads keep token reception independent of relay latency."""
from contextlib import contextmanager,ExitStack
import re
import logging
import threading
import time


class Publisher:
    def __init__(self,client,path,token,interval=.2):
        self.client,self.path,self.token,self.interval=client,path,token,interval
        self.condition=threading.Condition()
        self.latest='';self.version=0;self.stopped=False
        self.thread=threading.Thread(target=self.run,name='answer-progress',daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self,*_):
        with self.condition:
            self.stopped=True;self.condition.notify_all()
        # Final answers use their existing reliable transport and never wait on a partial upload.
        self.thread.join(timeout=.05)

    def __call__(self,text):
        with self.condition:
            text=text[:24000]
            if text==self.latest:return
            self.latest=text;self.version+=1;self.condition.notify_all()

    def run(self):
        sent=-1;sequence=0
        while True:
            with self.condition:
                if self.stopped:return
                if self.version==sent:self.condition.wait(timeout=self.interval)
                if self.stopped:return
                text,version=self.latest,self.version
            if version==sent:continue
            try:
                self.client.call(self.path,{'token':self.token,'sequence':sequence,'text':'' if sequence==0 else text},'PUT')
            except Exception:
                # An older relay, lost lease or transport failure cannot fail the actual answer.
                logging.debug('Partial answer transport unavailable',exc_info=False)
                return
            sequence+=1
            if sequence>1 or not text:sent=version
            time.sleep(self.interval)


@contextmanager
def publishing(config,client,path,token,field=None):
    if not config.get('answer_streaming',False):
        yield
        return
    from .streaming import answer_stream
    with Publisher(client,path,token) as publish,answer_stream(publish,field=field):
        yield


@contextmanager
def banking_publishing(config,jobs,token):
    questions=[j for j in jobs if j['kind']=='question' and re.fullmatch(r'[A-Za-z0-9_-]{8,64}',j['job_key'])]
    if not config.get('answer_streaming',False) or not questions or not config.get('relay_url') or not config.get('submit_token_file'):
        yield
        return
    from ..relay.client import OwnerClient
    from .streaming import answer_stream,reply_text
    with ExitStack() as stack:
        client=OwnerClient(config)
        publishers={j['seq']:stack.enter_context(Publisher(client,'/relay/v1/banking/conversations/'+j['job_key']+'/stream',token))
                    for j in questions}
        def changed(document):
            for sequence,publish in publishers.items():
                text=reply_text(document,sequence)
                if text:publish(text)
        with answer_stream(changed):yield
