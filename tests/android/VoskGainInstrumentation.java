package com.personalassistant.companion;
import android.app.Instrumentation;
import android.os.Bundle;
import java.io.*;
import java.lang.reflect.Field;
import java.util.*;
import org.json.*;

/** Limited actual JNI controls: sensitivity never modifies the capture PCM. */
public final class VoskGainInstrumentation extends Instrumentation {
    public void onCreate(Bundle args){super.onCreate(args);start();}
    public void onStart(){Bundle result=new Bundle();int outcome=0;VoskWakeDetector detector=null;try{
        if(!"ranchu".equals(android.os.Build.HARDWARE)&&!"goldfish".equals(android.os.Build.HARDWARE))throw new AssertionError("Emulator required");
        detector=(VoskWakeDetector)VoskWakeDetector.create(getTargetContext());check(detector!=null&&detector.available(),"Vosk unavailable");Field model=VoskWakeDetector.class.getDeclaredField("model"),frame=VoskWakeDetector.class.getDeclaredField("frame");model.setAccessible(true);frame.setAccessible(true);Object weights=model.get(detector);
        short[] raw=new short[320];short[] boundary={32767,-32768,20000,-20000,16383,-16384,0,7,-9};System.arraycopy(boundary,0,raw,0,boundary.length);short[] original=raw.clone();BufferedCapture capture=new BufferedCapture(32000);capture.begin(false);capture.ingest(raw,raw.length);
        detector.sensitivity(false);detector.accept(raw,raw.length);check(Arrays.equals(raw,(short[])frame.get(detector)),"Balanced input gain changed PCM");check(Arrays.equals(raw,original),"Balanced detector changed caller PCM");detector.sensitivity(true);detector.accept(raw,raw.length);short[] amplified=(short[])frame.get(detector);for(int i=0;i<raw.length;i++)check(amplified[i]==(short)Math.max(-32768,Math.min(32767,raw[i]*2)),"Sensitive gain/saturation "+i);check(Arrays.equals(raw,original)&&Arrays.equals(capture.finish(),original),"Sensitivity changed buffered original audio");check(model.get(detector)==weights,"Sensitivity reloaded model weights");
        byte[] bytes=read("clip-003.pcm");short[] positive=decode(bytes);JSONArray controls=new JSONArray();
        for(boolean sensitive:new boolean[]{false,true}){detector.sensitivity(sensitive);detector.reset();for(int i=0;i<positive.length&&!detector.candidateTriggered();i+=320){short[] chunk=Arrays.copyOfRange(positive,i,Math.min(positive.length,i+320)),before=chunk.clone();detector.accept(chunk,chunk.length);check(Arrays.equals(before,chunk),"Positive frame modified");}check(detector.candidateTriggered(),"Known positive missed with sensitivity "+sensitive);controls.put(new JSONObject().put("sensitive",sensitive).put("activation_samples",detector.activationSamples()));}
        detector.sensitivity(false);detector.reset();short[] negative=decode(read("clip-004.pcm"));for(int i=0;i<negative.length;i+=320){short[] chunk=Arrays.copyOfRange(negative,i,Math.min(negative.length,i+320));detector.accept(chunk,chunk.length);}check(!detector.candidateTriggered(),"Original no-wake control fired");
        result.putString("stream",new JSONObject().put("actual_android_vosk_jni",true).put("balanced_gain",1).put("sensitive_gain",2).put("sensitive_saturation_exact",true).put("caller_and_buffered_pcm_unchanged",true).put("model_retained_on_sensitivity_change",true).put("positive_controls",controls).put("no_wake_control_rejected",true).toString());
    }catch(Throwable error){result.putString("stream",android.util.Log.getStackTraceString(error));outcome=1;}finally{if(detector!=null)detector.close();}finish(outcome,result);}
    byte[] read(String name)throws IOException{try(InputStream input=getContext().getAssets().open(name);ByteArrayOutputStream output=new ByteArrayOutputStream()){byte[] buffer=new byte[8192];int count;while((count=input.read(buffer))!=-1)output.write(buffer,0,count);return output.toByteArray();}}
    static short[] decode(byte[] raw){short[] data=new short[raw.length/2];for(int i=0;i<data.length;i++)data[i]=(short)((raw[2*i]&255)|(raw[2*i+1]<<8));return data;}
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
