"""Agent queue worker; separate heartbeat, lock, ledger and local runtime."""
import argparse
import json
from pathlib import Path
import signal
from personal_assistant.worker.runtime import RelayClient,Worker
from .runtime import Orchestrator


class AgentClient:
    def __init__(self,client): self.client=client
    def call(self,path,payload=None):
        if not path.startswith('/v1/'): raise ValueError('Invalid worker path')
        return self.client.call('/v1/agent/'+path[4:],payload)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args()
    config=json.loads(args.config.read_text(encoding='utf-8-sig'))
    config['runtime_dir']=config['agent_runtime_dir']
    config['pause_file']=str(Path.home()/'.personal-assistant/worker/pause.flag')
    executor=Orchestrator(config)
    worker=Worker(config,client=AgentClient(RelayClient(config['relay_url'],config['worker_token_file'])),executor=executor)
    for number in (signal.SIGINT,signal.SIGTERM): signal.signal(number,lambda *_:worker.shutdown.set())
    worker.run()


if __name__=='__main__': main()
