"""Agent queue worker; separate heartbeat, lock, ledger and local runtime."""
import argparse
import json
import logging
import os
from pathlib import Path
import random
import signal
import threading
from datetime import datetime,timezone
from personal_assistant.worker.runtime import RelayClient,Worker,Singleton,TransportError
from .runtime import Orchestrator
from . import capacity


class AgentClient:
    def __init__(self,client,session_lanes=True): self.client=client;self.session_lanes=session_lanes
    def call(self,path,payload=None):
        if not path.startswith('/v1/'): raise ValueError('Invalid worker path')
        claim=path.split('?')[0]=='/v1/worker/claim'
        target='/v1/agent/'+path[4:]
        if claim and self.session_lanes:
            try:return self.client.call(target,{**(payload or {}),'session_lanes':True})
            except TransportError as error:
                if error.status!=422:raise
                # Older servers reject the capability field. Their global claim fence
                # keeps all slots serial until the relay is upgraded.
                self.session_lanes=False
        return self.client.call(target,payload)


class AgentWorker(Worker):
    """One bounded execution slot; durable outcomes still share the original ledger."""
    def __init__(self,config,slot,outbox_lock,**kwargs):
        super().__init__(config,**kwargs)
        self.slot,self.outbox_lock=slot,outbox_lock

    def status(self,state,**extra):
        record={'state':state,'pid':os.getpid(),'slot':self.slot,
                'updated_at':datetime.now(timezone.utc).isoformat(),
                'capabilities':getattr(self.executor,'capabilities',[]),**extra}
        filename='status' if self.slot==0 else 'status-slot-'+str(self.slot)
        temporary=self.directory/(filename+'.new')
        temporary.write_text(json.dumps(record),encoding='utf-8')
        temporary.replace(self.directory/(filename+'.json'))

    def flush_outbox(self):
        with self.outbox_lock:super().flush_outbox()

    def tick(self):
        availability = getattr(self.executor, 'agent_availability', None)
        if availability and self.executor.available() and not any(
            provider['usable'] for provider in availability().values()
        ):
            self.long_poll = False
            self.client.call('/v1/worker/heartbeat', {'readiness': 'blocked'})
            self.status('blocked', reason='model_allowance')
            self.flush_outbox()
            return False
        return super().tick()

    def run_slot(self):
        # The service holds one process-wide Singleton around every slot. Each
        # tick retains the existing lease keeper, cancellation and crash ledger.
        delay=2;self.status('starting')
        while not self.shutdown.is_set():
            try:
                worked=self.tick();delay=2
                if not (worked or self.long_poll):self.shutdown.wait(max(1,self.config.get('poll_seconds',4)))
            except TransportError as error:
                self.status('authentication_blocked' if error.status in (401,403) else 'disconnected',http_status=error.status)
                logging.warning('Agent slot %s relay connection: %s',self.slot,error)
                self.shutdown.wait(delay+random.uniform(0,min(2,delay/4)));delay=min(60,delay*2)
            except Exception as error:
                self.status('blocked',reason=type(error).__name__)
                logging.error('Agent slot %s operation failed: %s',self.slot,type(error).__name__)
                self.shutdown.wait(15)
        self.status('stopped')


def execution_slots(config):
    value=config.get('agent_execution_slots',4)
    if type(value) is not int or not 1<=value<=8:
        raise ValueError('agent_execution_slots must be an integer between 1 and 8')
    return value


def refresh_capacity(config, shutdown, interval):
    while not shutdown.is_set():
        try:
            capacity.refresh_codex(config)
        except Exception as error:
            logging.warning('Codex allowance refresh failed (%s).', type(error).__name__)
        if shutdown.wait(interval):
            break


def run_service(config):
    directory=Path(config['runtime_dir']);directory.mkdir(parents=True,exist_ok=True)
    shutdown=threading.Event();outbox_lock=threading.Lock()
    workers=[AgentWorker(config,slot,outbox_lock,
                client=AgentClient(RelayClient(config['relay_url'],config['worker_token_file']),
                                   session_lanes=config.get('dispatcher_mode','legacy')=='jev'),
                executor=Orchestrator(config)) for slot in range(execution_slots(config))]
    for worker in workers:worker.shutdown=shutdown
    for number in (signal.SIGINT,signal.SIGTERM):signal.signal(number,lambda *_:shutdown.set())
    with Singleton(directory/'worker.lock'):
        interval = config.get('codex_capacity_poll_seconds')
        if interval:
            threading.Thread(target=refresh_capacity, args=(config, shutdown, max(30, interval)),
                             name='codex-capacity', daemon=True).start()
        threads=[threading.Thread(target=worker.run_slot,name='agent-slot-'+str(worker.slot),daemon=True) for worker in workers]
        for thread in threads:thread.start()
        try:
            while not shutdown.wait(.5):
                if not any(thread.is_alive() for thread in threads):break
        finally:
            shutdown.set()
            for thread in threads:thread.join(timeout=40)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args()
    config=json.loads(args.config.read_text(encoding='utf-8-sig'))
    config['runtime_dir']=config['agent_runtime_dir']
    config['pause_file']=str(Path.home()/'.personal-assistant/worker/pause.flag')
    run_service(config)


if __name__=='__main__': main()
