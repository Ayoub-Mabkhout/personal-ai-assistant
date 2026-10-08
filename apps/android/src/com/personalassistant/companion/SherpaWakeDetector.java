package com.personalassistant.companion;

import android.content.Context;
import android.content.res.AssetManager;
import java.lang.reflect.Method;

/** Optional open-vocabulary neural detector, pinned runtime supplied by builder. */
public final class SherpaWakeDetector implements WakeDetector {
    private Object spotter,stream;
    private Method accept,isReady,decode,getResult,reset,getKeyword,createStream;
    private boolean ready;
    private static final String PREFIX="com.k2fsa.sherpa.onnx.";
    private static Object config(String name)throws Exception{return Class.forName(PREFIX+name).getConstructor().newInstance();}
    private static void set(Object object,String name,Class<?> type,Object value)throws Exception{object.getClass().getMethod(name,type).invoke(object,value);}

    public static WakeDetector create(Context context)throws Exception {
        try{context.getAssets().open("voice/sherpa/keywords.txt").close();Class.forName(PREFIX+"KeywordSpotterConfig");}
        catch(java.io.FileNotFoundException|ClassNotFoundException absent){return null;}
        try{return new SherpaWakeDetector(context.getAssets());}
        catch(LinkageError error){throw new java.io.IOException("Native wake runtime is incompatible with this phone",error);}
    }

    private SherpaWakeDetector(AssetManager assets)throws Exception {
        Object transducer=config("OnlineTransducerModelConfig");
        set(transducer,"setEncoder",String.class,"voice/sherpa/encoder.onnx");
        set(transducer,"setDecoder",String.class,"voice/sherpa/decoder.onnx");
        set(transducer,"setJoiner",String.class,"voice/sherpa/joiner.onnx");
        Object model=config("OnlineModelConfig");
        set(model,"setTransducer",transducer.getClass(),transducer);
        set(model,"setTokens",String.class,"voice/sherpa/tokens.txt");
        set(model,"setNumThreads",int.class,1);
        set(model,"setProvider",String.class,"cpu");
        set(model,"setModelType",String.class,"zipformer2");
        Object cfg=config("KeywordSpotterConfig");
        set(cfg,"setModelConfig",model.getClass(),model);
        set(cfg,"setKeywordsFile",String.class,"voice/sherpa/keywords.txt");
        set(cfg,"setMaxActivePaths",int.class,4);
        set(cfg,"setNumTrailingBlanks",int.class,1);
        set(cfg,"setKeywordsScore",float.class,1.0f);
        set(cfg,"setKeywordsThreshold",float.class,0.25f);
        Class<?> spotterClass=Class.forName(PREFIX+"KeywordSpotter");
        spotter=spotterClass.getConstructor(AssetManager.class,cfg.getClass()).newInstance(assets,cfg);
        createStream=spotterClass.getMethod("createStream",String.class);
        stream=createStream.invoke(spotter,"");
        Class<?> streamClass=stream.getClass();
        accept=streamClass.getMethod("acceptWaveform",float[].class,int.class);
        isReady=spotterClass.getMethod("isReady",streamClass);decode=spotterClass.getMethod("decode",streamClass);
        getResult=spotterClass.getMethod("getResult",streamClass);reset=spotterClass.getMethod("reset",streamClass);
        getKeyword=Class.forName(PREFIX+"KeywordSpotterResult").getMethod("getKeyword");ready=true;
    }

    public synchronized boolean accept(short[] frame,int length){
        if(!ready)return false;
        try{
            float[] samples=new float[length];for(int i=0;i<length;i++)samples[i]=frame[i]/32768.0f;
            accept.invoke(stream,samples,16000);
            while((Boolean)isReady.invoke(spotter,stream)){
                decode.invoke(spotter,stream);String keyword=(String)getKeyword.invoke(getResult.invoke(spotter,stream));
                if(!keyword.isEmpty()){reset.invoke(spotter,stream);return true;}
            }
            return false;
        }catch(Exception error){ready=false;throw new IllegalStateException("Neural wake detector stopped",error);}
    }
    public boolean available(){return ready;}
    public String name(){return "Sherpa neural Hey Chat · experimental";}
    public synchronized void reset(){
        if(!ready)return;
        try{
            // KeywordSpotter.reset only resets decoding results; a fresh stream also
            // discards feature/encoder context without reloading the shared model.
            Object previous=stream;stream=createStream.invoke(spotter,"");
            previous.getClass().getMethod("release").invoke(previous);
        }catch(Exception error){ready=false;throw new IllegalStateException("Wake stream reset failed",error);}
    }
    public synchronized void close(){
        ready=false;
        try{if(stream!=null)stream.getClass().getMethod("release").invoke(stream);}catch(Exception ignored){}
        try{if(spotter!=null)spotter.getClass().getMethod("release").invoke(spotter);}catch(Exception ignored){}
        stream=null;spotter=null;
    }
}
