package com.personalassistant.companion;

import android.content.Context;
import java.io.*;
import java.lang.reflect.Method;
import java.security.MessageDigest;
import java.util.Arrays;
import org.json.*;

/** Optional local streaming ASR wake policy; no microphone, cloud key or endpoint wait. */
public final class VoskWakeDetector implements WakeDetector {
    private static final String ASSET="voice/vosk/",GRAMMAR="[\"hey chat\",\"hey cat\",\"hey chad\",\"hey jack\",\"hey pat\",\"hey charles\",\"hate chatting\",\"[unk]\"]";
    private Object model,recognizer;private Class<?> modelClass,recognizerClass;
    private Method accept,getPartial,getResult;private final short[] frame=new short[320];
    private int pending,stableSamples;private long totalSamples,activationSamples=-1;private boolean ready,triggered,inactiveDiagnostic;
    private String lastPartial="";private int detectorGain=1;
    public static WakeDetector create(Context context)throws Exception {
        try{context.getAssets().open(ASSET+"settings.json").close();Class.forName("org.vosk.Model");}
        catch(FileNotFoundException|ClassNotFoundException missing){return null;}
        try{return new VoskWakeDetector(context.getApplicationContext());}
        catch(LinkageError error){throw new IOException("Vosk wake runtime is incompatible with this phone",error);}
    }
    private VoskWakeDetector(Context context)throws Exception {
        JSONObject settings=new JSONObject(new String(read(context.getAssets().open(ASSET+"settings.json")),"UTF-8"));
        if(settings.getInt("schema_version")!=1||settings.getInt("sample_rate")!=16000||settings.getInt("frame_samples")!=320||settings.getInt("stable_samples")!=1280||!settings.getJSONArray("grammar").toString().equals(GRAMMAR))throw new IOException("Unsupported Vosk wake policy");
        detectorGain="sensitive".equals(Cloud.prefs(context).getString("wake_sensitivity","balanced"))?2:1;
        inactiveDiagnostic=settings.optBoolean("diagnostic_no_activation",false);
        if(inactiveDiagnostic&&!settings.optBoolean("diagnostic_only",false))throw new IOException("Inactive wake policy requires diagnostic metadata");
        String identity=settings.getString("model_identity");if(!identity.matches("[a-f0-9]{64}"))throw new IOException("Invalid Vosk model identity");
        File folder=new File(context.getFilesDir(),"wake-vosk-"+identity),complete=new File(folder,".complete");
        if(!complete.exists()){
            if(!folder.isDirectory()&&!folder.mkdirs())throw new IOException("Cannot prepare Vosk model directory");
            JSONArray files=settings.getJSONArray("model_files");String base=folder.getCanonicalPath()+File.separator;
            for(int index=0;index<files.length();index++){
                JSONObject item=files.getJSONObject(index);String name=item.getString("path");
                if(!name.matches("[A-Za-z0-9._/-]+")||name.contains(".."))throw new IOException("Invalid Vosk model asset path");
                File file=new File(folder,name);if(!file.getCanonicalPath().startsWith(base))throw new IOException("Model asset outside cache");
                if(!file.getParentFile().isDirectory()&&!file.getParentFile().mkdirs())throw new IOException("Cannot prepare Vosk model file");
                MessageDigest digest=MessageDigest.getInstance("SHA-256");try(InputStream input=context.getAssets().open(ASSET+"model/"+name);OutputStream output=new FileOutputStream(file)){
                    byte[] bytes=new byte[65536];int count;while((count=input.read(bytes))!=-1){digest.update(bytes,0,count);output.write(bytes,0,count);}
                }
                if(!hex(digest.digest()).equals(item.getString("sha256")))throw new IOException("Vosk model checksum mismatch");
            }
            try(OutputStream marker=new FileOutputStream(complete)){marker.write(identity.getBytes("US-ASCII"));}
        }
        modelClass=Class.forName("org.vosk.Model");recognizerClass=Class.forName("org.vosk.Recognizer");
        model=modelClass.getConstructor(String.class).newInstance(folder.getAbsolutePath());
        try{accept=recognizerClass.getMethod("acceptWaveForm",short[].class,int.class);getPartial=recognizerClass.getMethod("getPartialResult");getResult=recognizerClass.getMethod("getResult");recognizer=newRecognizer();ready=true;}
        catch(Exception error){modelClass.getMethod("close").invoke(model);model=null;throw error;}
    }
    private Object newRecognizer()throws Exception {
        Object value=recognizerClass.getConstructor(modelClass,float.class,String.class).newInstance(model,16000f,GRAMMAR);
        recognizerClass.getMethod("setPartialWords",boolean.class).invoke(value,false);
        recognizerClass.getMethod("setWords",boolean.class).invoke(value,true);return value;
    }
    static boolean wake(String text){String[] words=text.toLowerCase(java.util.Locale.ROOT).trim().split("\\s+");for(int index=0;index+1<words.length;index++)if(words[index].equals("hey")&&words[index+1].equals("chat"))return true;return false;}
    public synchronized boolean accept(short[] data,int length){
        if(length<0||length>data.length)throw new IllegalArgumentException("PCM length");if(!ready||triggered)return false;
        try{int offset=0;while(offset<length){int count=Math.min(320-pending,length-offset);for(int i=0;i<count;i++)frame[pending+i]=(short)Math.max(-32768,Math.min(32767,(int)data[offset+i]*detectorGain));pending+=count;offset+=count;
            if(pending==320){pending=0;totalSamples+=320;boolean endpoint=(Boolean)accept.invoke(recognizer,frame,320);
                JSONObject result=new JSONObject((String)(endpoint?getResult:getPartial).invoke(recognizer));lastPartial=result.optString(endpoint?"text":"partial","");
                // Final results do not shortcut the selected partial-only stability policy.
                if(!endpoint&&wake(lastPartial))stableSamples+=320;else stableSamples=0;
                if(stableSamples>=1280){triggered=true;activationSamples=totalSamples;return !inactiveDiagnostic;}
            }
        }return false;}catch(Exception error){ready=false;throw new IllegalStateException("Vosk wake detector stopped",error);}
    }
    public synchronized void reset(){if(!ready)return;try{Object next=newRecognizer(),old=recognizer;recognizer=next;recognizerClass.getMethod("close").invoke(old);pending=stableSamples=0;totalSamples=0;activationSamples=-1;lastPartial="";triggered=false;Arrays.fill(frame,(short)0);}catch(Exception error){ready=false;throw new IllegalStateException("Vosk stream reset failed",error);}}
    public boolean available(){return ready;}
    /** Amplification is isolated to recognizer input; capture and transport retain original PCM. */
    public synchronized void sensitivity(boolean sensitive){int gain=sensitive?2:1;if(detectorGain!=gain){detectorGain=gain;reset();}}
    public String name(){return "Vosk local Hey Chat · experimental";}
    long activationSamples(){return activationSamples;}
    String partial(){return lastPartial;}
    boolean candidateTriggered(){return triggered;}
    public synchronized void close(){ready=false;try{if(recognizer!=null)recognizerClass.getMethod("close").invoke(recognizer);}catch(Exception ignored){}try{if(model!=null)modelClass.getMethod("close").invoke(model);}catch(Exception ignored){}recognizer=null;model=null;}
    private static byte[] read(InputStream input)throws IOException{try(InputStream source=input;ByteArrayOutputStream output=new ByteArrayOutputStream()){byte[] bytes=new byte[8192];int count;while((count=source.read(bytes))!=-1)output.write(bytes,0,count);return output.toByteArray();}}
    private static String hex(byte[] bytes){StringBuilder value=new StringBuilder();for(byte b:bytes)value.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return value.toString();}
}
