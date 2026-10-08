package com.personalassistant.companion.replaytests;
import android.app.*;
import android.content.*;
import android.os.*;
import java.io.*;
import org.json.*;

/** Actual production state loop with a diagnostic-only PCM source and no cloud sink. */
public final class ReplayInstrumentation extends Instrumentation {
    private byte[] beforeChat;private int delayedSample;private boolean expectNoCapture,manualSilence,localTest,modePolicy;
    @Override public void onCreate(Bundle args){super.onCreate(args);delayedSample=Integer.parseInt(args.getString("delay_sample","0"));expectNoCapture=Boolean.parseBoolean(args.getString("expect_no_capture","false"));manualSilence=Boolean.parseBoolean(args.getString("manual_silence","false"));localTest=Boolean.parseBoolean(args.getString("local_test","false"));modePolicy=Boolean.parseBoolean(args.getString("mode_policy","false"));start();}
    @Override public void onStart(){Bundle result=new Bundle();Context target=getTargetContext();SharedPreferences prefs=target.getSharedPreferences("assistant",0);boolean beforeWake=prefs.getBoolean("wake_enabled",false),beforePreview=prefs.getBoolean("voice_preview",false),beforeLive=prefs.getBoolean("voice_live",false),beforeTest=prefs.getBoolean("voice_listening_test",false);int code=0;Intent replay=new Intent().setComponent(new ComponentName(target.getPackageName(),"com.personalassistant.companion.ReplayVoiceService"));try{
        if(!"ranchu".equals(Build.HARDWARE)&&!"goldfish".equals(Build.HARDWARE))throw new IllegalStateException("Emulator required");
        if(!prefs.getString("token","").isEmpty())throw new IllegalStateException("Unpaired emulator required");
        if(modePolicy){File chat=new File(target.getFilesDir(),"voice-chat.json");if(chat.isFile())beforeChat=read(new FileInputStream(chat));modePolicy(target,prefs,replay,result);finish(0,result);return;}
        KeyguardManager guard=target.getSystemService(KeyguardManager.class);if(!guard.isDeviceSecure()||!guard.isDeviceLocked()||target.getSystemService(PowerManager.class).isInteractive())throw new IllegalStateException("Secure locked screen-off emulator required");
        target.stopService(new Intent().setComponent(new ComponentName(target.getPackageName(),"com.personalassistant.companion.VoiceService")));
        long wakeBaseline=prefs.getLong("voice_wake_count",0);File outbox=new File(target.getFilesDir(),"voice-outbox");int pendingBefore=outbox.list()==null?0:outbox.list().length;
        prefs.edit().putBoolean("wake_enabled",!manualSilence).putBoolean("voice_listening_test",localTest).putBoolean("voice_preview",!localTest).putBoolean("voice_live",localTest).putBoolean("voice_replay_manual_silence",manualSilence).putInt("voice_replay_trigger_after_sample",delayedSample).putInt("voice_replay_live_attempts",0).remove("voice_replay_result").remove("voice_capture_started_ns").remove("voice_wake_detected_ns").commit();
        if(manualSilence)replay.setAction("com.personalassistant.companion.TALK");target.startForegroundService(replay);long end=SystemClock.elapsedRealtime()+(expectNoCapture?21000:25000);
        while(SystemClock.elapsedRealtime()<end&&prefs.getString("voice_replay_result","").isEmpty()&&(!localTest||prefs.getLong("voice_wake_count",0)<=wakeBaseline)){String status=prefs.getString("voice_status","");if(status.startsWith("Voice stopped:")||status.startsWith("Microphone could not start:"))throw new IllegalStateException(status);Thread.sleep(20);}
        String saved=prefs.getString("voice_replay_result","");if(localTest){
            Thread.sleep(1500);int pendingAfter=outbox.list()==null?0:outbox.list().length;if(prefs.getLong("voice_wake_count",0)<=wakeBaseline)throw new IllegalStateException("Local test did not count an actual wake");if(!saved.isEmpty()||!prefs.getString("voice_replay_result","").isEmpty()||pendingBefore!=pendingAfter||prefs.getInt("voice_replay_live_attempts",0)!=0||prefs.getLong("voice_capture_started_ns",0)>0)throw new IllegalStateException("Local test entered capture/outbox/live mode");if(!guard.isDeviceLocked()||target.getSystemService(PowerManager.class).isInteractive())throw new IllegalStateException("Local test changed locked screen state");result.putBoolean("actual_production_local_test_loop",true);result.putLong("wake_events",prefs.getLong("voice_wake_count",0)-wakeBaseline);result.putBoolean("no_capture_outbox_or_live_attempt",true);result.putBoolean("screen_stayed_off_and_locked",true);result.putString("stream","Actual locked local wake counted with live preference ON, zero capture/outbox/session attempts; injected PCM only.");
        }else if(expectNoCapture){if(!saved.isEmpty()||prefs.getLong("voice_capture_started_ns",0)<=0)throw new IllegalStateException("Expected an entered capture with no submission");result.putBoolean("capture_entered_but_not_submitted",true);result.putBoolean("manual_silence",manualSilence);result.putString("stream","Capture entered but no cloud/sink submission; diagnostic expected outcome.");}else{
        if(saved.isEmpty())throw new IllegalStateException("Warm wake did not submit capture: "+prefs.getString("voice_status",""));JSONObject data=new JSONObject(saved);
        byte[] source=read(target.getAssets().open("replay/input.pcm")),captured=read(new FileInputStream(new File(target.getFilesDir(),"voice-replay-capture.pcm")));int first=data.getInt("source_start_sample")*2,last=data.getInt("source_end_sample")*2;
        if(first<0||last>source.length||!java.util.Arrays.equals(captured,java.util.Arrays.copyOfRange(source,first,last)))throw new IllegalStateException("Captured PCM has gaps or duplicates");
        long wake=prefs.getLong("voice_wake_detected_ns",0),capture=prefs.getLong("voice_capture_started_ns",0),submit=data.getLong("submit_ns");if(wake<=0||capture<wake||submit<capture)throw new IllegalStateException("Warm event clocks invalid");
        if(!guard.isDeviceLocked()||target.getSystemService(PowerManager.class).isInteractive())throw new IllegalStateException("Warm capture changed locked screen state");
        result.putBoolean("actual_production_service_loop",true);result.putBoolean("deterministic_injected_pcm_not_physical_microphone",true);result.putBoolean("screen_stayed_off_and_locked",true);result.putBoolean("capture_samples_exact",true);result.putBoolean("no_cloud_submission",data.getBoolean("no_cloud_submission"));result.putLong("wake_to_capture_us",(capture-wake)/1000);result.putLong("wake_to_endpoint_submit_ms",(submit-wake)/1000000);result.putInt("capture_samples",captured.length/2);result.putString("wake_detector",prefs.getString("wake_detector",""));result.putInt("delayed_decision_sample",delayedSample);result.putString("stream","Warm screen-off wake enters capture immediately through the production recorder thread and retains exact PCM; diagnostic source/sink only.");}
    }catch(Throwable error){result.putString("stream",android.util.Log.getStackTraceString(error));code=1;}finally{target.stopService(replay);if(modePolicy){try{File chat=new File(target.getFilesDir(),"voice-chat.json");if(beforeChat==null)chat.delete();else try(FileOutputStream out=new FileOutputStream(chat)){out.write(beforeChat);}File[] probes=new File(target.getFilesDir(),"voice-receipts").listFiles((folder,name)->name.matches("mode-probe-[0-9]+\\.json"));if(probes!=null)for(File probe:probes)probe.delete();}catch(Exception ignored){}}prefs.edit().putBoolean("wake_enabled",beforeWake).putBoolean("voice_preview",beforePreview).putBoolean("voice_live",beforeLive).putBoolean("voice_listening_test",beforeTest).remove("voice_replay_manual_silence").remove("voice_replay_trigger_after_sample").remove("voice_replay_live_attempts").remove("voice_replay_mode_probe").remove("voice_replay_spoken_replies").remove("voice_replay_followup").remove("voice_replay_last_reply").commit();}finish(code,result);}
    private void modePolicy(Context target,SharedPreferences prefs,Intent replay,Bundle result)throws Exception {
        target.stopService(new Intent().setComponent(new ComponentName(target.getPackageName(),"com.personalassistant.companion.VoiceService")));
        int before=new File(target.getFilesDir(),"voice-outbox").list()==null?0:new File(target.getFilesDir(),"voice-outbox").list().length;
        prefs.edit().putBoolean("wake_enabled",true).putBoolean("voice_preview",true).putBoolean("voice_listening_test",false).putBoolean("voice_replay_manual_silence",true).putBoolean("voice_replay_mode_probe",true).putInt("voice_replay_spoken_replies",0).putInt("voice_replay_live_attempts",0).commit();
        target.startForegroundService(replay);long end=SystemClock.elapsedRealtime()+20000;
        while(!prefs.getBoolean("voice_mic_active",false)&&SystemClock.elapsedRealtime()<end)Thread.sleep(25);
        if(!prefs.getBoolean("voice_mic_active",false))throw new IllegalStateException("Microphone did not start for mode probe");
        receipt(target,prefs,replay,"queued","Find my latest invoice.","Queued command to the laptop: Find my latest invoice.",1,false);
        Thread.sleep(500);if(prefs.getInt("voice_replay_spoken_replies",0)!=1||prefs.getBoolean("voice_replay_followup",true))throw new IllegalStateException("Default command restarted follow-up or repeated speech");
        receipt(target,prefs,replay,"completed","Add milk to my shopping list.","Added milk.",2,false);
        receipt(target,prefs,replay,"conversation_started","Start conversation mode.","Conversation mode on.",3,true);
        receipt(target,prefs,replay,"queued","Find my latest invoice.","Queued command to the laptop: Find my latest invoice.",4,true);
        receipt(target,prefs,replay,"ended","That was all.","Conversation ended.",5,false);
        target.startService(new Intent(replay).setAction("com.personalassistant.companion.START_CONVERSATION"));
        end=SystemClock.elapsedRealtime()+5000;while(!prefs.getBoolean("voice_conversation_mode",false)&&SystemClock.elapsedRealtime()<end)Thread.sleep(25);
        if(!prefs.getBoolean("voice_conversation_mode",false))throw new IllegalStateException("Start conversation intent did not change mode");
        target.startService(new Intent(replay).setAction("com.personalassistant.companion.END_CONVERSATION"));
        end=SystemClock.elapsedRealtime()+5000;while(prefs.getBoolean("voice_conversation_mode",true)&&SystemClock.elapsedRealtime()<end)Thread.sleep(25);
        if(prefs.getBoolean("voice_conversation_mode",true))throw new IllegalStateException("End conversation intent did not return to command mode");
        if(prefs.getInt("voice_replay_spoken_replies",0)!=5||prefs.getInt("voice_replay_live_attempts",0)!=0)throw new IllegalStateException("Mode controls produced extra reply or Live request");
        int after=new File(target.getFilesDir(),"voice-outbox").list()==null?0:new File(target.getFilesDir(),"voice-outbox").list().length;
        if(before!=after)throw new IllegalStateException("Mode tests changed voice outbox");
        result.putBoolean("one_receipt_one_spoken_reply",true);result.putBoolean("default_reply_returns_to_local_wake",true);result.putBoolean("explicit_conversation_followup_only",true);result.putBoolean("end_phrase_and_ui_return_to_standby",true);result.putBoolean("no_cloud_or_outbox_submission",true);result.putString("stream","Actual VoiceService receipt/lifecycle policy passed on isolated emulator; TTS intercepted, no paid/network calls.");
    }
    private void receipt(Context target,SharedPreferences prefs,Intent replay,String status,String text,String reply,int count,boolean conversation)throws Exception {
        JSONObject receipt=new JSONObject().put("task_id","mode-probe-"+count).put("status",status).put("text",text).put("reply",reply);
        target.startService(new Intent(replay).putExtra("isolated_receipt",receipt.toString()));long end=SystemClock.elapsedRealtime()+5000;
        while(prefs.getInt("voice_replay_spoken_replies",0)<count&&SystemClock.elapsedRealtime()<end)Thread.sleep(25);
        if(prefs.getInt("voice_replay_spoken_replies",0)!=count||prefs.getBoolean("voice_conversation_mode",!conversation)!=conversation||prefs.getBoolean("voice_replay_followup",!conversation)!=conversation)throw new IllegalStateException("Receipt policy wrong: "+status);
        if(!reply.equals(prefs.getString("voice_replay_last_reply","")))throw new IllegalStateException("Spoken receipt did not match authoritative backend");
    }
    static byte[] read(InputStream source)throws IOException{try(InputStream input=source;ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] data=new byte[8192];int n;while((n=input.read(data))!=-1)out.write(data,0,n);return out.toByteArray();}}
}
