"""Bounded, private wake-classifier experiment with frozen openWakeWord features.

Uses local Piper multispeaker synthesis and a small NumPy neural head. No paid
API calls; no assistant intents. Real command/no-wake test families are never
training or threshold-selection data. Outputs are experimental, not deployment
approval. Install dependencies in the coding-workbench task environment.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request
import wave

os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ.setdefault("OMP_NUM_THREADS", "4")
import numpy as np
import onnx
from onnx import helper, numpy_helper, TensorProto
import onnxruntime as ort
from openwakeword.utils import AudioFeatures
import openwakeword
from piper import PiperVoice, SynthesisConfig
from threadpoolctl import threadpool_limits

RATE = 16000
LENGTH = 32000
NEGATIVES = [
    "Hey Jack", "Hey cat", "Hey Chad", "Hey Pat", "Hey Matt", "Hey dad",
    "Hey chap", "Hey chef", "Hey there", "I hate chatting", "I hate chats",
    "He chats", "We chat", "They chatted", "Check that", "The cashier said hello",
    "Add bananas", "Buy sparkling water", "Set an alarm", "Find the latest invoice",
    "Check the calendar", "Read the email", "Where are my keys", "Open the window",
    "Close the door", "Coffee is ready", "The phone is charging", "Please check it",
    "Have a nice day", "Wait a minute", "The train is late", "Watch out",
    "I should buy milk", "How much does it cost", "Can you hear me",
    "This is quite noisy", "What's for dinner", "Let's go shopping", "Hate that",
    "A chat", "Great job", "The weather is cloudy", "Call me tomorrow",
    "Write it down", "Forget about it", "That's enough", "Keep going",
]
POSITIVES = ["Hey Chat", "Hey Chat, add bananas", "Hey Chat, check my calendar",
             "Hey Chat, find an email", "Hey Chat, set an alarm", "Hey Chat, what is next"]


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def reset_features(features):
    """Match the deterministic Android cold state without random dummy inference."""
    features.raw_data_buffer.clear(); features.melspectrogram_buffer=np.ones((76,32))
    features.accumulated_samples=0; features.raw_data_remainder=np.empty(0,np.int16)
    features.feature_buffer=np.zeros((16,96),np.float32)


def wav_read(path):
    with wave.open(str(path), "rb") as stream:
        assert stream.getsampwidth() == 2 and stream.getnchannels() == 1
        values = np.frombuffer(stream.readframes(stream.getnframes()), "<i2").astype(np.float32)
        rate = stream.getframerate()
    if rate != RATE:
        values = np.interp(np.arange(round(len(values) * RATE / rate)) * rate / RATE,
                           np.arange(len(values)), values).astype(np.float32)
    return values


def wav_write(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(RATE)
        stream.writeframes(np.clip(values, -32768, 32767).astype("<i2").tobytes())


def crop(values):
    energy = np.array([np.sqrt(np.mean(values[i:i+160]**2)) for i in range(0, len(values), 160)])
    active = np.flatnonzero(energy > max(80, float(energy.max()) * .06))
    if not len(active): return values
    return values[max(0, active[0] * 160 - 800):min(len(values), (active[-1]+1)*160+800)]


def window(values, rng, variant):
    values = crop(values)
    speed = rng.uniform(.85, 1.18)
    values = np.interp(np.arange(round(len(values)/speed))*speed, np.arange(len(values)), values)
    if len(values) > LENGTH - 3200: values = values[:LENGTH - 3200]
    result = np.zeros(LENGTH, np.float32)
    start = int(rng.integers(0, LENGTH - len(values) + 1))
    result[start:start+len(values)] = values * rng.uniform(.45, 1.10)
    if variant % 4 in (1, 2):
        snr = 10 if variant % 4 == 2 else 18
        noise = rng.normal(size=LENGTH)
        noise = np.convolve(noise, [.15, .25, .25, .20, .15], "same")
        signal_rms = np.sqrt(np.mean(result**2))
        result += noise * signal_rms / max(np.sqrt(np.mean(noise**2)), 1e-9) / 10**(snr/20)
    if variant % 4 == 3:
        original = result.copy()
        for delay, gain in [(640, .2), (1280, .1), (2080, .05)]: result[delay:] += original[:-delay]*gain
    return np.clip(result, -32768, 32767).astype(np.int16)


def fetch_features(output):
    folder = output / "backbone"; folder.mkdir(exist_ok=True)
    for item in openwakeword.FEATURE_MODELS.values():
        url = item["download_url"].replace(".tflite", ".onnx")
        path = folder / url.split("/")[-1]
        if not path.exists():
            temporary = path.with_suffix(".part")
            for attempt in range(3):
                try:
                    urllib.request.urlretrieve(url, temporary)
                    ort.InferenceSession(str(temporary), providers=["CPUExecutionProvider"])
                    temporary.replace(path); break
                except Exception:
                    if attempt == 2: raise
    return AudioFeatures(melspec_model_path=str(folder/"melspectrogram.onnx"),
                         embedding_model_path=str(folder/"embedding_model.onnx"),
                         inference_framework="onnx", ncpu=2)


def features_for(clips, features, output):
    matrices = []; labels = []; splits = []
    for offset in range(0, len(clips), 64):
        batch = clips[offset:offset+64]
        pcm = np.stack([wav_read(output/x["path"]).astype(np.int16) for x in batch])
        values = features.embed_clips(pcm, batch_size=64, ncpu=2)
        if values.shape[1:] != (16, 96): raise ValueError(f"Unexpected feature shape {values.shape}")
        matrices.append(values); labels.extend(x["positive"] for x in batch); splits.extend(x["split"] for x in batch)
    return np.concatenate(matrices).astype(np.float32), np.asarray(labels, np.float32), np.asarray(splits)


def sigmoid(x): return 1 / (1 + np.exp(-np.clip(x, -30, 30)))


def predict(x, params):
    normalized = (x.reshape(len(x), -1)-params["mean"])/params["scale"]
    hidden = np.maximum(0, normalized@params["w1"]+params["b1"])
    return sigmoid(hidden@params["w2"]+params["b2"]).reshape(-1)


def train(x, y, split, rng, deadline, epochs, width=32, stream_dev=None):
    train_mask = split == "train"; dev_mask = split == "dev"
    values = x[train_mask].reshape(sum(train_mask), -1)
    params = {"mean": values.mean(axis=0), "scale": np.maximum(values.std(axis=0), .1),
              "w1": rng.normal(0, 1/np.sqrt(1536), (1536, width)).astype(np.float32),
              "b1": np.zeros(width, np.float32), "w2": rng.normal(0, .1, (width, 1)).astype(np.float32),
              "b2": np.zeros(1, np.float32)}
    values = (values-params["mean"])/params["scale"]; targets = y[train_mask,None]
    stream_values=None
    if stream_dev is not None:
        stream_values=(stream_dev['vectors'].reshape(len(stream_dev['vectors']),-1)-params['mean'])/params['scale']
    moments = {key: np.zeros_like(params[key]) for key in ("w1", "b1", "w2", "b2")}
    variances = {key: np.zeros_like(params[key]) for key in moments}; step = 0
    best = None; best_score = (-1., -1.); history = []
    positive_indices=np.flatnonzero(targets.reshape(-1)>.5);negative_indices=np.flatnonzero(targets.reshape(-1)<.5)
    hard_negative_indices=negative_indices
    for epoch in range(epochs):
        if time.monotonic() >= deadline: break
        if stream_dev is None:
            batches=np.array_split(rng.permutation(len(values)),max(1,len(values)//128))
        else:
            if epoch%5==0:
                negative_scores=sigmoid(np.maximum(0,values[negative_indices]@params['w1']+params['b1'])@params['w2']+params['b2']).reshape(-1)
                hard_negative_indices=negative_indices[np.argsort(negative_scores)[-max(1,len(negative_indices)//10):]]
            batches=[]
            for positives in np.array_split(rng.permutation(positive_indices),max(1,len(positive_indices)//64)):
                negatives=np.concatenate([rng.choice(hard_negative_indices,size=len(positives)),rng.choice(negative_indices,size=2*len(positives))])
                batches.append(rng.permutation(np.concatenate([positives,negatives])))
        for indices in batches:
            a = values[indices]; truth = targets[indices]; hidden = np.maximum(0, a@params["w1"]+params["b1"])
            probability = sigmoid(hidden@params["w2"]+params["b2"])
            error = (probability-truth) * np.where(truth > .5, np.float32(1.), np.float32(2.)) / len(indices)
            delta = (error@params["w2"].T) * (hidden > 0)
            gradients = {"w2": hidden.T@error, "b2": error.sum(axis=0), "w1": a.T@delta, "b1": delta.sum(axis=0)}
            step += 1
            for key, gradient in gradients.items():
                gradient += 3e-4 * params[key]
                moments[key] = .9*moments[key]+.1*gradient
                variances[key] = .999*variances[key]+.001*gradient**2
                params[key] -= .001 * (moments[key]/(1-.9**step)) / (np.sqrt(variances[key]/(1-.999**step))+1e-8)
        dev = predict(x[dev_mask], params); dev_y = y[dev_mask]
        if stream_dev is None:
            threshold = max(.20, float(dev[dev_y==0].max())+.01)
            recall = float(np.mean(dev[dev_y==1] >= threshold))
        else:
            stream_scores=sigmoid(np.maximum(0,stream_values@params['w1']+params['b1'])@params['w2']+params['b2']).reshape(-1)
            wanted=[];unwanted=[]
            for row in stream_dev['bounds']:
                scores=stream_scores[row['begin']:row['end']];labels=row['labels']
                if row['wake_expected']:
                    wanted.append(float(scores[labels==1].max()) if np.any(labels==1) else 0.)
                    if np.any(labels==0):unwanted.append(float(scores[labels==0].max()))
                else:unwanted.append(float(scores.max()))
            # Work in finite logit space: adding a fixed probability margin near
            # one can create an impossible threshold above1 due to saturation.
            unwanted_array=np.clip(np.asarray(unwanted,np.float64),1e-12,1-1e-12)
            threshold_logit=float(np.log(unwanted_array/(1-unwanted_array)).max())+.01
            threshold=float(sigmoid(np.asarray(threshold_logit,np.float64)))
            recall=float(np.mean(np.asarray(wanted)>=threshold))
        loss = float(-np.mean(dev_y*np.log(dev+1e-8)+(1-dev_y)*np.log(1-dev+1e-8)))
        history.append({"epoch": epoch+1, "threshold": threshold, "recall": recall, "loss": loss,
                        "calibration":"per-utterance streaming maxima" if stream_dev is not None else "single offline windows"})
        if epoch%5==0:print(json.dumps({'stage':'epoch','epoch':epoch+1,'dev_recall':recall,'threshold':threshold}),flush=True)
        if (recall, -loss) > best_score:
            best_score = (recall, -loss); best = {key: value.copy() for key, value in params.items()}; selected_threshold = threshold
    if best is None: raise TimeoutError("No completed training epoch before deadline")
    return best, selected_threshold, history


def development_streams(records):
    vectors=[];bounds=[];cursor=0
    for row in records:
        if row['split']!='dev':continue
        data=np.load(row['cache_file']);values=data['vectors'].astype(np.float32)
        bounds.append({'begin':cursor,'end':cursor+len(values),'labels':data['labels'],
                       'wake_expected':row['wake_expected'],'source_group':row['source_group'],'duration':row['duration']})
        vectors.append(values);cursor+=len(values)
    return {'vectors':np.concatenate(vectors),'bounds':bounds}


def summarize_streams(records,params,threshold):
    rows=[]
    for row in records:
        saved=np.load(row['cache_file']);scores=predict(saved['vectors'].astype(np.float32),params);labels=saved['labels'];times=saved['times']
        wanted=float(scores[labels==1].max()) if np.any(labels==1) else None
        unwanted=float(scores[labels==0].max()) if np.any(labels==0) else None
        active=[];last=-100.
        for score,end in zip(scores,times):
            if score>=threshold and float(end)-last>=3.:
                active.append(float(end));last=float(end)
        rows.append({key:row[key] for key in ['source_group','split','wake_expected','duration']} | {
            'kind':row.get('kind','matched-synthetic'),'desired_max':wanted,'unwanted_max':unwanted,
            'max_score':float(scores.max()),'activations':active,
            'detected_complete_wake':wanted is not None and wanted>=threshold,
            'false_activation':unwanted is not None and unwanted>=threshold})
    return rows


def export(params, output):
    nodes = [helper.make_node("Flatten", ["input"], ["flat"], axis=1),
             helper.make_node("Sub", ["flat", "mean"], ["centered"]),
             helper.make_node("Div", ["centered", "scale"], ["normalized"]),
             helper.make_node("MatMul", ["normalized", "w1"], ["dense1"]),
             helper.make_node("Add", ["dense1", "b1"], ["biased1"]),
             helper.make_node("Relu", ["biased1"], ["hidden"]),
             helper.make_node("MatMul", ["hidden", "w2"], ["dense2"]),
             helper.make_node("Add", ["dense2", "b2"], ["logit"]),
             helper.make_node("Sigmoid", ["logit"], ["wake_probability"])]
    graph = helper.make_graph(nodes, "experimental_hey_chat", [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1,16,96])],
        [helper.make_tensor_value_info("wake_probability", TensorProto.FLOAT, [1,1])],
        [numpy_helper.from_array(value.astype(np.float32), key) for key, value in params.items()])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)], ir_version=8)
    onnx.checker.check_model(model); onnx.save(model, output / "hey_chat.onnx")
    return ort.InferenceSession(str(output/"hey_chat.onnx"), providers=["CPUExecutionProvider"])


def evaluate_real(corpus, features, head, threshold):
    manifest = json.loads((corpus/"manifest.json").read_text()); rows = []
    for item in manifest["clips"]:
        reset_features(features)
        pcm = wav_read(corpus/item["path"]).astype(np.int16)
        # Warm up with zero audio so initialization random noise is overwritten.
        data = np.concatenate([np.zeros(48000, np.int16), pcm, np.zeros(16000, np.int16)])
        scores = []; activations = []; started = time.monotonic()
        for offset in range(0,len(data),1280):
            chunk = data[offset:offset+1280]
            if len(chunk) < 1280: chunk = np.pad(chunk, (0,1280-len(chunk)))
            features(chunk); vector = features.get_features(16)
            score = float(head.run(None,{"input": vector})[0][0,0])
            if offset >= 48000:
                scores.append(score)
                if score >= threshold: activations.append(round((offset+1280-48000)/RATE, 3))
        rows.append(dict(item, max_score=max(scores), detected=bool(activations),
                         first_activation_seconds=activations[0] if activations else None,
                         replay_seconds=round(time.monotonic()-started,3)))
    return rows


def run(args):
    start = time.monotonic(); deadline = start + args.max_seconds
    out = args.output; out.mkdir(parents=True,exist_ok=True)
    rng = np.random.default_rng(args.seed); ort.set_seed(args.seed)
    features = fetch_features(out)
    voice = PiperVoice.load(args.voice_model)
    print(json.dumps({"stage":"synthesis","speakers":args.speakers,"seed":args.seed}),flush=True)
    # Avoid default ONNX thread fanout competing with existing assistant services.
    opts = ort.SessionOptions(); opts.intra_op_num_threads = 2; opts.inter_op_num_threads = 1
    voice.session = ort.InferenceSession(str(args.voice_model), sess_options=opts, providers=["CPUExecutionProvider"])
    ids = rng.choice(voice.config.num_speakers, size=args.speakers, replace=False).tolist()
    dev_ids = set(ids[-max(4,args.speakers//6):]); clips = []
    for speaker in ids:
        for index in range(args.per_speaker):
            if time.monotonic() >= deadline: raise TimeoutError("Dataset generation deadline; cached clips retained")
            positive = index % 3 == 0
            text = POSITIVES[(index//3)%len(POSITIVES)] if positive and args.context else "Hey Chat" if positive else NEGATIVES[int(rng.integers(len(NEGATIVES)))]
            group = f"libritts-speaker-{speaker}-{index}"; source = out/"sources"/(group+".wav")
            length_scale = float(rng.uniform(.85,1.15))
            if not source.exists():
                chunks = list(voice.synthesize(text, SynthesisConfig(speaker_id=speaker, length_scale=length_scale)))
                values = np.concatenate([chunk.audio_float_array for chunk in chunks])*32767
                rate = chunks[0].sample_rate
                values = np.interp(np.arange(round(len(values)*RATE/rate))*rate/RATE,np.arange(len(values)),values)
                wav_write(source,values)
            values = wav_read(source)
            for variant in range(args.variants):
                path = f"windows/{group}-{variant}.wav"; wav_write(out/path,window(values,rng,variant))
                clips.append({"path":path,"positive":positive,"split":"dev" if speaker in dev_ids else "train",
                              "source_group":group,"speaker":speaker,"text":text,"variant":variant,"source_sha256":sha(source)})
    # Only isolated personal wakes enter training. All command and no-wake test
    # families stay held out, including their descendants and duplicate reuploads.
    for path in sorted((args.corpus/"wake-model/templates").glob("*.wav")):
        values=wav_read(path)
        negatives=[r for r in clips if not r["positive"] and r["split"]=="train"]
        for variant in range(args.real_variants):
            example=values
            if args.context and variant%3:
                context=wav_read(out/negatives[int(rng.integers(len(negatives)))]["path"])
                # Context is temporally concatenated, never mixed over the wake.
                example=np.concatenate([context[8000:12000]*.7,values,context[12000:18000]*.7])
            destination=f"windows/personal-{path.stem}-{variant}.wav";wav_write(out/destination,window(example,rng,variant))
            clips.append({"path":destination,"positive":True,"split":"train","source_group":path.stem,"variant":variant,"source_sha256":sha(path)})
    (out/"training-manifest.json").write_text(json.dumps({"seed":args.seed,"speakers":ids,"dev_speakers":sorted(dev_ids),"clips":clips,
        "voice_source":"https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/libritts_r/medium",
        "voice_dataset_license":"CC BY 4.0, LibriTTS-R","voice_model_sha256":sha(args.voice_model)},indent=2))
    print(json.dumps({"stage":"features","windows":len(clips)}),flush=True)
    x,y,split=features_for(clips,features,out);np.savez_compressed(out/"training-features.npz",x=x,y=y,split=split)
    print(json.dumps({"stage":"training","feature_shape":list(x.shape)}),flush=True)
    params,threshold,history=train(x,y,split,rng,deadline,args.epochs,args.head_width)
    head=export(params,out)
    print(json.dumps({"stage":"replay","threshold":threshold}),flush=True)
    # ONNX serialization must reproduce the actual NumPy head.
    for sample in x[:5]:
        actual=float(head.run(None,{"input":sample[None]})[0][0,0]);expected=float(predict(sample[None],params)[0])
        if abs(actual-expected)>1e-5:raise AssertionError("Exported head mismatch")
    rows=evaluate_real(args.corpus,features,head,threshold)
    report={"experimental":True,"acceptance_passed":False,"elapsed_seconds":round(time.monotonic()-start,2),
        "threshold":threshold,"training_windows":len(clips),"synthetic_speakers":len(ids),"history":history,"samples":rows,
        "head_width":args.head_width,"one_take_training_context":args.context,
        "threshold_selection":"Single offline development windows; requires independent streaming calibration before deployment",
        "feature_contract":{"sample_rate":16000,"pcm":"int16 mono, raw scale","hop_samples":1280,"embedding_frames":16,"embedding_dimension":96,
            "melspec_window_frames":76,"melspec_bins":32,"embedding_hop_frames":8},
        "model_sha256":sha(out/"hey_chat.onnx"),"backbone_sha256":{p.name:sha(p) for p in (out/"backbone").glob("*.onnx")},
        "limitations":["Threshold/checkpoint selected on held-out synthetic speakers, not real test commands",
            "Single-window threshold does not bound false wakes over sliding audio windows; streaming dev calibration is required",
            "Small real test set, no hours-long natural negative speech/music/noise acceptance",
            "Synthetic filtered noise/echo do not prove field reliability","No Android lifecycle/battery measurement"]}
    (out/"evaluation.json").write_text(json.dumps(report,indent=2))
    print(json.dumps({key:report[key] for key in ["elapsed_seconds","threshold","training_windows","synthetic_speakers"]}),flush=True)
    for split_name in ("template","held-out-real","synthetic-evaluation"):
        for kind in ("original","synthetic","augmented"):
            selected=[r for r in rows if r["split"]==split_name and r["kind"]==kind]
            if kind=="original":selected=list({r["source_group"]:r for r in selected}.values())
            if selected:print(json.dumps({"split":split_name,"kind":kind,"positives":sum(r["wake_expected"] for r in selected),
                "missed":sum(r["wake_expected"] and not r["detected"] for r in selected),"negatives":sum(not r["wake_expected"] for r in selected),
                "false_wakes":sum(not r["wake_expected"] and r["detected"] for r in selected)}),flush=True)


def run_streaming(args):
    from wake_training_data import prepare_librispeech,build_streams,cache_stream_features,validate_streams
    started=time.monotonic();deadline=started+args.max_seconds;out=args.output;out.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(args.seed);ort.set_seed(args.seed);features=fetch_features(out)
    natural=prepare_librispeech(args.natural_archive,args.natural_output,args.seed,
                               (args.natural_train_minutes,args.natural_dev_minutes,args.natural_test_minutes))
    print(json.dumps({'stage':'natural-negatives','seconds':natural['seconds_per_split']}),flush=True)
    voice=PiperVoice.load(args.voice_model);options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
    voice.session=ort.InferenceSession(str(args.voice_model),sess_options=options,providers=['CPUExecutionProvider'])
    streams=build_streams(voice,args.corpus,out,natural,rng,args.speakers,args.variants,args.real_variants)
    validate_streams(streams['clips'])
    # Natural test streams never enter the learning matrix or dev calibration.
    learning=[row for row in streams['clips'] if row['split'] in ['train','dev']]
    x,y,split,ends,records=cache_stream_features(learning,features,out,out/'stream-cache',args.train_stride)
    np.savez_compressed(out/'stream-training-features.npz',x=x,y=y,split=split,ends=ends)
    stream_dev=development_streams(records)
    print(json.dumps({'stage':'stream-training','windows':len(x),'dev_stream_windows':len(stream_dev['vectors'])}),flush=True)
    params,threshold,history=train(x,y,split,rng,deadline,args.epochs,args.head_width,stream_dev)
    head=export(params,out);np.savez(out/'head-parameters.npz',**params)
    for sample in x[:5]:
        if abs(float(head.run(None,{'input':sample[None]})[0][0,0])-float(predict(sample[None],params)[0]))>1e-5:
            raise AssertionError('NumPy/ONNX export mismatch')
    training_eval=summarize_streams(records,params,threshold)
    natural_test=[row for row in streams['clips'] if row['split']=='natural-test']
    _,_,_,_,test_records=cache_stream_features(natural_test,features,out,out/'stream-cache',args.train_stride)
    natural_eval=summarize_streams(test_records,params,threshold)
    real_eval=evaluate_real(args.corpus,features,head,threshold)
    summaries={}
    for name,rows in [('train',[r for r in training_eval if r['split']=='train']),
                      ('dev',[r for r in training_eval if r['split']=='dev']),('natural-test',natural_eval)]:
        positives=[r for r in rows if r['wake_expected']];negatives=[r for r in rows if not r['wake_expected']]
        seconds=sum(r['duration'] for r in negatives);events=sum(len(r['activations']) for r in negatives)
        summaries[name]={'utterances':len(rows),'positive_utterances':len(positives),'missed_complete_wakes':sum(not r['detected_complete_wake'] for r in positives),
            'negative_utterances':len(negatives),'negative_utterances_triggered':sum(r['false_activation'] for r in negatives),
            'negative_seconds':seconds,'false_events':events,'false_events_per_hour':events/(seconds/3600) if seconds else None}
    report={'experimental':True,'acceptance_passed':False,'threshold':threshold,'streaming_calibration':True,
        'threshold_selection':'per-utterance maxima on dev speakers only, including post-wake command-only windows',
        'elapsed_seconds':round(time.monotonic()-started,2),'history':history,'head_width':args.head_width,
        'training_windows':len(x),'stream_summaries':summaries,'stream_evaluation':training_eval,'natural_test':natural_eval,'samples':real_eval,
        'model_sha256':sha(out/'hey_chat.onnx'),'backbone_sha256':{p.name:sha(p) for p in (out/'backbone').glob('*.onnx')},
        'limitations':['No handset lifecycle/battery validation','Personal corpus is a regression suite already inspected in prior experiments; new blind field trials remain necessary',
            'Natural read speech does not cover crowded streets, music or wind','Real command and no-wake sources never enter learning or calibration']}
    (out/'evaluation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'stage':'completed','threshold':threshold,'elapsed_seconds':report['elapsed_seconds'],'summaries':summaries}),flush=True)
    for split_name in ['template','held-out-real','synthetic-evaluation']:
        for kind in ['original','synthetic','augmented']:
            rows=[r for r in real_eval if r['split']==split_name and r['kind']==kind]
            if kind=='original':rows=list({r['source_group']:r for r in rows}.values())
            if rows:print(json.dumps({'split':split_name,'kind':kind,'positive':sum(r['wake_expected'] for r in rows),
                'missed':sum(r['wake_expected'] and not r['detected'] for r in rows),'negative':sum(not r['wake_expected'] for r in rows),
                'false':sum(not r['wake_expected'] and r['detected'] for r in rows)}),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus",type=Path,required=True);parser.add_argument("--voice-model",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True);parser.add_argument("--speakers",type=int,default=48)
    parser.add_argument("--per-speaker",type=int,default=12);parser.add_argument("--variants",type=int,default=4)
    parser.add_argument("--epochs",type=int,default=60);parser.add_argument("--seed",type=int,default=1907)
    parser.add_argument("--max-seconds",type=int,default=600)
    parser.add_argument("--head-width",type=int,default=32);parser.add_argument("--real-variants",type=int,default=20)
    parser.add_argument("--context",action="store_true",help="Train wake plus following commands and non-overlapping context")
    parser.add_argument('--streaming',action='store_true',help='Corrected matched-context/streaming-calibration pipeline')
    parser.add_argument('--natural-archive',type=Path);parser.add_argument('--natural-output',type=Path)
    parser.add_argument('--natural-train-minutes',type=int,default=45);parser.add_argument('--natural-dev-minutes',type=int,default=15)
    parser.add_argument('--natural-test-minutes',type=int,default=15);parser.add_argument('--train-stride',type=int,default=4)
    args=parser.parse_args()
    if args.streaming and (args.natural_archive is None or args.natural_output is None):parser.error('Streaming requires natural archive and output paths')
    with threadpool_limits(limits=4):(run_streaming if args.streaming else run)(args)
