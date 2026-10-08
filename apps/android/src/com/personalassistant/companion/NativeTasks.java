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
    static String enqueueFollowup(Context c,String id,String instruction)throws Exception{return enqueueFollowupWithId(c,id,instruction,UUID.randomUUID().toString());}
    static synchronized String enqueueFollowupWithId(Context c,String id,String instruction,String local)throws Exception{
        if(instruction==null||instruction.trim().isEmpty()||instruction.length()>4096)throw new IllegalArgumentException("Enter an instruction up to 4096 characters");
        JSONArray pending=pending(c);for(int i=0;i<pending.length();i++){JSONObject old=pending.getJSONObject(i);if(local.equals(old.optString("id"))){if(!id.equals(old.optString("task_id"))||!instruction.trim().equals(old.optString("instruction")))throw new IllegalArgumentException("Follow-up ID already has different contents");return local;}}
        pending.put(new JSONObject().put("id",local).put("task_id",id).put("instruction",instruction.trim()).put("origin",Cloud.prefs(c).getString("origin","")).put("created",System.currentTimeMillis()/1000.0).put("state","saved"));
        if(!Cloud.prefs(c).edit().putString("task_followups",pending.toString()).commit())throw new Exception("Phone storage failed");
        TaskSyncJob.schedule(c,false);changed(c);return local;
    }
    static void flush(Context c)throws Exception{synchronized(network){
        while(true){JSONObject turn=null;synchronized(NativeTasks.class){JSONArray rows=pending(c);boolean changed=false;for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);if("needs_review".equals(row.optString("state")))continue;if(!row.optString("origin",Cloud.prefs(c).getString("origin","")).equals(Cloud.prefs(c).getString("origin",""))){row.put("state","needs_review").put("error","This follow-up belongs to a different server");changed=true;continue;}turn=row;break;}if(changed){if(!Cloud.prefs(c).edit().putString("task_followups",rows.toString()).commit())throw new Exception("Phone storage failed");changed(c);}}if(turn==null)break;
            String identifier=turn.getString("id"),root=turn.getString("task_id");
            try{JSONObject receipt=(JSONObject)Cloud.call(c,"tasks/agent/"+encode(root)+"/followups",new JSONObject().put("id",identifier).put("instruction",turn.getString("instruction")),true);
                synchronized(NativeTasks.class){JSONArray fresh=pending(c),next=new JSONArray();for(int i=0;i<fresh.length();i++)if(!identifier.equals(fresh.getJSONObject(i).optString("id")))next.put(fresh.getJSONObject(i));
                    if(!Cloud.prefs(c).edit().putString("task_followups",next.toString()).putString("task_last_receipt",receipt.toString()).commit())throw new Exception("Phone storage failed");}
                changed(c);
            }catch(Exception error){synchronized(NativeTasks.class){JSONArray fresh=pending(c);for(int i=0;i<fresh.length();i++)if(identifier.equals(fresh.getJSONObject(i).optString("id"))){JSONObject saved=fresh.getJSONObject(i);saved.put("error",error.getMessage());String message=String.valueOf(error.getMessage());if(message.contains("(404)")||message.contains("(409)")||message.contains("(422)"))saved.put("state","needs_review");}Cloud.prefs(c).edit().putString("task_followups",fresh.toString()).commit();}changed(c);throw error;}
        }
    }}
    static void sync(Context c)throws Exception{PushRegistration.sync(c);flush(c);NotificationActions.flush(c);NativeNotifications.sync(c);history(c,"");changed(c);}
}
