package com.personalassistant.companion;

import android.app.Instrumentation;
import android.os.Bundle;
import android.content.Context;
import java.io.*;
import java.lang.reflect.*;
import java.security.MessageDigest;
import java.util.*;
import org.json.*;

/** Actual Android ORT feature parity only. No cloud calls or production model selection. */
public class OpenWakeInstrumentation extends Instrumentation {
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle result=new Bundle();OpenWakeDetector detector=null;try{
        JSONObject reference=new JSONObject(new String(bytes(getContext(),"reference.json"),"UTF-8"));
        boolean rawMel=reference.optString("feature_type","embedding").equals("logmel-cnn");
        JSONObject settings=new JSONObject(new String(bytes(getTargetContext(),"voice/openwake/settings.json"),"UTF-8"));
        check(settings.optBoolean("diagnostic_only",false)&&settings.optBoolean("diagnostic_no_activation",false),"Parity must use an explicitly inactive diagnostic classifier");
        byte[] raw=bytes(getContext(),"input.pcm");check(hash(raw).equals(reference.getString("pcm_sha256")),"Fixture PCM checksum");
        JSONObject models=reference.getJSONObject("models");
        for(Iterator<String> names=models.keys();names.hasNext();){
            String name=names.next();String packaged=(name.equals("melspectrogram.onnx")||name.equals("embedding_model.onnx"))?name:"classifier.onnx";
            check(hash(bytes(getTargetContext(),"voice/openwake/"+packaged)).equals(models.getString(name)),"Fixture model identity: "+name);
        }
        JSONArray frames=reference.getJSONArray("frames");short[] pcm=new short[frames.length()*1280];
        for(int n=0;n<raw.length/2;n++)pcm[n]=(short)((raw[2*n]&255)|(raw[2*n+1]<<8));
        detector=(OpenWakeDetector)OpenWakeDetector.create(getTargetContext());check(detector!=null&&detector.available(),"Actual ORT detector unavailable");
        check((field("embeddingSession").get(detector)==null)==rawMel,"Selected feature path loads the wrong model sessions");
        Field melField=field("mel"),featuresField=field("features"),countField=field("embeddingCount"),headField=field("headSession");
        Object head=headField.get(detector);Method infer=head.getClass().getDeclaredMethod("infer",float[].class,long[].class);infer.setAccessible(true);
        double maxMel=0,maxEmbedding=0,maxWindow=0,maxProbability=0;long started=System.nanoTime();
        for(int block=0;block<frames.length();block++){
            // The production microphone emits 20ms frames, not complete 80ms model hops.
            for(int part=0;part<4;part++){short[] chunk=Arrays.copyOfRange(pcm,block*1280+part*320,block*1280+(part+1)*320);check(!detector.accept(chunk,chunk.length),"Diagnostic threshold unexpectedly activated");}
            check(countField.getInt(detector)==block+1,"Cold-start block accounting");
            JSONObject expected=frames.getJSONObject(block);float[] mel=(float[])melField.get(detector),features=(float[])featuresField.get(detector);
            double melError=compare(Arrays.copyOfRange(mel,mel.length-8*32,mel.length),flatten(expected.getJSONArray("last_mel_frames")),2e-4,2e-5,"mel block "+block);
            double embeddingError=rawMel?0:compare(Arrays.copyOfRange(features,features.length-96,features.length),flat(expected.getJSONArray("embedding")),5e-4,2e-5,"embedding block "+block);
            float[] headInput=rawMel?mel:features;
            double windowError=compare(headInput,flatten(expected.getJSONArray("classifier_input")),5e-4,2e-5,"head history block "+block);
            float probability=((float[])infer.invoke(head,headInput,rawMel?new long[]{1,1,196,32}:new long[]{1,16,96}))[0];
            double probabilityError=Math.abs(probability-expected.getDouble("probability"));check(probabilityError<2e-4,"Head probability mismatch at block "+block+": "+probabilityError);
            if(block+1<=26)check(detector.score()==0,"Cold-start prediction was not suppressed");
            else check(Math.abs(detector.score()-probability)<1e-6,"Live head score differs from same native input");
            maxMel=Math.max(maxMel,melError);maxEmbedding=Math.max(maxEmbedding,embeddingError);maxWindow=Math.max(maxWindow,windowError);maxProbability=Math.max(maxProbability,probabilityError);
        }
        float[] finalFeatures=((float[])(rawMel?melField:featuresField).get(detector)).clone();float finalScore=detector.score();detector.reset();
        check(detector.score()==0&&countField.getInt(detector)==0,"Reset did not clear probability and temporal counters");
        check(headField.get(detector)==head,"Stream reset reloaded classifier model weights");
        // Exercise fragmented stream input and a second cold start independently.
        int cursor=0,index=0;int[] sizes={1,79,320,641,159,1280,37};
        while(cursor<pcm.length){int size=Math.min(sizes[index++%sizes.length],pcm.length-cursor);short[] chunk=Arrays.copyOfRange(pcm,cursor,cursor+size);check(!detector.accept(chunk,size),"Fragmented input activated diagnostic model");cursor+=size;}
        compare((float[])(rawMel?melField:featuresField).get(detector),finalFeatures,1e-6,1e-6,"Fragmented stream final history");check(Math.abs(detector.score()-finalScore)<1e-6,"Fragmented stream changed classifier score");
        JSONObject proof=new JSONObject().put("blocks",frames.length()).put("sample_rate",16000).put("microphone_frame_samples",320)
            .put("feature_type",rawMel?"logmel-cnn":"embedding").put("model_weights_retained_on_reset",true)
            .put("cold_start_blocks",26).put("max_mel_error",maxMel).put("embedding_model_loaded",!rawMel).put("max_embedding_error",rawMel?JSONObject.NULL:maxEmbedding).put("max_history_error",maxWindow)
            .put("max_probability_error",maxProbability).put("replay_seconds",(System.nanoTime()-started)/1e9)
            .put("fragmented_stream_equal",true).put("actual_android_onnxruntime",true).put("classifier_approved_for_deployment",false);
        result.putString("stream",proof.toString());finish(0,result);
    }catch(Throwable error){result.putString("stream",android.util.Log.getStackTraceString(error));finish(1,result);}finally{if(detector!=null)detector.close();}}
    static Field field(String name)throws Exception{Field f=OpenWakeDetector.class.getDeclaredField(name);f.setAccessible(true);return f;}
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static double compare(float[] actual,float[] expected,double absolute,double relative,String label){check(actual.length==expected.length,label+" shape");double error=0;for(int n=0;n<actual.length;n++){double difference=Math.abs(actual[n]-expected[n]);check(Double.isFinite(actual[n])&&difference<=absolute+relative*Math.abs(expected[n]),label+" element "+n+": "+actual[n]+" != "+expected[n]);error=Math.max(error,difference);}return error;}
    static float[] flat(JSONArray array)throws Exception{float[] values=new float[array.length()];for(int n=0;n<values.length;n++)values[n]=(float)array.getDouble(n);return values;}
    static float[] flatten(JSONArray array)throws Exception{int width=array.getJSONArray(0).length();float[] values=new float[array.length()*width];for(int n=0;n<array.length();n++)System.arraycopy(flat(array.getJSONArray(n)),0,values,n*width,width);return values;}
    static byte[] bytes(Context context,String path)throws IOException{try(InputStream in=context.getAssets().open(path);ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] chunk=new byte[8192];int n;while((n=in.read(chunk))!=-1){out.write(chunk,0,n);if(out.size()>64*1024*1024)throw new IOException("Diagnostic fixture too large");}return out.toByteArray();}}
    static String hash(byte[] value)throws Exception{StringBuilder hex=new StringBuilder();for(byte b:MessageDigest.getInstance("SHA-256").digest(value))hex.append(String.format("%02x",b&255));return hex.toString();}
}
