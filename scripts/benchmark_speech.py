"""Run inside the Wyoming speech container; transcription only, no intent execution."""
import argparse
import asyncio
import json
from pathlib import Path
import re
import time
import wave

import numpy as np
from wyoming.client import AsyncTcpClient
from wyoming.event import Event
from wyoming.audio import AudioChunk,AudioStart
from faster_whisper import WhisperModel

PHRASES=['Add bananas, sparkling water and yogurt to my shopping list.',
         'Ask my assistant to find the most recent electricity invoice in my email.']


async def audio(text):
    async with AsyncTcpClient('piper',10200) as client:
        await client.write_event(Event(type='synthesize',data={'text':text}))
        chunks=[];settings=None
        while True:
            event=await asyncio.wait_for(client.read_event(),30)
            if event is None:raise RuntimeError('Piper closed before audio completed.')
            if event.type=='audio-start':settings=AudioStart.from_event(event)
            elif event.type=='audio-chunk':chunks.append(AudioChunk.from_event(event).audio)
            elif event.type=='audio-stop':break
        return settings,b''.join(chunks)


def words(value):return re.findall(r"[\w']+",value.casefold())


def edits(a,b):
    previous=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        current=[i]
        for j,y in enumerate(b,1):current.append(min(previous[j]+1,current[-1]+1,previous[j-1]+(x!=y)))
        previous=current
    return previous[-1]


async def benchmark(output,models,beam,fixtures=None,prompt=None):
    root=Path(output);root.mkdir(parents=True,exist_ok=True);clips=[]
    for index,text in enumerate(PHRASES):
        if fixtures:
            for label in ('clean','noise12db'):
                path=Path(fixtures)/f'{index}-{label}.wav'
                with wave.open(str(path),'rb') as wav:duration=wav.getnframes()/wav.getframerate()
                clips.append((path,text,label,duration))
            continue
        settings,pcm=await audio(text)
        if settings.width!=2 or settings.channels!=1:raise RuntimeError('Expected 16-bit mono Piper audio.')
        clean=np.frombuffer(pcm,dtype='<i2').astype(np.float32)
        for label,snr in [('clean',None),('noise12db',12)]:
            values=clean.copy()
            if snr is not None:
                rng=np.random.default_rng(42+index)
                noise=rng.normal(0,np.sqrt(np.mean(clean**2))/10**(snr/20),len(clean))
                values=values+noise
            path=root/f'{index}-{label}.wav'
            with wave.open(str(path),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(settings.rate)
                wav.writeframes(np.clip(values,-32768,32767).astype('<i2').tobytes())
            clips.append((path,text,label,len(clean)/settings.rate))
    report={'synthetic_audio':True,'noise':'seeded Gaussian, 12dB SNR; not real crowd/wind noise','models':[]}
    for model_name in models:
        start=time.monotonic()
        model=WhisperModel('rhasspy/faster-whisper-'+model_name,download_root='/data',device='cpu',compute_type='int8',cpu_threads=2)
        load=time.monotonic()-start;rows=[]
        size=1 if model_name=='tiny-int8' else beam
        for path,expected,label,duration in clips:
            start=time.monotonic();segments,_=model.transcribe(str(path),language='en',beam_size=size,vad_filter=model_name!='tiny-int8',initial_prompt=prompt if model_name!='tiny-int8' else None)
            text=' '.join(segment.text for segment in segments).strip();elapsed=time.monotonic()-start
            rows.append({'expected':expected,'transcript':text,'variant':label,'audio_seconds':round(duration,2),
                'transcription_seconds':round(elapsed,2),'word_errors':edits(words(expected),words(text)),'reference_words':len(words(expected))})
        report['models'].append({'model':model_name,'beam_size':size,'initial_prompt':prompt if model_name!='tiny-int8' else None,'load_seconds':round(load,2),'samples':rows})
        print(json.dumps(report['models'][-1]),flush=True)
        del model
    (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='/data/voice-benchmark')
    parser.add_argument('--models',nargs='+',default=['tiny-int8','small-int8'])
    parser.add_argument('--beam',type=int,default=5)
    parser.add_argument('--prompt',default='Voice commands: add items to my shopping list, ask my assistant, check my calendar, find an email.')
    parser.add_argument('--fixtures',help='Reuse identical existing clips for a controlled comparison.')
    args=parser.parse_args();asyncio.run(benchmark(args.output,args.models,args.beam,args.fixtures,args.prompt))
