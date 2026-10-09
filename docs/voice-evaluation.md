# Voice evaluation

Record request/capture/transcription/queue acceptance separately. Use isolated
replays for parser and buffering regression, then test the actual paired handset
for quiet/noisy wake accuracy, locked service lifetime and battery impact.
Configured cloud transcription uses protected voice configuration and its budget.
Legacy server-local Whisper/Piper benchmarking scripts were removed with the old
stack. Wake-training synthesis remains an independent offline development tool;
its generated private fixtures must never be published.
