package com.personalassistant.companion;

import android.content.Context;
import android.content.res.AssetManager;
import java.io.*;
import java.lang.reflect.Method;
import java.nio.FloatBuffer;
import java.util.*;
import org.json.JSONObject;

/** Optional custom head over frozen openWakeWord features; no standby network. */
public final class OpenWakeDetector implements WakeDetector {
    private static final int HOP=1280,OVERLAP=480,MEL_FRAMES=76,MEL_BINS=32,EMBED_FRAMES=16,EMBED_DIM=96;
    private final float[] audio=new float[HOP+OVERLAP],mel,features=new float[EMBED_FRAMES*EMBED_DIM];
    private int audioSize,accumulated,embeddingCount,positiveFrames;
    private final Object environment;
    private final Session melSession,embeddingSession,headSession;
    private final Method createTensor;
    private final double threshold;
    private final int patience,minEmbeddingFrames;
    private final String featureType;
    private final int melFrames;
    private final boolean activationEnabled;
    private boolean ready=true;
    private float lastScore;

    static byte[] asset(AssetManager assets,String name)throws IOException {
        try(InputStream in=assets.open(name);ByteArrayOutputStream out=new ByteArrayOutputStream()){
            byte[] chunk=new byte[8192];int n;while((n=in.read(chunk))!=-1){out.write(chunk,0,n);if(out.size()>16*1024*1024)throw new IOException("Wake model asset too large");}return out.toByteArray();
        }
    }

    public static WakeDetector create(Context context)throws Exception {
        try{
            try{context.getAssets().open("voice/openwake/settings.json").close();Class.forName("ai.onnxruntime.OnnxTensor");}
            catch(FileNotFoundException|ClassNotFoundException absent){return null;}
            return new OpenWakeDetector(context.getAssets());
        }
        catch(LinkageError error){throw new IOException("ONNX wake runtime is incompatible with this phone",error);}
    }

    private OpenWakeDetector(AssetManager assets)throws Exception {
        JSONObject settings=new JSONObject(new String(asset(assets,"voice/openwake/settings.json"),"UTF-8"));
        if(settings.getInt("schema_version")!=1||settings.getInt("sample_rate")!=16000||settings.getInt("hop_samples")!=HOP)throw new IOException("Unsupported wake feature settings");
        featureType=settings.optString("feature_type","embedding");
        if(!featureType.equals("embedding")&&!featureType.equals("logmel-cnn"))throw new IOException("Unsupported wake classifier feature type");
        melFrames=featureType.equals("logmel-cnn")?196:MEL_FRAMES;
        if(settings.optInt("mel_frames",melFrames)!=melFrames)throw new IOException("Wake classifier history shape changed");
        mel=new float[melFrames*MEL_BINS];
        activationEnabled=!settings.optBoolean("diagnostic_no_activation",false);
        if(!activationEnabled&&!settings.optBoolean("diagnostic_only",false))throw new IOException("Disabled activation is restricted to a diagnostic model");
        threshold=settings.getDouble("threshold");patience=settings.optInt("patience",1);minEmbeddingFrames=settings.optInt("min_embedding_frames",26);
        if(threshold<=0||threshold>=1||patience<1||patience>5||minEmbeddingFrames<26||minEmbeddingFrames>100)throw new IOException("Invalid wake operating threshold");
        Class<?> envClass=Class.forName("ai.onnxruntime.OrtEnvironment");
        environment=envClass.getMethod("getEnvironment").invoke(null);
        envClass.getMethod("setTelemetry",boolean.class).invoke(environment,false);
        createTensor=Class.forName("ai.onnxruntime.OnnxTensor").getMethod("createTensor",envClass,FloatBuffer.class,long[].class);
        melSession=new Session(envClass,asset(assets,"voice/openwake/melspectrogram.onnx"));
        embeddingSession=featureType.equals("embedding")?new Session(envClass,asset(assets,"voice/openwake/embedding_model.onnx")):null;
        headSession=new Session(envClass,asset(assets,"voice/openwake/classifier.onnx"));
        reset();
    }

    final class Session implements AutoCloseable {
        final Object value;final String input;final Method run;
        Session(Class<?> envClass,byte[] model)throws Exception {
            Class<?> optionsClass=Class.forName("ai.onnxruntime.OrtSession$SessionOptions");
            Object options=optionsClass.getConstructor().newInstance();
            try{
                optionsClass.getMethod("setIntraOpNumThreads",int.class).invoke(options,1);
                optionsClass.getMethod("setInterOpNumThreads",int.class).invoke(options,1);
                value=envClass.getMethod("createSession",byte[].class,optionsClass).invoke(environment,model,options);
            }finally{((AutoCloseable)options).close();}
            input=(String)((Set<?>)value.getClass().getMethod("getInputNames").invoke(value)).iterator().next();
            run=value.getClass().getMethod("run",Map.class);
        }
        float[] infer(float[] samples,long... shape)throws Exception {
            Object tensor=createTensor.invoke(null,environment,FloatBuffer.wrap(samples),shape),result=null;
            try{
                result=run.invoke(value,Collections.singletonMap(input,tensor));
                Object output=result.getClass().getMethod("get",int.class).invoke(result,0);
                FloatBuffer buffer=(FloatBuffer)output.getClass().getMethod("getFloatBuffer").invoke(output);
                float[] data=new float[buffer.remaining()];buffer.get(data);return data;
            }finally{if(result!=null)((AutoCloseable)result).close();((AutoCloseable)tensor).close();}
        }
        public void close()throws Exception{((AutoCloseable)value).close();}
    }

    public synchronized void reset(){audioSize=accumulated=embeddingCount=positiveFrames=0;lastScore=0;Arrays.fill(audio,0);Arrays.fill(mel,1);Arrays.fill(features,0);}

    private static void append(float[] buffer,float[] values){
        int keep=Math.min(values.length,buffer.length),shift=buffer.length-keep;
        System.arraycopy(buffer,keep,buffer,0,shift);System.arraycopy(values,values.length-keep,buffer,shift,keep);
    }

    public synchronized boolean accept(short[] frame,int length){
        if(!ready)return false;
        try{
            for(int n=0;n<length;n++){
                // Inputs use raw PCM16 float scale, matching the frozen mel model.
                if(audioSize==audio.length){System.arraycopy(audio,1,audio,0,audio.length-1);audioSize--;}
                audio[audioSize++]=frame[n];accumulated++;
                if(accumulated!=HOP)continue;
                float[] pcm=Arrays.copyOf(audio,audioSize);float[] nextMel=melSession.infer(pcm,1,pcm.length);
                if(nextMel.length%MEL_BINS!=0||nextMel.length==0)throw new IOException("Wake mel shape changed");
                for(int k=0;k<nextMel.length;k++)nextMel[k]=nextMel[k]/10f+2f;
                append(mel,nextMel);
                if(embeddingSession!=null){
                    float[] embedding=embeddingSession.infer(mel,1,MEL_FRAMES,MEL_BINS,1);
                    if(embedding.length!=EMBED_DIM)throw new IOException("Wake embedding shape changed");
                    append(features,embedding);
                }
                embeddingCount++;
                // Retain exactly the 30ms overlap for the next 80ms chunk.
                int retained=Math.min(OVERLAP,audioSize);System.arraycopy(audio,audioSize-retained,audio,0,retained);audioSize=retained;accumulated=0;
                // Suppress all 26 cold-start blocks; first scored block has index 26.
                if(embeddingCount<=minEmbeddingFrames)continue;
                float[] prediction=featureType.equals("logmel-cnn")?headSession.infer(mel,1,1,melFrames,MEL_BINS):headSession.infer(features,1,EMBED_FRAMES,EMBED_DIM);
                if(prediction.length!=1)throw new IOException("Wake classifier shape changed");
                if(!Float.isFinite(prediction[0])||prediction[0]<0||prediction[0]>1)throw new IOException("Invalid wake probability");
                lastScore=prediction[0];positiveFrames=lastScore>=threshold?positiveFrames+1:0;
                if(activationEnabled&&positiveFrames>=patience){reset();return true;}
            }
            return false;
        }catch(Exception error){ready=false;throw new IllegalStateException("Custom wake detector stopped",error);}
    }
    public float score(){return lastScore;}
    public boolean available(){return ready;}
    public String name(){return "Custom neural Hey Chat · experimental";}
    public synchronized void close(){ready=false;for(Session session:new Session[]{melSession,embeddingSession,headSession})if(session!=null)try{session.close();}catch(Exception ignored){}}
}
