package com.personalassistant.companion;
import android.app.*;
import android.content.*;
import android.os.Build;
import org.json.*;

/** In-app task notification targets; no browser or Home Assistant dependency. */
final class NativeNotifications {
    static synchronized void sync(Context c)throws Exception{
        long cursor=Cloud.prefs(c).getLong("push_cursor",0);
        JSONObject response=(JSONObject)Cloud.call(c,"events?cursor="+cursor,null,true);JSONArray events=response.optJSONArray("items");if(events==null)return;
        long next=cursor;
        for(int i=0;i<events.length();i++){
            JSONObject event=events.getJSONObject(i);long sequence=event.getLong("sequence");JSONObject body=event.getJSONObject("payload");body.put("created",event.optDouble("created",System.currentTimeMillis()/1000.0));
            if(event.optDouble("expires",Double.MAX_VALUE)>System.currentTimeMillis()/1000.0){
                if("release".equals(body.optString("type"))){Cloud.prefs(c).edit().putBoolean("update_pending",true).commit();SyncJob.scheduleUpdate(c);}
                else show(c,event.getString("id"),body);
            }
            next=Math.max(next,sequence);
        }
        if(next>cursor){
            // Receipt is idempotent. If network fails, the same tagged card is replaced on retry.
            Cloud.call(c,"events/receipt",new JSONObject().put("cursor",next),true);
            if(!Cloud.prefs(c).edit().putLong("push_cursor",next).commit())throw new Exception("Phone storage failed");
        }
        if(events.length()>0)NativeTasks.changed(c);
        Cloud.prefs(c).edit().putBoolean("push_more",response.optBoolean("more",false)).commit();
    }
    static void show(Context c,String identifier,JSONObject body)throws Exception{
        String channel="task_updates",type=body.optString("type","task");if(type.equals("reminder"))channel="calendar_reminders";else if(type.equals("alarm"))channel="phone_actions";
        NotificationManager manager=(NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE);
        manager.createNotificationChannel(new NotificationChannel(channel,channel.equals("task_updates")?"Task updates":channel.equals("calendar_reminders")?"Calendar reminders":"Phone actions",NotificationManager.IMPORTANCE_HIGH));
        String kind=body.optString("task_kind","agent"),task=body.optString("task_id");
        Intent open=new Intent(c,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP).putExtra("task_kind",kind).putExtra("task_id",task).putExtra("push_event_id",identifier);
        if(type.equals("alarm"))open.setAction(Intent.ACTION_VIEW).setData(android.net.Uri.parse("personalassistant://sync"));
        PendingIntent pending=PendingIntent.getActivity(c,identifier.hashCode(),open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        boolean active=body.optBoolean("active",false);
        Notification.Builder notification=new Notification.Builder(c,channel).setSmallIcon(R.drawable.ic_stat_assistant).setContentTitle(body.optString("title","Assistant"))
            .setContentText(body.optString("message")).setStyle(new Notification.BigTextStyle().bigText(body.optString("message")))
            .setContentIntent(pending).setAutoCancel(!active).setOngoing(active).setOnlyAlertOnce(active).setVisibility(body.optString("visibility").equals("public")?Notification.VISIBILITY_PUBLIC:Notification.VISIBILITY_PRIVATE)
            .setGroup(type.equals("task")?"assistant_tasks":"assistant_events").setWhen((long)(body.optDouble("created",System.currentTimeMillis()/1000.0)*1000));
        if(body.optString("state").equals("running"))notification.setProgress(0,0,true);
        if(!task.isEmpty()){
            notification.addAction(new Notification.Action.Builder(null,"Details",pending).build());
            if(kind.equals("agent")){
                Intent reply=new Intent(c,NotificationActions.class).setAction("reply").putExtra("event_id",identifier).putExtra("task_id",task).putExtra("tag",body.optString("tag",identifier));
                PendingIntent action=PendingIntent.getBroadcast(c,(identifier+"reply").hashCode(),reply,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_MUTABLE);
                notification.addAction(new Notification.Action.Builder(null,"Reply",action).addRemoteInput(new RemoteInput.Builder("instruction").setLabel("Follow up on this task").build()).setAllowGeneratedReplies(false).build());
            }
        }
        if(type.equals("reminder")){
            Intent snooze=new Intent(c,NotificationActions.class).setAction("snooze").putExtra("event_id",identifier).putExtra("tag",body.optString("tag",identifier));
            PendingIntent action=PendingIntent.getBroadcast(c,(identifier+"snooze").hashCode(),snooze,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
            notification.addAction(new Notification.Action.Builder(null,"Snooze 10 min",action).build());
        }
        try{manager.notify(body.optString("tag",identifier),220,notification.build());}
        catch(SecurityException unavailable){Cloud.prefs(c).edit().putString("push_status","Allow notifications in Settings to receive task updates").commit();}
    }
}
