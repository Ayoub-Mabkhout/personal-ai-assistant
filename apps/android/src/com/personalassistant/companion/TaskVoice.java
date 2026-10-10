package com.personalassistant.companion;

import android.content.*;
import org.json.*;
import java.io.IOException;
import java.util.UUID;

/**
 * Voice on the task details screen, driven by VoiceService's single recorder.
 * Dictation uses the dry-run transcription endpoint, which never executes: the words wait for the user's own Send.
 * A task conversation saves each spoken turn as a stable-ID follow-up of the same task (never a new command or a live
 * session), then reads that turn's answer aloud. Once the server holds the turn, the microphone is free again while the
 * answer is awaited in the background; it is only read aloud if no newer turn began and the conversation is still on.
 */
final class TaskVoice {
    /**
     * VoiceService callbacks; every one is ignored once the user ends or replaces the turn. current: no newer capture or turn
     * began. talking: also, this task's conversation is still the active one. released: the server holds the follow-up, so
     * the recorder may serve Hey Chat, Talk and barge-in again while the answer is awaited.
     */
    interface Host {boolean current();boolean talking();void state(String message);void sent();void released();void reply(String text,boolean end);void done(String message);}
    static final long ANSWER_WAIT_MS=10*60000L;
    private TaskVoice(){}

    private static boolean valid(String id){return id!=null&&id.matches("[A-Za-z0-9_-]{1,160}");}
    /** Target "dictate:ID" or "talk:ID"; null when malformed. */
    static Intent intent(Context c,String target){
        int colon=target==null?-1:target.indexOf(':');if(colon<0)return null;String mode=target.substring(0,colon),id=target.substring(colon+1);
        if(!valid(id)||!(mode.equals("dictate")||mode.equals("talk")))return null;
        return new Intent(c,VoiceService.class).setAction(mode.equals("dictate")?VoiceService.TASK_DICTATE:VoiceService.TASK_TALK).putExtra("task_id",id);
    }
    /** Stop dictation: the words already said are still transcribed into the draft; null when the ID is malformed. */
    static Intent finish(Context c,String id){return valid(id)?new Intent(c,VoiceService.class).setAction(VoiceService.TASK_FINISH).putExtra("task_id",id):null;}
    /** dictate, talk or "" for this task, only while the microphone service is actually running. */
    static String mode(Context c,String id){if(!AppUi.micActive(c))return "";String value=Cloud.prefs(c).getString("task_voice","");return value.equals("dictate:"+id)?"dictate":value.equals("talk:"+id)?"talk":"";}
    /** Another voice conversation or task currently owns the microphone. */
    static boolean busy(Context c,String id){
        if(!AppUi.micActive(c))return false;SharedPreferences p=Cloud.prefs(c);String value=p.getString("task_voice","");
        if(value.endsWith(":"+id))return false;return !value.isEmpty()||p.getBoolean("voice_conversation_active",false)||p.getBoolean("voice_conversation_mode",false);
    }

    /**
     * Dictated words wait on the phone until that task's screen takes them into its draft. Each read-and-write is atomic under
     * the class lock; apply() updates memory at once and writes to disk off the lock, so the screen's main-thread take on every
     * voice broadcast and tick never waits for a disk write.
     */
    static synchronized void deliver(Context c,String task,String text){
        String key="task_dictation:"+task,old=Cloud.prefs(c).getString(key,"");Cloud.prefs(c).edit().putString(key,old.isEmpty()?text:old+" "+text).apply();
    }
    static synchronized String take(Context c,String task){String key="task_dictation:"+task,value=Cloud.prefs(c).getString(key,"");if(!value.isEmpty())Cloud.prefs(c).edit().remove(key).apply();return value;}
    static synchronized void note(Context c,String task,String text){if(task!=null)Cloud.prefs(c).edit().putString("task_voice_note:"+task,text).apply();}
    static synchronized String takeNote(Context c,String task){String key="task_voice_note:"+task,value=Cloud.prefs(c).getString(key,"");if(!value.isEmpty())Cloud.prefs(c).edit().remove(key).apply();return value;}

    /** Dry-run upload of one capture. The server transcribes and returns without dispatching anything. */
    static String transcribe(Context c,short[] pcm,String id)throws Exception{
        JSONObject result=VoiceOutbox.upload(c,VoiceOutbox.envelope(id,pcm,"",true));
        if(!"transcribed".equals(result.optString("status")))throw new IOException("Transcription unavailable");
        return result.optString("text","").trim();
    }

    static void turn(Context c,short[] pcm,String task,boolean dictation,boolean preview,Host host){
        Context app=c.getApplicationContext();new Thread(()->run(app,pcm,task,dictation,preview,host),"assistant-task-voice").start();
    }

    private static void end(Context c,String task,Host host,String text){note(c,task,text);host.reply(text,true);}

    private static void run(Context c,short[] pcm,String task,boolean dictation,boolean preview,Host host){
        String id=UUID.randomUUID().toString(),text;host.state("Transcribing your words…");
        try{text=transcribe(c,pcm,id);}
        catch(Exception error){
            if(!host.current())return;String reason=VoiceOutbox.networkReady(c)?"Could not transcribe that":"No internet · could not transcribe that";
            if(dictation){note(c,task,reason+" · your draft is unchanged.");host.done(reason);}else end(c,task,host,reason+". Talk about this task again when you are connected.");return;
        }
        if(!host.current())return;
        if(dictation||preview){
            if(!text.isEmpty())deliver(c,task,text);note(c,task,text.isEmpty()?"No speech heard · your draft is unchanged.":"Added to your draft · edit it, then tap Send.");
            if(dictation)host.done(text.isEmpty()?"No speech heard":"Dictation added to the task draft · nothing was sent");
            else host.reply(text.isEmpty()?"I didn't catch that.":"Transcription preview is on, so nothing was sent. I added that to your draft.",false);
            return;
        }
        String control=TaskTurns.control(text);
        if(text.isEmpty()){host.reply("I didn't catch that. Say it again, or say That was all to finish.",false);return;}
        if("end".equals(control)){end(c,task,host,"Conversation ended.");return;}
        if("start".equals(control)){host.reply("We are already talking about this task. Go ahead.",false);return;}
        try{NativeTasks.enqueueFollowupWithId(c,task,text,id);}catch(Exception error){end(c,task,host,"Could not save that follow-up on this phone.");return;}
        host.state("Sent to this task · waiting for the task's answer");host.sent();
        try{NativeTasks.flush(c);}catch(Exception ignored){}
        String pending=pendingState(c,id);
        if("needs_review".equals(pending)){end(c,task,host,"The task did not accept that follow-up. It is kept on this phone for review.");return;}
        if(pending!=null){end(c,task,host,"Saved on this phone. It will be sent to the task when you are connected.");return;}
        host.released();
        await(c,task,TaskTurns.turnId(id),host);
    }

    /**
     * Polls the task in the background until this turn settles; the screen refreshes on each state change. The answer is read
     * aloud only while this conversation is still on and no newer turn began; otherwise the task screen and its notification
     * carry it, and polling stops.
     */
    private static void await(Context c,String task,String turn,Host host){
        long start=System.currentTimeMillis();String seen="";int polls=0;
        while(host.talking()&&System.currentTimeMillis()-start<ANSWER_WAIT_MS){
            if(!pause(host,polls++<10?3000:6000))return;
            try{
                JSONObject detail=NativeTasks.detail(c,"agent",task),mine=null;JSONArray turns=detail.optJSONArray("turns");
                for(int n=0;turns!=null&&n<turns.length();n++){JSONObject t=turns.optJSONObject(n);if(t!=null&&turn.equals(t.optString("id")))mine=t;}
                if(mine==null)continue;String state=mine.optString("state");if(!state.equals(seen)){seen=state;NativeTasks.changed(c);}
                if(!TaskTurns.outcome(state).equals("wait")){if(host.talking())host.reply(TaskTurns.spoken(state,mine.optString("summary")),false);return;}
                JSONObject connection=detail.optJSONObject("connection");
                if("queued".equals(state)&&connection!=null&&!"ready".equals(connection.optString("laptop","ready"))&&System.currentTimeMillis()-start>20000){end(c,task,host,"Sent. The laptop is not connected, so the answer will appear in this task later.");return;}
            }catch(Exception ignored){}
        }
        if(host.talking())end(c,task,host,"The task is still working. Its answer will appear in this task.");
    }
    private static boolean pause(Host host,long ms){long until=System.currentTimeMillis()+ms;while(System.currentTimeMillis()<until){if(!host.talking())return false;try{Thread.sleep(250);}catch(InterruptedException stop){Thread.currentThread().interrupt();return false;}}return host.talking();}
    /** null once the server acknowledged the follow-up; otherwise its outbox state. */
    private static String pendingState(Context c,String id){
        try{JSONArray rows=NativeTasks.pending(c);for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);if(id.equals(row.optString("id")))return row.optString("state","saved");}}catch(Exception error){return "saved";}
        return null;
    }
}
