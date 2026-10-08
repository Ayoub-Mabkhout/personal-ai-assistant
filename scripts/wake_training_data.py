"""Source-grouped, annotated wake streams and licensed natural negatives."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
from collections import deque

import numpy as np
from piper import SynthesisConfig
from train_personal_wake import RATE, crop, sha, wav_read, wav_write, reset_features

TAILS = ["add bananas to my shopping list",
         "add bananas and sparkling water to my shopping list",
         "set an alarm for seven thirty tomorrow morning",
         "find the latest electricity invoice in my email"]
PREFIXES = ["Hey Chat", "", "Hey Jack", "Hey Cat", "Hey Chad", "Hey Pat", "I hate chatting"]


def prepare_librispeech(archive, output, seed=4207, per_split_minutes=(45,15,15)):
    """Verify and select speakers before extracting a bounded natural corpus.

    Read transcripts first and exclude any utterance containing 'HEY CHAT'. No
    arbitrary tar paths are extracted: selected audio bytes are written to our
    own filenames, decoded by ffmpeg, and preserved with source provenance.
    """
    output.mkdir(parents=True,exist_ok=True)
    manifest_path=output/"manifest.json"
    if manifest_path.exists():return json.loads(manifest_path.read_text())
    sums=archive.parent/"openslr-md5sum.txt"
    if sums.exists():
        expected=next((line.split()[0] for line in sums.read_text().splitlines() if line.split()[-1]==archive.name),None)
        if not expected or hashlib.md5(archive.read_bytes()).hexdigest()!=expected:raise ValueError("LibriSpeech archive checksum mismatch")
    rng=np.random.default_rng(seed);rows=[];transcripts={}
    with tarfile.open(archive) as tar:
        members=tar.getmembers()
        for member in members:
            if member.name.endswith('.trans.txt'):
                content=tar.extractfile(member).read().decode('utf-8')
                for line in content.splitlines():
                    ident,text=line.split(' ',1);transcripts[ident]=text
        audio=[m for m in members if m.name.endswith('.flac')]
        speakers=sorted({Path(m.name).stem.split('-')[0] for m in audio})
        rng.shuffle(speakers);n=len(speakers)
        assignments={s:'train' if i<int(n*.6) else 'dev' if i<int(n*.8) else 'natural-test' for i,s in enumerate(speakers)}
        # Keep physical tar order. Random seeks in a gzip archive repeatedly
        # decompress it; speaker quotas give diversity without that cost.
        durations={name:0 for name in ['train','dev','natural-test']}
        limits=dict(zip(durations,[m*60 for m in per_split_minutes]))
        speaker_seconds={s:0 for s in speakers}
        speaker_quota={s:limits[assignments[s]]/sum(v==assignments[s] for v in assignments.values()) for s in speakers}
        for member in audio:
            ident=Path(member.name).stem;speaker=ident.split('-')[0];split=assignments[speaker]
            if durations[split]>=limits[split] or speaker_seconds[speaker]>=speaker_quota[speaker] or 'HEY CHAT' in transcripts[ident]:continue
            original=output/'flac'/f'{ident}.flac';original.parent.mkdir(exist_ok=True)
            if not original.exists():original.write_bytes(tar.extractfile(member).read())
            dest=output/'wav'/f'{ident}.wav';dest.parent.mkdir(exist_ok=True)
            if not dest.exists():subprocess.run(['ffmpeg','-v','error','-y','-i',str(original),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(dest)],check=True)
            samples=len(wav_read(dest));durations[split]+=samples/RATE;speaker_seconds[speaker]+=samples/RATE
            rows.append({'id':ident,'path':str(dest.resolve()),'speaker':speaker,'split':split,'source_group':f'librispeech-{ident}',
                'source_member':member.name,'source_sha256':sha(original),'wav_sha256':sha(dest),'duration':samples/RATE,'text':transcripts[ident]})
            if all(durations[k]>=limits[k] for k in limits):break
    result={'seed':seed,'archive_sha256':sha(archive),'source_url':'https://www.openslr.org/12/',
        'license':'CC BY 4.0','attribution':'LibriSpeech: Vassil Panayotov, Guoguo Chen, Daniel Povey and Sanjeev Khudanpur; derived from LibriVox',
        'speaker_split':assignments,'seconds_per_split':durations,'clips':rows}
    manifest_path.write_text(json.dumps(result,indent=2));return result


def tts_source(voice, text, speaker, length_scale, output):
    options={'text':text,'speaker':speaker,'length_scale':length_scale}
    digest=hashlib.sha256(json.dumps(options,sort_keys=True).encode()).hexdigest()[:16]
    path=output/'sources'/f'tts-{speaker}-{digest}.wav'
    if not path.exists():
        chunks=list(voice.synthesize(text,SynthesisConfig(speaker_id=speaker,length_scale=length_scale)))
        values=np.concatenate([c.audio_float_array for c in chunks])*32767
        rate=chunks[0].sample_rate
        values=np.interp(np.arange(round(len(values)*RATE/rate))*rate/RATE,np.arange(len(values)),values)
        wav_write(path,crop(values))
        path.with_suffix('.json').write_text(json.dumps(dict(options,sha256=sha(path)),indent=2))
    return wav_read(path),path


def join(prefix,tail,gap=0):
    # Prefix already includes a short crop margin. Preserve it completely: the
    # following command never overwrites the last keyword phoneme.
    return np.concatenate([prefix,np.zeros(gap,np.float32),tail])


def variant(values,rng,index,natural=None):
    result=values.astype(np.float32)*rng.uniform(.45,1.15)
    if index%3==1:
        if natural is not None:
            noise=wav_read(natural)
            start=int(rng.integers(max(1,len(noise)-len(result)+1)))
            noise=noise[start:start+len(result)]
            if len(noise)<len(result):noise=np.tile(noise,int(np.ceil(len(result)/max(1,len(noise)))))[:len(result)]
        else:noise=rng.normal(size=len(result))
        snr=rng.uniform(8,18);rms=np.sqrt(np.mean(result**2));noise_rms=np.sqrt(np.mean(noise**2))
        result+=noise*rms/max(noise_rms,1e-9)/10**(snr/20)
    if index%3==2:
        clean=result.copy()
        for delay,gain in [(int(RATE*.04),.2),(int(RATE*.08),.1),(int(RATE*.13),.05)]:result[delay:]+=clean[:-delay]*gain
    return np.clip(result,-32768,32767).astype(np.int16)


def build_streams(voice,corpus,output,natural,rng,speakers=48,variants=2,personal_variants=12):
    output.mkdir(parents=True,exist_ok=True);manifest=output/'streams.json'
    if manifest.exists():return json.loads(manifest.read_text())
    ids=rng.choice(voice.config.num_speakers,size=speakers,replace=False).tolist();dev_ids=set(ids[-max(4,speakers//6):])
    clips=[];natural_by_split={name:[r['path'] for r in natural['clips'] if r['split']==name] for name in ['train','dev']}
    for speaker in ids:
        split='dev' if speaker in dev_ids else 'train';length_scale=float(rng.uniform(.85,1.15));prefix_cache={}
        for prefix in PREFIXES:
            if prefix:prefix_cache[prefix]=tts_source(voice,prefix,speaker,length_scale,output)
        reference_length=len(prefix_cache['Hey Chat'][0])
        for tail_index,text in enumerate(TAILS):
            tail,tail_path=tts_source(voice,text,speaker,length_scale,output)
            lead=int(rng.integers(int(RATE*.15),int(RATE*.65)))
            for prefix_index,prefix_text in enumerate(PREFIXES):
                prefix,prefix_path=prefix_cache[prefix_text] if prefix_text else (np.zeros(reference_length,np.float32),None)
                body=join(prefix,tail);values=np.concatenate([np.zeros(lead,np.float32),body,np.zeros(RATE,np.float32)])
                group=f'tts-{speaker}-tail{tail_index}-prefix{prefix_index}'
                # Paired control has identical tail and voice. Post-wake tails are
                # also negative sliding windows once the complete wake expires.
                for index in range(variants):
                    path=f'streams/{group}-{index}.wav';noise_path=None
                    if natural_by_split[split]:noise_path=natural_by_split[split][int(rng.integers(len(natural_by_split[split])))]
                    wav_write(output/path,variant(values,rng,index,noise_path))
                    clips.append({'path':path,'split':split,'source_group':group,'matched_family':f'tts-{speaker}-tail{tail_index}',
                        'speaker':speaker,'wake_expected':prefix_text=='Hey Chat','wake_start':lead/RATE if prefix_text=='Hey Chat' else None,
                        'wake_end':(lead+len(prefix))/RATE if prefix_text=='Hey Chat' else None,'prefix':prefix_text,'tail':text,
                        'tail_source_sha256':sha(tail_path),'prefix_source_sha256':sha(prefix_path) if prefix_path else None,'variant':index,
                        'noise_source':noise_path,'duration':len(values)/RATE})
        print(json.dumps({'stage':'matched-streams','speaker':speaker,'streams':len(clips)}),flush=True)
    training_ids=[s for s in ids if s not in dev_ids]
    for source in sorted((corpus/'wake-model/templates').glob('*.wav')):
        wake=wav_read(source)
        # Include same-speaker fragments and reversed word order as negatives.
        # The complete wake is never present in these synthetic controls.
        fragments=[('full',wake,True),('first',wake[:int(len(wake)*.35)],False),
                   ('last',wake[int(len(wake)*.65):],False),('reordered',np.concatenate([wake[len(wake)//2:],wake[:len(wake)//2]]),False)]
        for index in range(personal_variants):
            speaker=training_ids[index%len(training_ids)];text=TAILS[index%len(TAILS)]
            tail,_=tts_source(voice,text,speaker,1.,output);lead=int(rng.integers(2400,8000))
            for name,prefix,positive in fragments:
                values=np.concatenate([np.zeros(lead,np.float32),prefix,tail,np.zeros(RATE,np.float32)])
                path=f'streams/personal-{source.stem}-{index}-{name}.wav'
                noise_path=natural_by_split['train'][int(rng.integers(len(natural_by_split['train'])))] if natural_by_split['train'] else None
                wav_write(output/path,variant(values,rng,index,noise_path))
                clips.append({'path':path,'split':'train','source_group':f'personal-{source.stem}-{index}-{name}',
                    'speaker':'personal-training','wake_expected':positive,'wake_start':lead/RATE if positive else None,
                    'wake_end':(lead+len(prefix))/RATE if positive else None,'source_sha256':sha(source),'prefix':name,
                    'tail':text,'variant':index,'noise_source':noise_path,'duration':len(values)/RATE})
    # Natural files remain whole utterances and are selected by disjoint speaker.
    for row in natural['clips']:
        clips.append(dict(row,path=row['path'],wake_expected=False,wake_start=None,wake_end=None,kind='natural'))
    result={'speaker_ids':ids,'dev_speakers':sorted(dev_ids),'clips':clips,
        'positive_label':'entire annotated wake inside 1.96-second receptive field with40msguard',
        'natural_negative_source':'https://www.openslr.org/12/','natural_license':'CC BY4.0'}
    manifest.write_text(json.dumps(result,indent=2));return result


def window_label(end,wake_start,wake_end,horizon=1.96,guard=.04):
    if wake_start is None:return 0
    start=end-horizon
    if start<=wake_start-guard and end>=wake_end+guard:return 1
    if end<wake_start-guard or start>wake_end+guard:return 0
    # Do not label partial keywords or their immediate border as either class.
    return -1


def validate_streams(rows):
    """Reject source-family leakage and malformed wake annotations."""
    families={};source_splits={}
    for row in rows:
        previous=families.setdefault(row['source_group'],row['split'])
        if previous!=row['split']:raise ValueError('Source family crosses train/dev/test')
        for key in ['prefix_source_sha256','tail_source_sha256','source_sha256']:
            digest=row.get(key)
            if digest and source_splits.setdefault(digest,row['split'])!=row['split']:
                raise ValueError('Identical raw source bytes cross train/dev/test')
        if row['wake_expected']:
            if not 0<=row['wake_start']<row['wake_end']<=row['duration']:
                raise ValueError('Wake interval is outside its source stream')
            if row['wake_end']-row['wake_start']>1.88:
                raise ValueError('Wake cannot fit complete inside the classifier receptive field')
        elif row['wake_start'] is not None or row['wake_end'] is not None:
            raise ValueError('Negative stream has a wake annotation')


def cache_stream_features(rows,features,root,cache,train_stride=4):
    cache.mkdir(parents=True,exist_ok=True);records=[];x=[];y=[];split=[];ends=[]
    reset_features(features)
    for _ in range(38):features(np.zeros(1280,np.int16))
    warm_state=(list(features.raw_data_buffer),features.melspectrogram_buffer.copy(),features.feature_buffer.copy())
    for index,row in enumerate(rows):
        digest=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()[:20];path=cache/(digest+'.npz')
        if path.exists():
            saved=np.load(path);vectors=saved['vectors'].astype(np.float32);times=saved['times'];labels=saved['labels']
        else:
            pcm=wav_read(Path(row['path']) if Path(row['path']).is_absolute() else root/row['path']).astype(np.int16)
            # 3.04 seconds =38whole80msblocks, matching Android's cold-start state.
            warmup=48640;data=np.concatenate([pcm,np.zeros(16000,np.int16)])
            features.raw_data_buffer=deque(warm_state[0],maxlen=RATE*10)
            features.melspectrogram_buffer=warm_state[1].copy();features.feature_buffer=warm_state[2].copy()
            features.accumulated_samples=0;features.raw_data_remainder=np.empty(0,np.int16)
            vectors=[];times=[];labels=[]
            for offset in range(0,len(data),1280):
                block=data[offset:offset+1280]
                if len(block)<1280:block=np.pad(block,(0,1280-len(block)))
                features(block)
                end=(offset+1280)/RATE
                vectors.append(features.get_features(16)[0]);times.append(end)
                labels.append(window_label(end,row['wake_start'],row['wake_end']))
            vectors=np.asarray(vectors,np.float32);times=np.asarray(times,np.float32);labels=np.asarray(labels,np.int8)
            np.savez_compressed(path,vectors=vectors,times=times,labels=labels)
        begin=len(x)
        for j,(vector,label,end) in enumerate(zip(vectors,labels,times)):
            # Keep positives dense; bound long natural negatives in training only.
            if label<0 or (row['split']=='train' and label==0 and j%train_stride):continue
            x.append(vector);y.append(label);split.append(row['split']);ends.append(end)
        records.append(dict(row,cache_file=str(path.resolve()),window_begin=begin,window_end=len(x),
            positive_windows=int(sum(labels==1)),negative_windows=int(sum(labels==0))))
        if index%50==0:print(json.dumps({'stage':'stream-features','utterances':index+1,'windows':len(x)}),flush=True)
    return np.asarray(x,np.float32),np.asarray(y,np.float32),np.asarray(split),np.asarray(ends,np.float32),records
