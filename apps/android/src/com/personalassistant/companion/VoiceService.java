package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.media.*;
import android.media.audiofx.*;
import android.net.*;
import android.os.*;
import android.speech.tts.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.*;

/** A single microphone producer feeds both wake detection and lossless pre-roll. */
public class VoiceService extends Service {
    static final String TALK="com.personalassistant.companion.TALK",STOP="com.personalassistant.companion.STOP_VOICE",START_CONVERSATION="com.personalassistant.companion.START_CONVERSATION",END_CONVERSATION="com.personalassistant.companion.END_CONVERSATION";
    private final AtomicBoolean running=new AtomicBoolean();private volatile boolean requestCapture,waiting,speaking,followup,conversationMode,cancelCapture;private volatile long conversationDeadline;
    private AudioRecord recorder;private Thread audioThread;private TextToSpeech tts;private volatile boolean ttsReady;private volatile String utteranceId;private PowerManager.WakeLock lock;private ConnectivityManager.NetworkCallback network;
    private String session=UUID.randomUUID().toString();private final Handler main=new Handler(Looper.getMainLooper());private volatile VoiceSocket live;private volatile boolean liveEnded,liveAcknowledged;private volatile String liveEndReason;private AudioTrack playback;private volatile boolean destroyed;private volatile long playbackGeneration,liveGeneration,turnGeneration;private final StringBuilder liveCaptions=new StringBuilder();private String captionRole="",captionId="",lastReceiptId="",lastReceiptStatus="";private final StringBuilder roleCaption=new StringBuilder();private final java.util.concurrent.ThreadPoolExecutor playbackExecutor=new java.util.concurrent.ThreadPoolExecutor(1,1,0,java.util.concurrent.TimeUnit.SECONDS,new java.util.concurrent.LinkedBlockingQueue<Runnable>());
    @Override public void onCreate(){super.onCreate();Cloud.prefs(this).edit().putBoolean("voice_conversation_mode",false).apply();tts=new TextToSpeech(this,status->ttsReady=status==TextToSpeech.SUCCESS);tts.setOnUtteranceProgressListener(new UtteranceProgressListener(){public void onStart(String id){if(id.equals(utteranceId))speaking=true;}public void onDone(String id){main.post(()->{if(destroyed||!id.equals(utteranceId))return;utteranceId=null;speaking=false;afterReply();});}public void onError(String id){onDone(id);}});
        network=new ConnectivityManager.NetworkCallback(){@Override public void onAvailable(Network n){if(!Cloud.prefs(VoiceService.this).getBoolean("voice_listening_test",false))VoiceOutbox.retry(VoiceService.this,null);}@Override public void onLost(Network n){if(VoiceOutbox.networkReady(VoiceService.this))return;VoiceSocket current=live;if(current!=null){liveEndReason=null;state("No internet · voice connection interrupted");current.disconnect();liveAcknowledged=current.acknowledged();liveEnded=true;state(liveAcknowledged?"Connection lost · check task notifications; use Talk to retry":"No internet · recording; command will be saved");}else state("No internet · listening locally; commands will be saved");}};((ConnectivityManager)getSystemService(CONNECTIVITY_SERVICE)).registerDefaultNetworkCallback(network);
    }
    @Override public int onStartCommand(Intent intent,int flags,int startId){
        if(intent!=null&&STOP.equals(intent.getAction())){Cloud.prefs(this).edit().putBoolean("wake_enabled",false).putBoolean("voice_listening_test",false).commit();stopSelf();return START_NOT_STICKY;}
        if(intent!=null&&END_CONVERSATION.equals(intent.getAction())){endConversation();return START_NOT_STICKY;}
        if(checkSelfPermission("android.permission.RECORD_AUDIO")!=android.content.pm.PackageManager.PERMISSION_GRANTED){state("Microphone permission required");stopSelf();return START_NOT_STICKY;}
        try{Notification notice=notification("Starting microphone…");if(Build.VERSION.SDK_INT>=29)startForeground(217,notice,ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);else startForeground(217,notice);
            if(intent!=null&&START_CONVERSATION.equals(intent.getAction())){setConversation(true);session=UUID.randomUUID().toString();}
            boolean task=taskStart(intent);
            if(intent!=null&&(task||TALK.equals(intent.getAction())||START_CONVERSATION.equals(intent.getAction()))){utteranceId=null;tts.stop();speaking=false;if(live!=null){playbackGeneration++;playbackExecutor.getQueue().clear();if(playback!=null)try{playback.pause();playback.flush();playback.play();}catch(Exception ignored){}state("Conversation mode · speak now");}else{if(!conversationMode)session=UUID.randomUUID().toString();requestCapture=true;followup=conversationMode;conversationDeadline=System.currentTimeMillis()+30000;}}
            if(running.compareAndSet(false,true)){lock=((PowerManager)getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"assistant:voice");lock.acquire();audioThread=new Thread(this::record,"assistant-microphone");audioThread.start();}
        }catch(Exception error){state("Microphone could not start: "+error.getMessage());stopSelf();}return START_NOT_STICKY;
    }
    /** Test subclasses may supply deterministic PCM; production always reads this recorder. */
    protected int readMicrophone(short[] frame){return recorder.read(frame,0,frame.length,AudioRecord.READ_BLOCKING);}
    WakeDetector loadDetector()throws Exception {
        for(String adapter:new String[]{"VoskWakeDetector","OpenWakeDetector","SherpaWakeDetector"}){
            try{Object optional=Class.forName("com.personalassistant.companion."+adapter).getMethod("create",android.content.Context.class).invoke(null,this);if(optional instanceof WakeDetector){WakeDetector candidate=(WakeDetector)optional;if(candidate.available()){Cloud.prefs(this).edit().remove("wake_runtime_error").commit();return candidate;}candidate.close();}}
            catch(ClassNotFoundException ignored){}
            catch(Exception error){Cloud.prefs(this).edit().putString("wake_runtime_error",adapter+" unavailable").commit();}
        }
        if(!Cloud.prefs(this).getBoolean("voice_template_experimental",false))return new WakeDetector(){public boolean accept(short[] frame,int n){return false;}public boolean available(){return false;}public String name(){return "Wake model unavailable";}public void reset(){}};TemplateWakeDetector detector=new TemplateWakeDetector();String[] files=getAssets().list("voice/templates");if(files!=null)for(String file:files)if(file.endsWith(".pcm")){ByteArrayOutputStream bytes=new ByteArrayOutputStream();try(InputStream in=getAssets().open("voice/templates/"+file)){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1){bytes.write(b,0,n);if(bytes.size()>64000)throw new IOException("Wake template too large");}}byte[] raw=bytes.toByteArray();short[] pcm=new short[raw.length/2];for(int i=0;i<pcm.length;i++)pcm[i]=(short)((raw[2*i]&255)|(raw[2*i+1]<<8));detector.add(pcm);}
        try(InputStream in=getAssets().open("voice/template.threshold")){byte[] value=new byte[32];int n=in.read(value);detector.threshold(Double.parseDouble(new String(value,0,n,"UTF-8").trim()));}catch(FileNotFoundException ignored){}return detector;
    }
    private void record(){synchronized(VoiceService.class){recordOwned();}}
    private void recordOwned(){BufferedCapture capture=new BufferedCapture(32000);NoiseSuppressor noise=null;AcousticEchoCanceler echo=null;WakeDetector detector=null;
        try{boolean wake=Cloud.prefs(this).getBoolean("wake_enabled",false);boolean wakeLoaded=wake;
            int minimum=AudioRecord.getMinBufferSize(16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT);if(minimum<0)throw new IOException("16 kHz microphone not supported");
            recorder=new AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION,16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT,Math.max(minimum,64000));if(recorder.getState()!=AudioRecord.STATE_INITIALIZED)throw new IOException("Microphone initialization failed");
            if(Build.VERSION.SDK_INT>=29)recorder.registerAudioRecordingCallback(getMainExecutor(),new AudioManager.AudioRecordingCallback(){@Override public void onRecordingConfigChanged(java.util.List<AudioRecordingConfiguration> configs){if(recorder==null)return;for(AudioRecordingConfiguration config:configs)if(config.getClientAudioSessionId()==recorder.getAudioSessionId()&&config.isClientSilenced()){state("Microphone interrupted by another app · reopen to resume");stopSelf();}}});
            // Recognition input retains quiet phonemes. Never suppress the local wake stream.
            if(NoiseSuppressor.isAvailable()){noise=NoiseSuppressor.create(recorder.getAudioSessionId());if(noise!=null)noise.setEnabled(false);}
            if(AcousticEchoCanceler.isAvailable()){echo=AcousticEchoCanceler.create(recorder.getAudioSessionId());if(echo!=null)echo.setEnabled(false);}if(!running.get())return;Cloud.prefs(this).edit().putLong("voice_recorder_start_request_ns",SystemClock.elapsedRealtimeNanos()).apply();recorder.startRecording();Cloud.prefs(this).edit().putBoolean("voice_mic_active",true).putLong("voice_mic_ready_ns",SystemClock.elapsedRealtimeNanos()).apply();if(wake)state("Preparing Hey Chat listening…");
            detector=wake?loadDetector():new DisabledWakeDetector();if(wake&&!detector.available()){state("Wake model not installed · use Talk");wake=false;if(!requestCapture){main.post(this::stopSelf);return;}}Cloud.prefs(this).edit().putString("wake_detector",detector.name()).commit();
            WakeStreamGate wakeStream=new WakeStreamGate(detector);boolean firstPcm=true;short[] frame=new short[320];int quiet=0,voiced=0,elapsed=0,zeros=0;double noiseFloor=40;long lastMetrics=0,testCooldown=0;boolean wasTest=false,echoEnabled=false;ArrayDeque<Double> ambient=new ArrayDeque<>();state(wake?"Listening locally for Hey Chat · experimental":"Ready for voice");
            while(running.get()){
                if(Cloud.prefs(this).getBoolean("wake_enabled",false)&&!wakeLoaded&&!capture.active()&&live==null&&!speaking&&!waiting){state("Preparing Hey Chat listening…");detector.close();detector=loadDetector();wakeStream=new WakeStreamGate(detector);wakeLoaded=true;Cloud.prefs(this).edit().putString("wake_detector",detector.name()).commit();state(detector.available()?"Listening locally for Hey Chat · experimental":"Wake model not installed · use Talk");}
                wake=Cloud.prefs(this).getBoolean("wake_enabled",false)&&detector.available();
                boolean testing=Cloud.prefs(this).getBoolean("voice_listening_test",false);
                if(testing&&!wasTest){liveGeneration++;turnGeneration++;if(live!=null)live.disconnect();live=null;liveEnded=false;capture.cancel();requestCapture=false;waiting=speaking=followup=false;setConversation(false);utteranceId=null;tts.stop();wakeStream.pause();state("Local wake test · say Hey Chat");}wasTest=testing;
                if(detector instanceof VoskWakeDetector)((VoskWakeDetector)detector).sensitivity("sensitive".equals(Cloud.prefs(this).getString("wake_sensitivity","balanced")));
                boolean useEcho=live!=null||speaking;if(echo!=null&&useEcho!=echoEnabled){echo.setEnabled(useEcho);echoEnabled=useEcho;}
                int n=readMicrophone(frame);if(n<0)throw new IOException("Microphone interrupted ("+n+")");if(n==0){if(++zeros>100)throw new IOException("Microphone unavailable");continue;}zeros=0;if(firstPcm){firstPcm=false;Cloud.prefs(this).edit().putLong("voice_first_pcm_ns",SystemClock.elapsedRealtimeNanos()).apply();}
                if(cancelCapture){cancelCapture=false;capture.cancel();wakeStream.pause();}
                double sum=0;for(int i=0;i<n;i++)sum+=(double)frame[i]*frame[i];double rms=Math.sqrt(sum/n);
                long now=SystemClock.elapsedRealtime();if(now-lastMetrics>=200){lastMetrics=now;float level=(float)Math.max(0,Math.min(1,(20*Math.log10(Math.max(1,rms)/32768.0)+60)/50));String partial=detector instanceof VoskWakeDetector?((VoskWakeDetector)detector).partial():"";Cloud.prefs(this).edit().putFloat("voice_level",level).putLong("voice_metrics_elapsed",now).putString("voice_last_partial",partial).putBoolean("voice_conversation_active",!testing&&(capture.active()||live!=null||waiting||speaking||followup)).apply();}
                if(liveEnded){liveEnded=false;live=null;followup=false;if(!liveAcknowledged&&capture.active()){quiet=0;voiced=6400;elapsed=capture.size();state("Connection lost · still recording; command will be saved after a pause");}else{capture.cancel();setConversation(false);state(liveEndReason==null?"Connection lost · check requests; use Talk to retry":liveEndReason);if(!wake){main.post(this::stopSelf);break;}}}
                if(speaking||waiting){wakeStream.pause();capture.cancel();continue;}
                VoiceSocket activeLive=live;
                if(activeLive!=null){wakeStream.pause();activeLive.audio(frame,n);if(!activeLive.acknowledged()&&capture.size()<1440000)capture.ingest(frame,n);else if(activeLive.acknowledged())capture.cancel();continue;}
                capture.ingest(frame,n);boolean speech=CaptureSpeechGate.speech(rms,noiseFloor);
                if(!capture.active()&&!followup){ambient.add(rms);if(ambient.size()>150)ambient.removeFirst();if(ambient.size()>=20&&ambient.size()%5==0){Double[] levels=ambient.toArray(new Double[0]);Arrays.sort(levels);noiseFloor=Math.max(20,levels[levels.length/5]);}else if(!speech)noiseFloor=0.995*noiseFloor+0.005*rms;}
                if(!capture.active()){
                    boolean trigger=!testing&&requestCapture;requestCapture=false;
                    if(!testing&&!trigger&&followup&&System.currentTimeMillis()<conversationDeadline&&speech)trigger=true;
                    if(followup&&System.currentTimeMillis()>=conversationDeadline){followup=false;setConversation(false);session=UUID.randomUUID().toString();if(!wake){main.post(this::stopSelf);break;}state("Listening locally for Hey Chat · experimental");}
                    boolean detected=!trigger&&wake&&now>=testCooldown&&wakeStream.accept(frame,n);
                    if(testing){if(detected){testCooldown=now+2000;wakeStream.pause();capture.cancel();main.post(()->{if(destroyed)return;rememberWake();((Vibrator)getSystemService(VIBRATOR_SERVICE)).vibrate(VibrationEffect.createOneShot(40,VibrationEffect.DEFAULT_AMPLITUDE));state("Heard Hey Chat · local test");});}continue;}
                    if(trigger||detected){long wakeClock=SystemClock.elapsedRealtimeNanos();wakeStream.pause();capture.begin(detected||followup);turnGeneration++;if(!conversationMode)session=UUID.randomUUID().toString();long captureClock=SystemClock.elapsedRealtimeNanos();android.content.SharedPreferences.Editor clocks=Cloud.prefs(this).edit().putLong("voice_capture_started_ns",captureClock);if(detected)clocks.putLong("voice_wake_detected_ns",wakeClock);clocks.apply();quiet=elapsed=0;voiced=detected?6400:0;followup=false;captureTask=taskTarget;captureDictation=taskDictation;if(taskDictation){taskTarget=null;taskDictation=false;}final boolean acknowledgeWake=detected;main.post(()->{if(destroyed)return;if(acknowledgeWake){rememberWake();((Vibrator)getSystemService(VIBRATOR_SERVICE)).vibrate(VibrationEffect.createOneShot(25,VibrationEffect.DEFAULT_AMPLITUDE));}if(!waiting&&!speaking&&live==null)state("Listening to your command…");});if(conversationMode&&captureTask==null&&!Cloud.prefs(this).getBoolean("voice_preview",false)&&VoiceOutbox.networkReady(this))startLive(capture.snapshot());}
                }else{
                    wakeStream.pause();elapsed+=n;if(speech){voiced+=n;quiet=0;}else quiet+=n;
                    if((voiced>=6400&&quiet>=19200)||elapsed>=480000){short[] pcm=capture.finish();waiting=true;state("Sending voice command…");submit(pcm);}
                    else if(elapsed>=128000&&voiced<6400){capture.cancel();taskDropped(wake);state(wake?"Listening locally for Hey Chat · experimental":"No speech heard");if(!wake){main.post(this::stopSelf);break;}}
                }
            }
        }catch(Exception error){if(running.get())state("Voice stopped: "+error.getMessage());main.post(this::stopSelf);}finally{running.set(false);Cloud.prefs(this).edit().putBoolean("voice_mic_active",false).putBoolean("voice_conversation_active",false).putFloat("voice_level",0f).apply();if(detector!=null)detector.close();if(noise!=null)noise.release();if(echo!=null)echo.release();if(recorder!=null){try{recorder.stop();}catch(Exception ignored){}recorder.release();recorder=null;}if(lock!=null&&lock.isHeld())lock.release();}
    }
    synchronized void startLive(short[] prefix){
        if(!conversationMode||destroyed||Cloud.prefs(this).getBoolean("voice_listening_test",false))return;
        final long generation=++liveGeneration;
        liveEndReason=null;liveCaptions.setLength(0);roleCaption.setLength(0);captionRole=captionId=lastReceiptId=lastReceiptStatus="";
        playbackGeneration++;playbackExecutor.getQueue().clear();liveAcknowledged=false;liveEnded=false;state("Connecting conversation…");
        VoiceSocket socket=new VoiceSocket(this,new VoiceSocket.Listener(){
            public void event(JSONObject event){
                if(destroyed||generation!=liveGeneration||Cloud.prefs(VoiceService.this).getBoolean("voice_listening_test",false))return;
                String type=event.optString("type");
                if("ready".equals(type)){liveAcknowledged=true;state("Conversation mode · microphone active");}
                else if("audio".equals(type)){
                    try{byte[] pcm=android.util.Base64.decode(event.getString("audio"),android.util.Base64.DEFAULT);long audioGeneration=playbackGeneration;
                        playbackExecutor.execute(()->{try{if(destroyed||audioGeneration!=playbackGeneration)return;
                            if(playback==null){int size=AudioTrack.getMinBufferSize(16000,AudioFormat.CHANNEL_OUT_MONO,AudioFormat.ENCODING_PCM_16BIT);playback=new AudioTrack.Builder().setAudioAttributes(new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()).setAudioFormat(new AudioFormat.Builder().setSampleRate(16000).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).setEncoding(AudioFormat.ENCODING_PCM_16BIT).build()).setBufferSizeInBytes(Math.max(size,6400)).setTransferMode(AudioTrack.MODE_STREAM).build();playback.play();}
                            playback.write(pcm,0,pcm.length,AudioTrack.WRITE_BLOCKING);
                        }catch(Exception e){state("Speaker unavailable · conversation text remains available");}});
                    }catch(Exception ignored){}
                }
                else if("playback_reset".equals(type))clearPlayback();
                else if("transcript".equals(type)){
                    String role=event.optString("role","assistant");
                    String entryId=event.optString("id",session+":"+role);
                    if(!role.equals(captionRole)||!entryId.equals(captionId)){if(liveCaptions.length()>0)liveCaptions.append("\n");liveCaptions.append("user".equals(role)?"You: ":"Assistant: ");captionRole=role;captionId=entryId;roleCaption.setLength(0);}
                    String delta=event.optString("text");liveCaptions.append(delta);roleCaption.append(delta);
                    if(roleCaption.length()>8000)roleCaption.delete(0,roleCaption.length()-8000);
                    if(liveCaptions.length()>8000){int cut=liveCaptions.indexOf("\n",liveCaptions.length()-8000);liveCaptions.delete(0,cut>=0?cut+1:liveCaptions.length()-8000);}
                    if("user".equals(role))VoiceChat.user(VoiceService.this,entryId,roleCaption.toString(),System.currentTimeMillis());
                    else if(entryId.equals(lastReceiptId))VoiceChat.assistant(VoiceService.this,entryId,roleCaption.toString(),System.currentTimeMillis(),("queued".equals(lastReceiptStatus)||"running".equals(lastReceiptStatus))?"acknowledgement":"answer",lastReceiptId);
                    else VoiceChat.assistant(VoiceService.this,entryId,roleCaption.toString(),System.currentTimeMillis());
                    Cloud.prefs(VoiceService.this).edit().putString("voice_transcript",liveCaptions.toString()).putString("user".equals(role)?"voice_user_text":"voice_reply",roleCaption.toString()).apply();
                    sendBroadcast(new Intent("com.personalassistant.companion.VOICE_STATE").setPackage(getPackageName()));
                }
                else if("error".equals(type))state(event.optString("message","Conversation unavailable"));
                else if("closed".equals(type)){if("session_time_limit".equals(event.optString("reason")))liveEndReason="Conversation time limit reached · say Hey Chat to start again";}
                else if("status".equals(type)){
                    rememberReceipt(event,event.optString("task_id",session));
                    if(event.optBoolean("grocery_changed",false))VoiceOutbox.refreshGroceries(VoiceService.this);
                    if("ended".equals(event.optString("status"))){
                        String reply=event.optString("reply","Conversation ended.");endConversation(false);state(reply);speakReply(reply);return;
                    }
                    state(event.optString("reply",event.optString("message",event.optString("status","Conversation mode"))));
                }
            }
            public void closed(String message,boolean acknowledged){if(destroyed||generation!=liveGeneration)return;liveAcknowledged=acknowledged;liveEnded=true;state(message);}
        });live=socket;socket.start(prefix);
    }
    protected void submit(short[] pcm){
        if(Cloud.prefs(this).getBoolean("voice_listening_test",false)){waiting=false;return;}
        if(captureTask!=null){taskSubmit(pcm);return;}
        final long generation=turnGeneration;
        try{
            String commandId=VoiceOutbox.save(this,pcm,session,Cloud.prefs(this).getBoolean("voice_preview",false));VoiceRetryJob.schedule(this);
            if(!VoiceOutbox.networkReady(this)){waiting=false;followup=false;setConversation(false);state("No internet · voice command saved on this phone");if(!Cloud.prefs(this).getBoolean("wake_enabled",false))main.post(this::stopSelf);return;}
            VoiceOutbox.retry(this,commandId,new VoiceOutbox.Listener(){
                public void received(JSONObject response){main.post(()->{
                    if(destroyed||generation!=turnGeneration||Cloud.prefs(VoiceService.this).getBoolean("voice_listening_test",false))return;
                    acknowledge(response,commandId);
                });}
                public void unavailable(String message){main.post(()->{if(destroyed||generation!=turnGeneration)return;waiting=false;followup=false;setConversation(false);state("Cloud unavailable · command saved on this phone");if(!Cloud.prefs(VoiceService.this).getBoolean("wake_enabled",false))stopSelf();});}
            });
        }catch(Exception error){waiting=false;followup=false;setConversation(false);state("Audio could not be saved: "+error.getMessage());}
    }
    /** The same backend receipt path is exercised by isolated native replay tests. */
    protected void acknowledge(JSONObject response,String fallbackId){
        waiting=false;String transcript=response.optString("text","");String reply=response.optString("reply",response.optString("status","Cloud acknowledged"));
        String resultStatus=response.optString("status");
        if("conversation_started".equals(resultStatus)){setConversation(true);session=UUID.randomUUID().toString();}
        else if("ended".equals(resultStatus))setConversation(false);
        rememberReceipt(response,response.optString("task_id",fallbackId));
        Cloud.prefs(this).edit().putString("voice_transcript",transcript).putString("voice_user_text",transcript).putString("voice_reply",reply).apply();
        state(reply);speakReply(reply);
    }
    private void rememberReceipt(JSONObject response,String identifier){
        String transcript=response.optString("text","");String reply=response.optString("reply","");String resultStatus=response.optString("status");
        lastReceiptId=identifier;lastReceiptStatus=resultStatus;
        long now=System.currentTimeMillis();if(!transcript.isEmpty())VoiceChat.user(this,response.optString("user_message_id",identifier),transcript,now);
        if(!reply.isEmpty())VoiceChat.assistant(this,identifier,reply,now,("queued".equals(resultStatus)||"running".equals(resultStatus))?"acknowledgement":"answer",response.optString("task_id",""));
        try{VoiceHistory.record(this,response);Cloud.prefs(this).edit().remove("voice_history_error").apply();}
        catch(Exception error){Cloud.prefs(this).edit().putString("voice_history_error","Recent requests could not be saved").apply();}
    }
    protected void speakReply(String reply){
        if(ttsReady&&!reply.isEmpty()){speaking=true;utteranceId=UUID.randomUUID().toString();if(tts.speak(reply,TextToSpeech.QUEUE_FLUSH,null,utteranceId)==TextToSpeech.ERROR){utteranceId=null;speaking=false;afterReply();}}
        else afterReply();
    }
    protected void afterReply(){
        if(conversationMode){followup=true;conversationDeadline=System.currentTimeMillis()+30000;state("Conversation mode · listening");}
        else{followup=false;session=UUID.randomUUID().toString();if(Cloud.prefs(this).getBoolean("wake_enabled",false))state("Listening locally for Hey Chat");else stopSelf();}
    }
    private void setConversation(boolean enabled){conversationMode=enabled;if(!enabled){taskTarget=null;taskDictation=false;}android.content.SharedPreferences.Editor edit=Cloud.prefs(this).edit().putBoolean("voice_conversation_mode",enabled);if(!enabled)edit.remove("task_voice");edit.apply();}
    private void clearPlayback(){playbackGeneration++;playbackExecutor.getQueue().clear();if(playback!=null)try{playback.pause();playback.flush();playback.play();}catch(Exception ignored){}}
    private void endConversation(){endConversation(true);}
    private synchronized void endConversation(boolean stopWhenIdle){
        setConversation(false);turnGeneration++;liveGeneration++;followup=requestCapture=waiting=speaking=false;cancelCapture=true;
        if(live!=null)live.disconnect();live=null;liveEnded=false;utteranceId=null;tts.stop();clearPlayback();session=UUID.randomUUID().toString();
        if(running.get()&&Cloud.prefs(this).getBoolean("wake_enabled",false))state("Listening locally for Hey Chat");else if(stopWhenIdle)stopSelf();
    }
    private void rememberWake(){Cloud.prefs(this).edit().putLong("voice_wake_count",Cloud.prefs(this).getLong("voice_wake_count",0)+1).putLong("voice_last_wake_at",System.currentTimeMillis()).apply();}

    // ---- Task details voice (TaskVoice), kept apart from the command, wake and live paths above. A dictation capture is
    // transcribed into that task's draft and never executed; a task conversation sends each turn as a follow-up of the
    // same task instead of a new command, and never opens the live provider. ----
    static final String TASK_DICTATE="com.personalassistant.companion.TASK_DICTATE",TASK_TALK="com.personalassistant.companion.TASK_TALK";
    /** The requested task, and the task bound to the capture in progress when it began; a dictation covers one capture. */
    private volatile String taskTarget,captureTask;private volatile boolean taskDictation,captureDictation;
    private boolean taskStart(Intent intent){
        String action=intent==null?"":String.valueOf(intent.getAction()),task=intent==null?null:intent.getStringExtra("task_id");boolean dictate=TASK_DICTATE.equals(action),general=START_CONVERSATION.equals(action);
        if(!dictate&&!TASK_TALK.equals(action)){if(general){taskTarget=null;taskDictation=false;}if(taskTarget==null&&(captureTask==null||general))Cloud.prefs(this).edit().remove("task_voice").apply();return false;}
        if(task==null||!task.matches("[A-Za-z0-9_-]{1,160}"))return false;
        if(live!=null||(dictate&&conversationMode)){state("Voice is busy · end the conversation first");return false;}
        turnGeneration++;waiting=false;taskTarget=task;taskDictation=dictate;if(!dictate){setConversation(true);session=UUID.randomUUID().toString();}
        Cloud.prefs(this).edit().putString("task_voice",(dictate?"dictate:":"talk:")+task).apply();return true;
    }
    private void taskSubmit(short[] pcm){
        final long generation=turnGeneration;
        TaskVoice.turn(this,pcm,captureTask,captureDictation,Cloud.prefs(this).getBoolean("voice_preview",false),new TaskVoice.Host(){
            public boolean current(){return !destroyed&&generation==turnGeneration;}
            public void state(String message){if(current())VoiceService.this.state(message);}
            public void sent(){main.post(()->{if(current()&&ttsReady)tts.speak("Sent.",TextToSpeech.QUEUE_FLUSH,null,"task-sent");});}
            public void reply(String text,boolean end){main.post(()->{if(!current())return;waiting=false;if(end)endConversation(false);VoiceService.this.state(text);speakReply(text);});}
            public void done(String message){main.post(()->{if(!current())return;waiting=false;Cloud.prefs(VoiceService.this).edit().remove("task_voice").apply();VoiceService.this.state(message);afterReply();});}
        });
    }
    /** A task capture ended without speech: the screen hears why, and a dictation never carries over to a later wake. */
    private void taskDropped(boolean wake){
        String task=captureTask;if(task==null||(!captureDictation&&wake))return;
        TaskVoice.note(this,task,captureDictation?"No speech heard · your draft is unchanged.":"No speech heard · the conversation ended.");captureTask=null;captureDictation=false;Cloud.prefs(this).edit().remove("task_voice").apply();
    }
    Notification notification(String status){NotificationManager manager=(NotificationManager)getSystemService(NOTIFICATION_SERVICE);NotificationStyle.channel(manager,"voice","Voice microphone",NotificationManager.IMPORTANCE_LOW,"Shows while the assistant's microphone is on");Intent open=new Intent(this,MainActivity.class);PendingIntent app=PendingIntent.getActivity(this,217,open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);PendingIntent stop=PendingIntent.getService(this,218,new Intent(this,VoiceService.class).setAction(STOP),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);PendingIntent talk=PendingIntent.getService(this,219,new Intent(this,VoiceService.class).setAction(TALK),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);return new Notification.Builder(this,"voice").setSmallIcon(R.drawable.ic_stat_assistant).setColor(NativeNotifications.ACCENT).setColorized(true).setCategory(Notification.CATEGORY_SERVICE).setSubText("Voice").setContentTitle("Assistant voice").setContentText(status).setContentIntent(app).setOngoing(true).addAction(new Notification.Action.Builder(null,"Talk",talk).build()).addAction(new Notification.Action.Builder(null,"Stop",stop).build()).build();}
    void state(String message){if(destroyed)return;Cloud.prefs(this).edit().putString("voice_status",message).commit();((NotificationManager)getSystemService(NOTIFICATION_SERVICE)).notify(217,notification(message));sendBroadcast(new Intent("com.personalassistant.companion.VOICE_STATE").setPackage(getPackageName()));}
    @Override public void onDestroy(){Cloud.prefs(this).edit().putBoolean("voice_mic_active",false).putBoolean("voice_conversation_active",false).putBoolean("voice_conversation_mode",false).putFloat("voice_level",0f).apply();destroyed=true;running.set(false);if(live!=null)live.disconnect();if(recorder!=null)try{recorder.stop();}catch(Exception ignored){}if(network!=null)((ConnectivityManager)getSystemService(CONNECTIVITY_SERVICE)).unregisterNetworkCallback(network);if(tts!=null){tts.stop();tts.shutdown();}playbackExecutor.shutdownNow();if(playback!=null){try{playback.stop();}catch(Exception ignored){}playback.release();playback=null;}String last=Cloud.prefs(this).getString("voice_status","");if(!(last.startsWith("Voice stopped:")||last.startsWith("No internet")||last.startsWith("Cloud unavailable")||last.startsWith("Connection lost")||last.startsWith("Wake model not installed")||last.startsWith("Microphone interrupted")))Cloud.prefs(this).edit().putString("voice_status","Microphone off").commit();sendBroadcast(new Intent("com.personalassistant.companion.VOICE_STATE").setPackage(getPackageName()));super.onDestroy();}
    @Override public IBinder onBind(Intent i){return null;}
}
