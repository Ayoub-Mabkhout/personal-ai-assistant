package com.personalassistant.companion;

import android.content.Context;
import android.util.AtomicFile;
import org.json.*;
import java.io.*;
import java.util.*;

/** Private, bounded chat log. Streaming revisions update one bubble, not many copies. */
final class VoiceChat {
    private static final Object lock=new Object();
    private static AtomicFile store(Context c){return new AtomicFile(new File(c.getFilesDir(),"voice-chat.json"));}
    static void user(Context c,String id,String text,long time){put(c,id,"user",text,time,"request","");}
    static void assistant(Context c,String id,String text,long time){put(c,id,"assistant",text,time,"answer","");}
    static void assistant(Context c,String id,String text,long time,String kind,String taskId){put(c,id,"assistant",text,time,kind,taskId);}
    private static void put(Context c,String id,String role,String text,long time,String kind,String taskId){
        if(text==null||text.trim().isEmpty()||id==null||id.isEmpty())return;
        synchronized(lock){try{JSONArray entries=history(c);JSONObject item=null;for(int n=0;n<entries.length();n++){JSONObject existing=entries.getJSONObject(n);if(id.equals(existing.optString("id"))&&role.equals(existing.optString("role"))){item=existing;break;}}
            if(item==null){item=new JSONObject().put("id",id).put("role",role).put("time",time>0?time:System.currentTimeMillis());entries.put(item);}item.put("text",text.length()>16000?text.substring(0,16000):text).put("kind",kind==null?"answer":kind).put("task_id",taskId==null?"":taskId);
            ArrayList<JSONObject> sorted=new ArrayList<>();for(int n=0;n<entries.length();n++)sorted.add(entries.getJSONObject(n));Collections.sort(sorted,(a,b)->Long.compare(a.optLong("time"),b.optLong("time")));JSONArray bounded=new JSONArray();for(int n=Math.max(0,sorted.size()-300);n<sorted.size();n++)bounded.put(sorted.get(n));AtomicFile target=store(c);FileOutputStream out=null;try{out=target.startWrite();out.write(bounded.toString().getBytes("UTF-8"));target.finishWrite(out);}catch(Exception error){if(out!=null)target.failWrite(out);throw error;}
            Cloud.prefs(c).edit().putLong("voice_chat_updated_at",Math.max(System.currentTimeMillis(),Cloud.prefs(c).getLong("voice_chat_updated_at",0)+1)).apply();
        }catch(Exception error){Cloud.prefs(c).edit().putString("voice_history_error","Recent conversation could not be saved.").apply();}}
    }
    static JSONArray history(Context c){synchronized(lock){try{byte[] bytes=store(c).readFully();if(bytes.length>6000000)throw new IOException("Chat history is too large");return new JSONArray(new String(bytes,"UTF-8"));}catch(Exception ignored){return new JSONArray();}}}
    static void importReceipts(Context c){synchronized(lock){if(Cloud.prefs(c).getBoolean("voice_chat_imported",false))return;File[] files=new File(c.getFilesDir(),"voice-receipts").listFiles((d,n)->n.endsWith(".json"));if(files!=null){Arrays.sort(files,Comparator.comparingLong(File::lastModified));for(File file:files)try{JSONObject r=new JSONObject(VoiceOutbox.read(file));String id=r.optString("id",file.getName());user(c,id,r.optString("text"),file.lastModified());String task=r.optString("task_id");assistant(c,id,r.optString("reply",r.optString("status")),file.lastModified(),task.isEmpty()?"answer":"acknowledgement",task);}catch(Exception ignored){}}Cloud.prefs(c).edit().putBoolean("voice_chat_imported",true).apply();}}
}
