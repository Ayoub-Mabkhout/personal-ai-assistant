package com.personalassistant.companion;

import android.content.*;
import android.media.AudioManager;
import android.os.Looper;
import android.util.Timeline;
import java.util.*;
import java.util.concurrent.*;

/**
 * Drives the real VoiceService record loop with scripted microphone frames and a scripted Hey Chat model, against the shims of
 * tests/test_task_voice.py: no phone, microphone, network or paid service. The harness plays TaskVoice's part through the task
 * host VoiceService hands over, and prints one JSON object describing each scenario.
 */
public final class TaskVoiceServiceHarness {
    /** Frame markers: the wake word, a sound made just before a Talk tap, and speech. */
    static final short WAKE=12345,BEFORE=777,SPEECH=3000;
    static final Context app=new Context();

    /** The microphone plays scripted frames, then silence, paced so the record loop never spins; the wake model hears WAKE frames. */
    static final class Phone extends VoiceService {
        final BlockingQueue<short[]> frames=new LinkedBlockingQueue<short[]>();
        @Override protected int readMicrophone(short[] frame){short[] next=null;try{next=frames.poll(2,TimeUnit.MILLISECONDS);}catch(InterruptedException e){Thread.currentThread().interrupt();}if(next==null)Arrays.fill(frame,(short)0);else System.arraycopy(next,0,frame,0,frame.length);return frame.length;}
        @Override WakeDetector loadDetector(){return new WakeDetector(){public boolean accept(short[] f,int n){if(f[0]!=WAKE)return false;Timeline.add("wake");return true;}public boolean available(){return true;}public String name(){return "Scripted wake";}public void reset(){}};}
        void say(int speech,int silence){for(int i=0;i<speech;i++)frames.add(filled(SPEECH));for(int i=0;i<silence;i++)frames.add(filled((short)0));}
        /** "Hey Chat", then a command long enough for a wake capture to finish. */
        void heyChat(){short[] wake=new short[320];wake[0]=WAKE;frames.add(wake);say(45,70);}
    }
    static short[] filled(short value){short[] frame=new short[320];Arrays.fill(frame,value);return frame;}

    static SharedPreferences prefs(){return Cloud.prefs(app);}
    static void until(java.util.function.BooleanSupplier done,String what)throws Exception{long end=System.currentTimeMillis()+10000;while(!done.getAsBoolean()){if(System.currentTimeMillis()>end)throw new IllegalStateException("Timed out waiting for "+what+": "+Timeline.copy());Thread.sleep(1);}}
    static boolean logged(String event){return Timeline.copy().contains(event);}
    static long captures(){return prefs().getLong("voice_capture_started_ns",0);}

    static Phone start(boolean wake)throws Exception{
        prefs().clear();AudioManager.INSTANCE.reset();Timeline.events.clear();TaskVoice.hosts.clear();TaskVoice.notes.clear();VoiceOutbox.saved.clear();
        prefs().edit().putBoolean("wake_enabled",wake).commit();Phone phone=new Phone();Looper.run(phone::onCreate);return phone;
    }
    static void intent(Phone phone,String action,String task)throws Exception{Intent i=new Intent(app,VoiceService.class).setAction(action);if(task!=null)i.putExtra("task_id",task);Looper.run(()->phone.onStartCommand(i,0,1));}
    /** Taps an action that starts a capture, waits for the capture, then speaks into it. */
    static void tapAndSpeak(Phone phone,String action,String task)throws Exception{long before=captures();intent(phone,action,task);until(()->captures()!=before,"a capture after "+action);phone.say(20,70);}
    /** TaskVoice's part once a task turn is transcribed and saved: "Sent.", then the server holds it and the recorder is free. */
    static TaskVoice.Host held(int turn)throws Exception{
        until(()->TaskVoice.hosts.size()>turn,"task turn "+turn);TaskVoice.Host host=TaskVoice.hosts.get(turn);
        host.state("Transcribing your words…");host.state("Sent to this task · waiting for the task's answer");host.sent();host.released();Looper.idle();return host;
    }
    /** The record loop writes its activity every 200 ms; wait for a fresh write, then read it with what BatterySampler records for it. */
    static Map<String,Object> settled()throws Exception{
        Thread.sleep(300);boolean active=prefs().getBoolean("voice_conversation_active",false),conversation=prefs().getBoolean("voice_conversation_mode",false);String task=prefs().getString("task_voice","");
        Map<String,Object> state=new LinkedHashMap<String,Object>();state.put("voice_conversation_active",active);state.put("voice_conversation_mode",conversation);state.put("task_voice",task);
        state.put("battery_mode",BatteryUsage.mode(true,prefs().getBoolean("wake_enabled",false),active,conversation,task));return state;
    }
    static Map<String,Object> report(String failure)throws Exception{
        Looper.idle();Map<String,Object> row=new LinkedHashMap<String,Object>();row.put("events",Timeline.copy());
        List<String> commands=new ArrayList<String>();for(short[] pcm:VoiceOutbox.saved){boolean wake=false,before=false;for(short s:pcm){wake|=s==WAKE;before|=s==BEFORE;}commands.add((wake?"wake ":"")+(before?"before ":"")+"command");}
        row.put("commands",commands);row.put("task_turns",TaskVoice.hosts.size());row.put("notes",new ArrayList<String>(TaskVoice.notes));
        row.put("conversation_mode",prefs().getBoolean("voice_conversation_mode",false));row.put("task_voice",prefs().getString("task_voice",""));row.put("voice_status",prefs().getString("voice_status",""));
        row.put("audio_mode",AudioManager.INSTANCE.getMode()==AudioManager.MODE_NORMAL?"normal":"communication");row.put("speakerphone",AudioManager.INSTANCE.isSpeakerphoneOn());
        if(failure!=null)row.put("failure",failure);return row;
    }
    static void stop(Phone phone)throws Exception{Looper.run(phone::onDestroy);for(Thread t:Thread.getAllStackTraces().keySet())if(t.getName().equals("assistant-microphone"))t.join(5000);Looper.idle();}
    /** After a command started while the task answer was awaited: the late answer arrives. */
    static Map<String,Object> lateAnswer(TaskVoice.Host first)throws Exception{
        until(()->!VoiceOutbox.saved.isEmpty()||TaskVoice.hosts.size()>1,"the command");
        if(!VoiceOutbox.saved.isEmpty())until(()->"Listening locally for Hey Chat".equals(prefs().getString("voice_status","")),"the command's reply");else Thread.sleep(300);
        first.reply("The answer for task-1.",false);Thread.sleep(200);Map<String,Object> row=report(null);row.put("first_turn_current",first.current());row.put("first_turn_talking",first.talking());return row;
    }

    /** Hey Chat while the task's answer is awaited. */
    static Map<String,Object> wake()throws Exception{
        Phone phone=start(true);try{tapAndSpeak(phone,VoiceService.TASK_TALK,"task-1");TaskVoice.Host first=held(0);Map<String,Object> awaiting=settled();
            phone.heyChat();Map<String,Object> row=lateAnswer(first);row.put("awaiting",awaiting);return row;}
        catch(IllegalStateException timeout){return report(timeout.getMessage());}finally{stop(phone);}
    }
    /** The notification's (or the lock screen entry's) Talk while the task's answer is awaited. */
    static Map<String,Object> talk()throws Exception{
        Phone phone=start(true);try{tapAndSpeak(phone,VoiceService.TASK_TALK,"task-1");TaskVoice.Host first=held(0);
            phone.frames.add(filled(BEFORE));until(phone.frames::isEmpty,"the sound before Talk");tapAndSpeak(phone,VoiceService.TALK,null);return lateAnswer(first);}
        catch(IllegalStateException timeout){return report(timeout.getMessage());}finally{stop(phone);}
    }
    /** The answer is read aloud, the next spoken turn in the follow-up window goes to the task, and That was all ends it. */
    static Map<String,Object> window()throws Exception{
        Phone phone=start(true);try{tapAndSpeak(phone,VoiceService.TASK_TALK,"task-1");TaskVoice.Host first=held(0);
            first.reply("The answer for task-1.",false);until(()->"Conversation mode · listening".equals(prefs().getString("voice_status","")),"the follow-up window");
            phone.say(20,70);until(()->TaskVoice.hosts.size()>1||!VoiceOutbox.saved.isEmpty(),"the follow-up turn");Map<String,Object> during=settled();during.put("audio_mode",AudioManager.INSTANCE.getMode()==AudioManager.MODE_NORMAL?"normal":"communication");
            if(TaskVoice.hosts.size()>1){TaskVoice.Host second=TaskVoice.hosts.get(1);second.state("Transcribing your words…");second.reply("Conversation ended.",true);until(()->"Listening locally for Hey Chat".equals(prefs().getString("voice_status","")),"the end of the conversation");}
            Map<String,Object> row=report(null);row.put("follow_up_turn",during);return row;}
        catch(IllegalStateException timeout){return report(timeout.getMessage());}finally{stop(phone);}
    }
    /** Hey Chat with no task: master's ordinary command path. */
    static Map<String,Object> ordinary()throws Exception{
        Phone phone=start(true);try{intent(phone,null,null);until(()->logged("input:recognition"),"the recorder");phone.heyChat();
            until(()->!VoiceOutbox.saved.isEmpty(),"the command");until(()->"Listening locally for Hey Chat".equals(prefs().getString("voice_status","")),"the command's reply");return report(null);}
        catch(IllegalStateException timeout){return report(timeout.getMessage());}finally{stop(phone);}
    }

    /** ASCII JSON, so the report survives any console code page. */
    static String quote(String s){StringBuilder b=new StringBuilder("\"");for(char ch:s.toCharArray()){if(ch=='"'||ch=='\\')b.append('\\').append(ch);else if(ch<0x20||ch>0x7e)b.append(String.format("\\u%04x",(int)ch));else b.append(ch);}return b.append('"').toString();}
    static String json(Object v){
        if(v instanceof String)return quote((String)v);
        if(v instanceof Map){StringBuilder b=new StringBuilder("{");for(Map.Entry<?,?> e:((Map<?,?>)v).entrySet()){if(b.length()>1)b.append(',');b.append(quote(String.valueOf(e.getKey()))).append(':').append(json(e.getValue()));}return b.append('}').toString();}
        if(v instanceof Collection){StringBuilder b=new StringBuilder("[");for(Object item:(Collection<?>)v){if(b.length()>1)b.append(',');b.append(json(item));}return b.append(']').toString();}
        return String.valueOf(v);
    }

    public static void main(String[] args)throws Exception{
        Map<String,Object> result=new LinkedHashMap<String,Object>();
        result.put("wake",wake());result.put("talk",talk());result.put("window",window());result.put("ordinary",ordinary());
        System.out.println(json(result));System.exit(0);
    }
}
