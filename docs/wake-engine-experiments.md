# Wake engine experiments

All model quality experiments use private offline PCM and reports. They do not
send commands, call a paid API or publish a diagnostic APK. Real handset timing,
continuous natural negative audio and battery tests remain separate requirements.

## Vosk streaming grammar

`scripts/evaluate_vosk_wake.py` replays the existing corpus and an optional TTS
manifest in 320-sample/20ms frames. It declares both grammar policies before
replay. The narrow grammar is `hey chat` plus `[unk]`; the contrast grammar also
includes `hey cat`, `hey chad`, `hey jack`, `hey pat`, `hey charles` and `hate
chatting`. A wake hypothesis must contain adjacent `hey chat` tokens. The
stability policy requires that hypothesis over four successive 20ms frames.

Normal partial text exposes the current hypothesis, allowing activation before
utterance endpointing. `SetPartialWords(true)` changes the partial path to a
delayed committed-word subset and should not be used for this low-latency policy.
The evaluator can measure that alternative explicitly, keeping both results.
Recognition output may retract a previous partial: stability is a measured
candidate policy rather than a guarantee about ambiguous speech.

The official `vosk-model-small-en-us-0.15.zip` is 41,205,931 bytes, SHA256
`30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498`.
The [official model catalog](https://alphacephei.com/vosk/models) lists Apache-2.0
and supports dynamic vocabulary for this small English model. The benchmark
uses `vosk==0.3.45` in a separate environment. Keep downloaded models outside the
public checkout. Its broad speech recognizer has a larger memory/runtime cost
than a tiny keyword classifier; host CPU figures do not establish phone battery
life. The [recognizer source](https://github.com/alphacep/vosk-api/blob/master/src/recognizer.cc)
defines the distinction between normal and timestamped partial results.

## Voicute portability review

The [public Voicute repository](https://github.com/voicute/onnx-wakeword) was
inspected at commit `4a46a06d06112034ccd698c19fd5432f8a9f0a67`.
Its Android engine uses float PCM, the mel transform `/10+2` and a classifier
with `[1,mel_time,n_mels]` input. The English metadata selects 98 frames, 32 mel
bins and three consecutive positive frames. This is an alternative classifier
contract, not a drop-in match for this app's `[1,1,196,32]` CNN or compressed
embedding head.

Public English assets target Hey Friday/Hey Jarvis. No public Hey Chat asset or
training implementation was found in that pinned tree. Custom training points
to the vendor's website. The tree had no explicit license file/SPDX grant and
GitHub reported no license metadata. No vendor account was created and no
model was adopted. Public source access alone does not establish redistribution
terms for an APK.

## Audio retention and transport

`scripts/evaluate_voice_transport.py` compiles the actual production
`VoiceSocket`, `BufferedCapture` and `PcmRingBuffer` against minimal JVM Android
shims and a supplied `org.json` JAR. It never starts a network connection.
`tests/jvm/VoiceTransportHarness.java` checks exact PCM order across delayed
reader/connection readiness, irregular frame fragments, preack backup recording,
stop ordering and the explicit memory bound.

The recorder retains two seconds before a wake trigger. Once capture begins,
its command recording retains subsequent audio even during an unacknowledged
live connection. A trigger later than that two-second prefix cannot recover
earlier speech; increasing the network queue does not change this boundary.

The previous 500-message queue with 20ms continuation frames overflowed at
9.82 seconds after a two-second initial prefix. The updated transport combines
PCM into 100ms packets and caps total queued PCM at 60 seconds. The extra control
slot lets stop follow the final partial audio packet without losing its tail.
Start declares the actual queued duration in `buffered_audio_seconds`, including
the partial packet, so the server can allow a bounded initial burst after TLS
connection establishment. Overflow before acknowledgement keeps the separate
capture backup; acknowledged failures retain the existing uncertain-action
semantics and are not automatically replayed.
