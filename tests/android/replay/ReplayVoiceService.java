package com.personalassistant.companion;
import android.os.*;
import java.io.*;
import org.json.*;

/** Diagnostic target only: paced PCM through the actual production state loop. */
public final class ReplayVoiceService extends VoiceService {
    private short[] source;private int cursor;
    @Override WakeDetector loadDetector()throws Exception {
        final WakeDetector delegate=super.loadDetector();final int after=Cloud.prefs(this).getInt("voice_replay_trigger_after_sample",0);if(after<=0)return delegate;
        return new WakeDetector(){private boolean heard;
            public boolean accept(short[] data,int size){heard=delegate.accept(data,size)||heard;return heard&&cursor>=after;}
            public boolean available(){return delegate.available();}public String name(){return delegate.name()+" · delayed decision diagnostic";}
            public void reset(){heard=false;delegate.reset();}public void close(){delegate.close();}
        };
    }
    @Override public void onCreate(){
        if(!"ranchu".equals(Build.HARDWARE)&&!"goldfish".equals(Build.HARDWARE))throw new IllegalStateException("Emulator only");
        if(!Cloud.prefs(this).getString("token","").isEmpty()||VoiceOutbox.pending(this)!=0)throw new IllegalStateException("Unpaired isolated emulator required");
        super.onCreate();
        try{ByteArrayOutputStream out=new ByteArrayOutputStream();try(InputStream in=getAssets().open("replay/input.pcm")){byte[] data=new byte[8192];int n;while((n=in.read(data))!=-1)out.write(data,0,n);}byte[] raw=out.toByteArray();source=new short[raw.length/2];for(int i=0;i<source.length;i++)source[i]=(short)((raw[2*i]&255)|(raw[2*i+1]<<8));}
        catch(Exception error){throw new IllegalStateException(error);}
    }
    @Override public int onStartCommand(android.content.Intent intent,int flags,int startId){
        if(intent!=null&&intent.hasExtra("isolated_receipt")){
            if(!Cloud.prefs(this).getBoolean("voice_replay_mode_probe",false))throw new IllegalStateException("Mode probe not enabled");
            try{JSONObject receipt=new JSONObject(intent.getStringExtra("isolated_receipt"));acknowledge(receipt,receipt.getString("task_id"));}
            catch(Exception error){throw new IllegalStateException(error);}return START_NOT_STICKY;
        }
        return super.onStartCommand(intent,flags,startId);
    }
    @Override protected void speakReply(String reply){
        if(!Cloud.prefs(this).getBoolean("voice_replay_mode_probe",false)){super.speakReply(reply);return;}
        // Count authoritative receipts without a TTS engine or external API.
        int completed=Cloud.prefs(this).getInt("voice_replay_spoken_replies",0)+1;
        afterReply();
        try{java.lang.reflect.Field followup=VoiceService.class.getDeclaredField("followup");followup.setAccessible(true);Cloud.prefs(this).edit().putBoolean("voice_replay_followup",followup.getBoolean(this)).putString("voice_replay_last_reply",reply).putInt("voice_replay_spoken_replies",completed).commit();}
        catch(Exception error){throw new IllegalStateException(error);}
    }
    @Override protected int readMicrophone(short[] frame){
        try{Thread.sleep(20);}catch(InterruptedException interrupted){Thread.currentThread().interrupt();return 0;}
        if(Cloud.prefs(this).getBoolean("voice_replay_manual_silence",false)){java.util.Arrays.fill(frame,(short)0);return frame.length;}int n=Math.min(frame.length,source.length-cursor);if(n>0){System.arraycopy(source,cursor,frame,0,n);cursor+=n;return n;}
        java.util.Arrays.fill(frame,(short)0);return frame.length;
    }
    @Override protected void submit(short[] pcm){
        long submitClock=SystemClock.elapsedRealtimeNanos();try{File destination=new File(getFilesDir(),"voice-replay-capture.pcm");try(FileOutputStream out=new FileOutputStream(destination)){byte[] raw=new byte[pcm.length*2];for(int i=0;i<pcm.length;i++){raw[2*i]=(byte)pcm[i];raw[2*i+1]=(byte)(pcm[i]>>>8);}out.write(raw);}
            JSONObject result=new JSONObject().put("samples",pcm.length).put("source_end_sample",cursor).put("submit_ns",submitClock).put("source_start_sample",cursor-pcm.length).put("no_cloud_submission",true);
            Cloud.prefs(this).edit().putString("voice_replay_result",result.toString()).commit();state("Replay capture intercepted · no server");
        }catch(Exception error){throw new IllegalStateException(error);}
    }
    @Override void startLive(short[] prefix){Cloud.prefs(this).edit().putInt("voice_replay_live_attempts",Cloud.prefs(this).getInt("voice_replay_live_attempts",0)+1).commit();state("Replay live connection intercepted · no server");}
}
