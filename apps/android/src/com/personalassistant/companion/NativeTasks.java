package com.personalassistant.companion;

import android.content.Context;
import android.content.Intent;
import org.json.*;
import java.net.URLEncoder;
import java.util.UUID;

/** Paired task data and a durable follow-up outbox. Network never holds the local lock. */
final class NativeTasks {
    static final String ACTION="com.personalassistant.companion.TASK_STATE";
    private static final Object network=new Object();
    static void changed(Context c){c.sendBroadcast(new Intent(ACTION).setPackage(c.getPackageName()));}
    private static String encode(String value)throws Exception{return URLEncoder.encode(value,"UTF-8");}
    static JSONObject history(Context c,String query)throws Exception{return history(c,query,null);}
    static JSONObject history(Context c,String query,String cursor)throws Exception{
        String path="tasks?q="+encode(query==null?"":query);if(cursor!=null&&!cursor.isEmpty())path+="&cursor="+encode(cursor);
        JSONObject result=(JSONObject)Cloud.call(c,path,null,true);
        if((query==null||query.isEmpty())&&(cursor==null||cursor.isEmpty()))Cloud.prefs(c).edit().putString("tasks_history",result.toString()).putLong("tasks_synced",System.currentTimeMillis()).commit();
        return result;
    }
    static JSONObject cachedHistory(Context c){try{return new JSONObject(Cloud.prefs(c).getString("tasks_history","{\"items\":[]}"));}catch(Exception e){return new JSONObject();}}
    private static String key(String kind,String id){return "task_detail_"+kind+"_"+id;}
    static JSONObject detail(Context c,String kind,String id)throws Exception{
        JSONObject result=(JSONObject)Cloud.call(c,"tasks/"+encode(kind)+"/"+encode(id),null,true);
        Cloud.prefs(c).edit().putString(key(kind,id),result.toString()).commit();return result;
    }
    static JSONObject cachedDetail(Context c,String kind,String id){try{return new JSONObject(Cloud.prefs(c).getString(key(kind,id),"{}"));}catch(Exception e){return new JSONObject();}}
    static synchronized JSONArray pending(Context c){try{return new JSONArray(Cloud.prefs(c).getString("task_followups","[]"));}catch(Exception e){throw new IllegalStateException("Saved follow-ups need recovery",e);}}
    static synchronized JSONArray newPending(Context c){try{return new JSONArray(Cloud.prefs(c).getString("task_new_outbox","[]"));}catch(Exception e){throw new IllegalStateException("Saved new tasks need recovery",e);}}
    static synchronized String enqueueNew(Context c,String text)throws Exception{
        if(text==null||text.trim().isEmpty()||text.length()>4096)throw new IllegalArgumentException("Enter a request up to 4096 characters");
        String id="typed-"+UUID.randomUUID().toString().replace("-","");JSONArray attachments=TaskAttachments.ids(TaskAttachments.draft(c,"new-task"));
        JSONObject body=new JSONObject().put("id",id).put("text",text).put("created_at",java.time.Instant.now().toString()).put("timezone",java.util.TimeZone.getDefault().getID());
        if(attachments.length()>0)body.put("attachments",attachments);else body.put("native_timers",true);
        JSONArray queue=newPending(c);queue.put(new JSONObject().put("id",id).put("body",body).put("origin",Cloud.prefs(c).getString("origin","")).put("state","saved"));
        if(!Cloud.prefs(c).edit().putString("task_new_outbox",queue.toString()).remove("quick_task_draft").remove("quick_task_id").remove("attachment_draft:new-task").commit())throw new Exception("Phone storage failed");
        TaskSyncJob.schedule(c,false);changed(c);return id;
    }
    static void flushNew(Context c)throws Exception{
        while(true){JSONObject row;synchronized(NativeTasks.class){JSONArray queue=newPending(c);if(queue.length()==0)return;row=queue.getJSONObject(0);}
            if(!row.optString("origin").equals(Cloud.prefs(c).getString("origin","")))throw new Exception("Saved task belongs to a different server; it remains on this phone");
            JSONObject body=row.getJSONObject("body");JSONArray ids=body.optJSONArray("attachments");boolean files=ids!=null&&ids.length()>0;
            if(files)TaskAttachments.upload(c,ids);
            JSONObject receipt=(JSONObject)Cloud.call(c,files?"tasks":"voice/text",body,true);
            synchronized(NativeTasks.class){JSONArray next=new JSONArray(),fresh=newPending(c);for(int n=0;n<fresh.length();n++)if(!row.getString("id").equals(fresh.getJSONObject(n).optString("id")))next.put(fresh.getJSONObject(n));if(!Cloud.prefs(c).edit().putString("task_new_outbox",next.toString()).putString("task_last_receipt",receipt.toString()).putString("task_new_receipt:"+row.getString("id"),receipt.toString()).commit())throw new Exception("Phone storage failed");}changed(c);
        }
    }
    static String enqueueFollowup(Context c,String id,String instruction)throws Exception{return enqueueFollowupWithId(c,id,instruction,UUID.randomUUID().toString());}
    static synchronized String enqueueFollowupWithId(Context c,String id,String instruction,String local)throws Exception{
        return enqueueFollowupWithId(c,id,instruction,local,new JSONArray());
    }
    static synchronized String enqueueFollowupWithId(Context c,String id,String instruction,String local,JSONArray attachments)throws Exception{
        if(instruction==null||instruction.trim().isEmpty()||instruction.length()>4096)throw new IllegalArgumentException("Enter an instruction up to 4096 characters");
        JSONArray pending=pending(c);for(int i=0;i<pending.length();i++){JSONObject old=pending.getJSONObject(i);if(local.equals(old.optString("id"))){if(!id.equals(old.optString("task_id"))||!instruction.trim().equals(old.optString("instruction"))||!(old.optJSONArray("attachments")==null?"[]":old.optJSONArray("attachments").toString()).equals(attachments.toString()))throw new IllegalArgumentException("Follow-up ID already has different contents");return local;}}
        pending.put(new JSONObject().put("id",local).put("task_id",id).put("instruction",instruction.trim()).put("attachments",attachments).put("origin",Cloud.prefs(c).getString("origin","")).put("created",System.currentTimeMillis()/1000.0).put("state","saved"));
        if(!Cloud.prefs(c).edit().putString("task_followups",pending.toString()).remove("attachment_draft:task:"+id).commit())throw new Exception("Phone storage failed");
        TaskSyncJob.schedule(c,false);changed(c);return local;
    }
    static void flush(Context c)throws Exception{synchronized(network){
        flushNew(c);
        while(true){JSONObject turn=null;synchronized(NativeTasks.class){JSONArray rows=pending(c);boolean changed=false;for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);if("needs_review".equals(row.optString("state")))continue;if(!row.optString("origin",Cloud.prefs(c).getString("origin","")).equals(Cloud.prefs(c).getString("origin",""))){row.put("state","needs_review").put("error","This follow-up belongs to a different server");changed=true;continue;}turn=row;break;}if(changed){if(!Cloud.prefs(c).edit().putString("task_followups",rows.toString()).commit())throw new Exception("Phone storage failed");changed(c);}}if(turn==null)break;
            String identifier=turn.getString("id"),root=turn.getString("task_id");
            try{JSONArray attachments=turn.optJSONArray("attachments");if(attachments==null)attachments=new JSONArray();TaskAttachments.upload(c,attachments);
                JSONObject body=new JSONObject().put("id",identifier).put("instruction",turn.getString("instruction"));if(attachments.length()>0)body.put("attachments",attachments);
                JSONObject receipt=(JSONObject)Cloud.call(c,"tasks/agent/"+encode(root)+"/followups",body,true);
                synchronized(NativeTasks.class){JSONArray fresh=pending(c),next=new JSONArray();for(int i=0;i<fresh.length();i++)if(!identifier.equals(fresh.getJSONObject(i).optString("id")))next.put(fresh.getJSONObject(i));
                    if(!Cloud.prefs(c).edit().putString("task_followups",next.toString()).putString("task_last_receipt",receipt.toString()).commit())throw new Exception("Phone storage failed");}
                changed(c);
            }catch(Exception error){synchronized(NativeTasks.class){JSONArray fresh=pending(c);for(int i=0;i<fresh.length();i++)if(identifier.equals(fresh.getJSONObject(i).optString("id"))){JSONObject saved=fresh.getJSONObject(i);saved.put("error",error.getMessage());String message=String.valueOf(error.getMessage());if(message.contains("(404)")||message.contains("(409)")||message.contains("(422)"))saved.put("state","needs_review");}Cloud.prefs(c).edit().putString("task_followups",fresh.toString()).commit();}changed(c);throw error;}
        }
    }}
    static void sync(Context c)throws Exception{PushRegistration.sync(c);flush(c);NotificationActions.flush(c);NativeNotifications.sync(c);history(c,"");changed(c);}
}
