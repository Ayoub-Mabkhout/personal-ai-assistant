package com.personalassistant.companion;

import android.app.Instrumentation;
import android.os.Bundle;
import java.io.*;
import java.lang.reflect.Field;
import java.security.MessageDigest;
import java.util.*;
import org.json.*;

/** Actual Vosk/JNA JNI through production adapter; no mic/network/paired device. */
public final class VoskInstrumentation extends Instrumentation {
    public void onCreate(Bundle args){super.onCreate(args);start();}
    public void onStart(){Bundle bundle=new Bundle();VoskWakeDetector detector=null;try{
        check(Cloud.prefs(getTargetContext()).getString("token","").isEmpty(),"Unpaired disposable emulator required");
        JSONObject settings=new JSONObject(new String(bytes(true,"voice/vosk/settings.json"),"UTF-8"));
        check(settings.getBoolean("diagnostic_only")&&settings.getBoolean("diagnostic_no_activation"),"Require inactive diagnostic target");
        long start=System.nanoTime();detector=(VoskWakeDetector)VoskWakeDetector.create(getTargetContext());double load=(System.nanoTime()-start)/1e9;check(detector!=null&&detector.available(),"Actual Vosk native engine not available");
        Field model=VoskWakeDetector.class.getDeclaredField("model");model.setAccessible(true);Object weights=model.get(detector);
        JSONArray cases=new JSONObject(new String(bytes(false,"reference.json"),"UTF-8")).getJSONArray("cases"),rows=new JSONArray();int mismatches=0;double maxDelta=0;List<Long> times=new ArrayList<>();short[] fragmentedReference=null;long fragmentedActivation=-1;
        for(int index=0;index<cases.length();index++){
            JSONObject item=cases.getJSONObject(index);byte[] raw=bytes(false,item.getString("path"));check(hex(MessageDigest.getInstance("SHA-256").digest(raw)).equals(item.getString("sha256")),"Fixture checksum");short[] pcm=decode(raw);detector.reset();check(model.get(detector)==weights,"Reset reloaded Model");long began=System.nanoTime();
            for(int cursor=0;cursor<pcm.length;cursor+=320){short[] frame=Arrays.copyOfRange(pcm,cursor,Math.min(pcm.length,cursor+320));boolean active=!detector.candidateTriggered();long frameStart=System.nanoTime();check(!detector.accept(frame,frame.length),"Inactive diagnostic dispatched wake");if(active)times.add(System.nanoTime()-frameStart);}
            boolean nativeDetected=detector.candidateTriggered(),hostDetected=item.getBoolean("host_detected");if(nativeDetected!=hostDetected)mismatches++;
            Long nativeSamples=nativeDetected?detector.activationSamples():null;double difference=nativeDetected&&hostDetected?Math.abs(nativeSamples-item.getLong("host_activation_samples"))/16000.0:0;maxDelta=Math.max(maxDelta,difference);
            JSONObject row=new JSONObject(item.toString()).put("native_detected",nativeDetected).put("native_activation_samples",nativeSamples==null?JSONObject.NULL:nativeSamples).put("host_native_time_difference_seconds",difference).put("native_processing_seconds",(System.nanoTime()-began)/1e9);rows.put(row);
            if(fragmentedReference==null&&nativeDetected&&pcm.length<160000){fragmentedReference=pcm;fragmentedActivation=detector.activationSamples();}
        }
        check(fragmentedReference!=null,"No positive fixture for reset/fragment proof");detector.reset();int cursor=0,part=0;int[] chunks={1,319,641,7,320,997};while(cursor<fragmentedReference.length){int count=Math.min(chunks[part++%chunks.length],fragmentedReference.length-cursor);check(!detector.accept(Arrays.copyOfRange(fragmentedReference,cursor,cursor+count),count),"Diagnostic fragmented wake activated");cursor+=count;}check(detector.activationSamples()==fragmentedActivation,"Fragment size changed80ms stability decision");
        // Old partial prefix must not survive a skipped-audio/reset boundary.
        int split=Math.min(16000,fragmentedReference.length);detector.reset();detector.accept(Arrays.copyOfRange(fragmentedReference,0,split),split);detector.reset();short[] suffix=Arrays.copyOfRange(fragmentedReference,split,fragmentedReference.length);detector.accept(suffix,suffix.length);long resumed=detector.activationSamples();detector.reset();detector.accept(suffix,suffix.length);check(detector.activationSamples()==resumed,"Old prefix changed reset suffix");check(model.get(detector)==weights,"Boundary reset reloaded weights");
        Collections.sort(times);JSONObject proof=new JSONObject().put("actual_android_jni",true).put("cases",rows).put("model_load_seconds",load).put("classification_mismatches",mismatches).put("max_host_native_activation_delta_seconds",maxDelta).put("frame_p95_ms",times.get((int)(times.size()*.95))/1e6).put("frame_max_ms",times.get(times.size()-1)/1e6).put("fragmented_stream_same_activation",true).put("reset_retains_model",true).put("reset_suffix_matches_fresh",true).put("diagnostic_no_activation",true);
        bundle.putString("stream",proof.toString());finish(0,bundle);
    }catch(Throwable error){bundle.putString("stream",android.util.Log.getStackTraceString(error));finish(1,bundle);}finally{if(detector!=null)detector.close();}}
    private byte[] bytes(boolean target,String path)throws IOException{try(InputStream input=(target?getTargetContext():getContext()).getAssets().open(path);ByteArrayOutputStream output=new ByteArrayOutputStream()){byte[] buffer=new byte[65536];int count;while((count=input.read(buffer))!=-1)output.write(buffer,0,count);return output.toByteArray();}}
    static short[] decode(byte[] raw){short[] pcm=new short[raw.length/2];for(int i=0;i<pcm.length;i++)pcm[i]=(short)((raw[2*i]&255)|(raw[2*i+1]<<8));return pcm;}
    static String hex(byte[] bytes){StringBuilder value=new StringBuilder();for(byte b:bytes)value.append(String.format(Locale.ROOT,"%02x",b&255));return value.toString();}
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
