package com.personalassistant.companion;
import android.content.*;
import android.app.RemoteInput;
import android.os.Bundle;
import org.json.*;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

/** Explicit app-private notification reply/snooze targets. */
public class NotificationActions extends BroadcastReceiver {
    static synchronized JSONArray saved(Context c)throws Exception{return new JSONArray(Cloud.prefs(c).getString("notification_actions","[]"));}
    @Override public void onReceive(Context c,Intent intent){
        String event=intent.getStringExtra("event_id");if(event==null||!event.matches("[a-f0-9]{64}"))return;
        try{
            if("reply".equals(intent.getAction())){
                Bundle results=RemoteInput.getResultsFromIntent(intent);CharSequence text=results==null?null:results.getCharSequence("instruction");
                if(text==null||text.toString().trim().isEmpty())return;
                String task=intent.getStringExtra("task_id");if(task==null||!task.matches("[A-Za-z0-9_-]{8,64}"))return;
                String stable=UUID.nameUUIDFromBytes((event+":"+text.toString()).getBytes(StandardCharsets.UTF_8)).toString();
                NativeTasks.enqueueFollowupWithId(c,task,text.toString(),stable);
            }else if("snooze".equals(intent.getAction())){
                synchronized(NotificationActions.class){JSONArray actions=saved(c);String identifier=UUID.nameUUIDFromBytes((event+":snooze").getBytes(StandardCharsets.UTF_8)).toString();boolean exists=false;for(int i=0;i<actions.length();i++)if(identifier.equals(actions.getJSONObject(i).optString("id")))exists=true;
                    if(!exists){actions.put(new JSONObject().put("id",identifier).put("event_id",event).put("seconds",600));if(!Cloud.prefs(c).edit().putString("notification_actions",actions.toString()).commit())throw new Exception("Phone storage failed");}}
                TaskSyncJob.schedule(c,false);
            }else return;
            ((android.app.NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE)).cancel(intent.getStringExtra("tag"),220);
        }catch(Exception error){Cloud.prefs(c).edit().putString("task_sync_error",error.getMessage()).commit();NativeTasks.changed(c);}
    }
    static void flush(Context c)throws Exception{
        while(true){JSONObject action;synchronized(NotificationActions.class){JSONArray actions=saved(c);if(actions.length()==0)return;action=actions.getJSONObject(0);}
            try{Cloud.call(c,"events/"+action.getString("event_id")+"/snooze",new JSONObject().put("id",action.getString("id")).put("seconds",action.getInt("seconds")),true);}
            catch(Exception error){String message=String.valueOf(error.getMessage());if(!(message.contains("(404)")||message.contains("(409)")||message.contains("(422)")))throw error;Cloud.prefs(c).edit().putString("push_status","That reminder is no longer available to snooze").commit();}
            synchronized(NotificationActions.class){JSONArray fresh=saved(c),next=new JSONArray();for(int i=0;i<fresh.length();i++)if(!action.getString("id").equals(fresh.getJSONObject(i).optString("id")))next.put(fresh.getJSONObject(i));if(!Cloud.prefs(c).edit().putString("notification_actions",next.toString()).commit())throw new Exception("Phone storage failed");}
        }
    }
}
