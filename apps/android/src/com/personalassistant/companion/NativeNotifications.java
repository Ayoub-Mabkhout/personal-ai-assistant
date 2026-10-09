package com.personalassistant.companion;
import android.app.*;
import android.content.*;
import android.graphics.Typeface;
import android.os.Build;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.style.StyleSpan;
import java.util.HashSet;
import java.util.Set;
import org.json.*;

/** In-app task notification targets; no browser or Home Assistant dependency. */
final class NativeNotifications {
    /** Mid-violet that keeps contrast on both the light and the dark notification shade. */
    static final int ACCENT=0xFF7B58E8;
    static synchronized void sync(Context c)throws Exception{
        long cursor=Cloud.prefs(c).getLong("push_cursor",0);
        JSONObject response=(JSONObject)Cloud.call(c,"events?cursor="+cursor,null,true);JSONArray events=response.optJSONArray("items");if(events==null)return;
        long next=cursor;boolean more=response.optBoolean("more",false),held=false;
        Set<String> shown=Cloud.prefs(c).getStringSet("push_shown",new HashSet<String>()),kept=new HashSet<String>();
        for(int i=0;i<events.length();i++){
            JSONObject event=events.getJSONObject(i);long sequence=event.getLong("sequence");String id=event.getString("id");JSONObject body=event.getJSONObject("payload");body.put("created",event.optDouble("created",System.currentTimeMillis()/1000.0));
            if(event.optDouble("expires",Double.MAX_VALUE)>System.currentTimeMillis()/1000.0){
                boolean release="release".equals(body.optString("type"));
                // A blocked card stays unreceived so the server reports it and it shows once unblocked. A full page is never held:
                // the server would keep serving the same 100 events and nothing behind them, reminders included, would arrive.
                if(!release&&!more&&blocked(c,body))held=true;
                else{
                    if(!shown.contains(id)){if(release){Cloud.prefs(c).edit().putBoolean("update_pending",true).commit();SyncJob.scheduleUpdate(c);}else show(c,id,body);}
                    if(held)kept.add(id);
                }
            }
            if(!held)next=Math.max(next,sequence);
        }
        Cloud.prefs(c).edit().putStringSet("push_shown",kept).commit();
        if(next>cursor){
            // Receipt is idempotent. If network fails, the same tagged card is replaced on retry.
            Cloud.call(c,"events/receipt",new JSONObject().put("cursor",next),true);
            if(!Cloud.prefs(c).edit().putLong("push_cursor",next).commit())throw new Exception("Phone storage failed");
        }
        if(events.length()>0)NativeTasks.changed(c);
        Cloud.prefs(c).edit().putBoolean("push_more",more).commit();
    }
    static String channel(String type){return type.equals("reminder")?"calendar_reminders":type.equals("alarm")?"phone_actions":"task_updates";}
    static boolean blocked(Context c,JSONObject body){
        NotificationManager manager=(NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE);
        if(!manager.areNotificationsEnabled())return true;
        NotificationChannel channel=manager.getNotificationChannel(channel(body.optString("type","task")));
        return channel!=null&&channel.getImportance()==NotificationManager.IMPORTANCE_NONE;
    }
    static void channels(NotificationManager manager){
        NotificationStyle.channel(manager,"task_updates","Task updates",NotificationManager.IMPORTANCE_HIGH,"Progress, results and questions from tasks running on your laptop");
        NotificationStyle.channel(manager,"calendar_reminders","Calendar reminders",NotificationManager.IMPORTANCE_HIGH,"Upcoming events from your assistant's calendar");
        NotificationStyle.channel(manager,"phone_actions","Phone actions",NotificationManager.IMPORTANCE_HIGH,"Alarms and other requests your assistant sends to this phone");
    }
    /** Glyph and medallion tone for a task state. */
    static Object[] look(String state){
        switch(state){
            case "queued":return new Object[]{"clock",NotificationStyle.PROGRESS};
            case "running":return new Object[]{"activity",NotificationStyle.PROGRESS};
            case "completed":return new Object[]{"check",NotificationStyle.DONE};
            case "needs_input":return new Object[]{"chat",NotificationStyle.ATTENTION};
            case "failed":return new Object[]{"alert",NotificationStyle.FAILED};
            case "cancelled":return new Object[]{"stop",NotificationStyle.BRAND};
            case "expired":return new Object[]{"history",NotificationStyle.BRAND};
            default:return new Object[]{"sparkle",NotificationStyle.BRAND};
        }
    }
    static void show(Context c,String identifier,JSONObject body)throws Exception{
        String type=body.optString("type","task"),channel=channel(type);
        NotificationManager manager=(NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE);
        channels(manager);
        String kind=body.optString("task_kind","agent"),task=body.optString("task_id");
        Intent open=new Intent(c,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP).putExtra("task_kind",kind).putExtra("task_id",task).putExtra("push_event_id",identifier);
        if(type.equals("alarm"))open.setAction(Intent.ACTION_VIEW).setData(android.net.Uri.parse("personalassistant://sync"));
        PendingIntent pending=PendingIntent.getActivity(c,identifier.hashCode(),open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        boolean active=body.optBoolean("active",false);
        String title=body.optString("title","Assistant"),message=body.optString("message"),label,glyph;CharSequence headline=title,text=message,expanded=message;int[] tone;
        if(type.equals("task")){
            // Producers append the short task reference to the title and put the request before the status. The bold request identifies the task, so the reference is dropped.
            int mark=title.lastIndexOf(" · ");if(mark>0)headline=title.substring(0,mark);
            int split=message.indexOf("\n\n");String request=split<0?"":message.substring(0,split).trim(),status=split<0?message.trim():message.substring(split+2).trim();
            text=status.isEmpty()?request:status;
            if(!request.isEmpty()&&!status.isEmpty()){SpannableStringBuilder rich=new SpannableStringBuilder(request);rich.setSpan(new StyleSpan(Typeface.BOLD),0,rich.length(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);expanded=rich.append("\n").append(status);}
            label=kind.equals("command")?"Command":"Laptop task";
            Object[] look=look(body.optString("state"));glyph=(String)look[0];tone=(int[])look[1];
        }else if(type.equals("reminder")){
            // Reminder messages are the event title, then its time and optional location.
            String[] lines=message.split("\n");
            if(lines.length>1&&!lines[0].trim().isEmpty()){headline=lines[0].trim();StringBuilder rest=new StringBuilder();for(int i=1;i<lines.length;i++)if(!lines[i].trim().isEmpty())rest.append(rest.length()==0?"":" · ").append(lines[i].trim());text=expanded=rest.toString();}
            label="Calendar";glyph="bell";tone=NotificationStyle.ATTENTION;
        }else{label="Phone action";glyph="clock";tone=NotificationStyle.BRAND;}
        boolean hidden=!body.optString("visibility").equals("public");
        Notification.Builder notification=new Notification.Builder(c,channel).setSmallIcon(R.drawable.ic_stat_assistant).setColor(ACCENT).setContentTitle(headline)
            .setContentText(text).setStyle(new Notification.BigTextStyle().bigText(expanded)).setSubText(label).setLargeIcon(NotificationStyle.icon(c,glyph,tone))
            .setContentIntent(pending).setAutoCancel(!active).setOngoing(active).setOnlyAlertOnce(active).setVisibility(hidden?Notification.VISIBILITY_PRIVATE:Notification.VISIBILITY_PUBLIC)
            .setGroup(type.equals("task")?"assistant_tasks":"assistant_events").setWhen((long)(body.optDouble("created",System.currentTimeMillis()/1000.0)*1000)).setShowWhen(true);
        if(type.equals("reminder"))notification.setCategory(Notification.CATEGORY_EVENT);else if(active)notification.setCategory(Notification.CATEGORY_PROGRESS);
        // The lock screen shows only the kind of update, never the request, result or event.
        if(hidden)notification.setPublicVersion(new Notification.Builder(c,channel).setSmallIcon(R.drawable.ic_stat_assistant).setColor(ACCENT).setContentTitle(type.equals("task")?(headline.toString().startsWith("Task")?headline:"Task update"):type.equals("reminder")?"Calendar reminder":"Phone action").setSubText(type.equals("task")?"Laptop task":null).setShowWhen(true).setWhen((long)(body.optDouble("created",System.currentTimeMillis()/1000.0)*1000)).build());
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
