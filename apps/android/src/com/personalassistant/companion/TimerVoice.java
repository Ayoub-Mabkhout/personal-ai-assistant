package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.net.Uri;
import android.provider.AlarmClock;
import android.os.SystemClock;
import org.json.JSONObject;

/** Durable native countdowns. Clock delegation remains distinct from registration. */
final class TimerVoice {
    static final String CHANNEL="voice_timers", COUNTDOWN="timer_countdowns";
    static String key(String id){if(!id.matches("[A-Za-z0-9_-]{8,80}"))throw new IllegalArgumentException("Invalid timer ID");return "timer_"+id;}
    static Intent clockIntent(int seconds){return new Intent(AlarmClock.ACTION_SET_TIMER).putExtra(AlarmClock.EXTRA_LENGTH,seconds).putExtra(AlarmClock.EXTRA_MESSAGE,"Assistant timer · "+TimerCommand.duration(seconds)).putExtra(AlarmClock.EXTRA_SKIP_UI,false);}
    static JSONObject apply(Context c,JSONObject response)throws Exception{
        if(!"timer".equals(response.optString("local_command"))||!"local_command".equals(response.optString("status")))return response;
        String id=response.optString("task_id",response.optString("id"));String saved=Cloud.prefs(c).getString(key(id),"");if(!saved.isEmpty()){JSONObject receipt=new JSONObject(saved);if("timer_active".equals(receipt.optString("status")))schedule(c,id,receipt);return receipt;}
        long age;try{age=System.currentTimeMillis()-java.time.Instant.parse(response.getString("created_at")).toEpochMilli();}catch(Exception error){age=Long.MAX_VALUE;}
        if(age>120000||age< -60000)return persist(Cloud.prefs(c),key(id),new JSONObject(response.toString()).put("status","timer_expired").put("reply","That timer command is too old. The timer has not started; please repeat it."));
        JSONObject result=prepare(c,id,response.optString("text"));return result==null?persist(Cloud.prefs(c),key(id),new JSONObject(response.toString()).put("status","timer_invalid").put("reply","I could not read that timer duration. The timer has not started; please repeat it.")):result;
    }
    static synchronized JSONObject prepare(Context c,String id,String text)throws Exception{
        Integer seconds=TimerCommand.seconds(text);if(seconds==null)return null;
        String key=key(id);SharedPreferences p=Cloud.prefs(c);String saved=p.getString(key,"");if(!saved.isEmpty())return new JSONObject(saved);
        JSONObject receipt=new JSONObject().put("id",id).put("text",text).put("local_command","timer");
        if(seconds==0)return persist(p,key,receipt.put("status","timer_invalid").put("reply","Please give a timer duration between one second and 24 hours, for example five minutes or one hour and thirty minutes."));
        receipt.put("timer_seconds",seconds);
        NotificationManager manager=c.getSystemService(NotificationManager.class);
        manager.createNotificationChannelGroup(new NotificationChannelGroup(NotificationStyle.GROUP,"Assistant"));
        NotificationStyle.channel(manager,COUNTDOWN,"Timer countdowns",NotificationManager.IMPORTANCE_LOW,"Active native timer countdowns and cancellation");
        NotificationChannel timerChannel=new NotificationChannel(CHANNEL,"Voice timers",NotificationManager.IMPORTANCE_HIGH);timerChannel.setGroup(NotificationStyle.GROUP);timerChannel.setDescription("Native timer completion alerts");timerChannel.setSound(android.provider.Settings.System.DEFAULT_ALARM_ALERT_URI,new android.media.AudioAttributes.Builder().setUsage(android.media.AudioAttributes.USAGE_ALARM).build());timerChannel.enableVibration(true);manager.createNotificationChannel(timerChannel);
        boolean allowed=manager.areNotificationsEnabled()&&manager.getNotificationChannel(CHANNEL).getImportance()!=NotificationManager.IMPORTANCE_NONE;
        if(!allowed)return persist(p,key,receipt.put("status","timer_blocked").put("reply","Timer has not started. Allow Companion's Voice timers notifications, then repeat the timer command."));
        receipt.put("status","timer_active").put("deadline",System.currentTimeMillis()+seconds*1000L).put("elapsed_deadline",SystemClock.elapsedRealtime()+seconds*1000L).put("boot",boot(c));
        String reply="Timer set for "+TimerCommand.duration(seconds)+" on this phone."+(precise(c)?"":" The alert may be delayed while the phone is asleep; tap its notification to allow precise timers.");
        receipt.put("reply",reply);persist(p,key,receipt);
        try{schedule(c,id,receipt);}catch(RuntimeException error){return persist(p,key,receipt.put("status","timer_failed").put("reply","Timer could not start on this phone. Open Clock to set it manually."));}
        show(c,id,seconds,manager);
        return receipt;
    }
    static JSONObject persist(SharedPreferences p,String key,JSONObject receipt)throws Exception{if(!p.edit().putString(key,receipt.toString()).commit())throw new Exception("Timer could not be saved on this phone");return receipt;}
    static void show(Context c,String id,int seconds,NotificationManager manager){
        Intent open=new Intent(c,TimerActivity.class).setData(Uri.parse("personalassistant://timer/"+id)).putExtra("timer_id",id);
        PendingIntent tap=PendingIntent.getActivity(c,id.hashCode(),open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        JSONObject saved;try{saved=new JSONObject(Cloud.prefs(c).getString(key(id),"{}"));}catch(Exception error){return;}
        Intent cancel=new Intent(c,TimerReceiver.class).setAction("timer_cancel").setData(Uri.parse("personalassistant://timer/"+id)).putExtra("timer_id",id);
        PendingIntent cancelTap=PendingIntent.getBroadcast(c,id.hashCode(),cancel,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        Notification notification=new Notification.Builder(c,COUNTDOWN).setSmallIcon(R.drawable.ic_stat_assistant).setLargeIcon(NotificationStyle.icon(c,"clock",NotificationStyle.PROGRESS)).setColor(NativeNotifications.ACCENT).setContentTitle(TimerCommand.duration(seconds)+" timer").setContentText(precise(c)?"Counting down on this phone":"Alert may be delayed during sleep · tap to allow precise timers").setWhen(saved.optLong("deadline")).setUsesChronometer(true).setChronometerCountDown(true).setContentIntent(tap).addAction(new Notification.Action.Builder(null,"Cancel",cancelTap).build()).setVisibility(Notification.VISIBILITY_PRIVATE).setOnlyAlertOnce(true).build();
        manager.notify("timer:"+id,1,notification);
    }
    /** Called only by a foreground Activity from an explicit notification tap. */
    static synchronized String launch(Activity activity,String id)throws Exception{
        String key=key(id);SharedPreferences p=Cloud.prefs(activity);JSONObject receipt=new JSONObject(p.getString(key,"{}"));
        if(!"timer_active".equals(receipt.optString("status"))||receipt.optBoolean("handoff_attempted"))return "This timer request is no longer available for handoff. Check Clock before starting another timer.";
        if(activity.getSystemService(KeyguardManager.class).isDeviceLocked())return "Unlock the phone to use Clock instead. Your Companion timer is still running.";
        int seconds=(int)Math.min(86400,Math.max(1,(remaining(activity,receipt)+999)/1000));Intent intent=clockIntent(seconds);
        if(intent.resolveActivity(activity.getPackageManager())==null)return "No Clock app accepts timers on this phone. Open your Clock app and set "+TimerCommand.duration(seconds)+" manually.";
        // Save BEFORE launch: a process death/second tap cannot silently create another timer.
        receipt.put("handoff_attempted",true).put("reply","Timer handoff pending. Check Clock before starting another timer.");persist(p,key,receipt);
        try{activity.startActivity(intent);}
        catch(ActivityNotFoundException|SecurityException error){receipt.put("handoff_attempted",false).put("reply","Clock could not open. Your Companion timer is still running.");persist(p,key,receipt);return receipt.getString("reply");}
        receipt.put("status","timer_delegated").put("reply","Sent a "+TimerCommand.duration(seconds)+" timer request to Clock. Check Clock to confirm it started.");persist(p,key,receipt);
        activity.getSystemService(NotificationManager.class).cancel("timer:"+id,1);
        activity.getSystemService(AlarmManager.class).cancel(alarm(activity,id));
        return receipt.getString("reply");
    }
    static int boot(Context c){return android.provider.Settings.Global.getInt(c.getContentResolver(),android.provider.Settings.Global.BOOT_COUNT,-1);}
    static PendingIntent alarm(Context c,String id){return PendingIntent.getBroadcast(c,id.hashCode(),new Intent(c,TimerReceiver.class).setAction("timer_due").setData(Uri.parse("personalassistant://timer/"+id)).putExtra("timer_id",id),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);}
    static long remaining(Context c,JSONObject value){return value.optInt("boot",-2)==boot(c)?value.optLong("elapsed_deadline")-SystemClock.elapsedRealtime():value.optLong("deadline")-System.currentTimeMillis();}
    static boolean precise(Context c){return android.os.Build.VERSION.SDK_INT<31||c.getSystemService(AlarmManager.class).canScheduleExactAlarms();}
    static void schedule(Context c,String id,JSONObject value){AlarmManager manager=c.getSystemService(AlarmManager.class);long deadline=SystemClock.elapsedRealtime()+Math.max(0,remaining(c,value));if(precise(c))manager.setExactAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP,deadline,alarm(c,id));else manager.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP,deadline,alarm(c,id));}
    static synchronized void recover(Context c){for(java.util.Map.Entry<String,?> entry:Cloud.prefs(c).getAll().entrySet())if(entry.getKey().startsWith("timer_"))try{JSONObject value=new JSONObject(String.valueOf(entry.getValue()));String id=value.optString("id");if("timer_active".equals(value.optString("status"))){if(remaining(c,value)<=0)due(c,id,false);else{schedule(c,id,value);show(c,id,value.getInt("timer_seconds"),c.getSystemService(NotificationManager.class));}}else if("timer_finished".equals(value.optString("status"))&&!value.optBoolean("completion_notified"))finished(c,id,value);}catch(Exception ignored){}}
    static synchronized void due(Context c,String id,boolean cancel)throws Exception{
        SharedPreferences p=Cloud.prefs(c);String key=key(id);JSONObject value=new JSONObject(p.getString(key,"{}"));
        if(!"timer_active".equals(value.optString("status")))return;
        if(!cancel&&remaining(c,value)>0){schedule(c,id,value);return;}
        value.put("status",cancel?"timer_cancelled":"timer_finished").put("reply",cancel?"Timer cancelled.":"Timer finished.");persist(p,key,value);c.getSystemService(AlarmManager.class).cancel(alarm(c,id));
        NotificationManager manager=c.getSystemService(NotificationManager.class);manager.cancel("timer:"+id,1);
        if(!cancel)finished(c,id,value);
    }
    static void finished(Context c,String id,JSONObject value)throws Exception{Notification notification=new Notification.Builder(c,CHANNEL).setSmallIcon(R.drawable.ic_stat_assistant).setLargeIcon(NotificationStyle.icon(c,"clock",NotificationStyle.DONE)).setColor(NativeNotifications.ACCENT).setContentTitle("Timer finished").setContentText(TimerCommand.duration(value.getInt("timer_seconds"))+" timer finished").setVisibility(Notification.VISIBILITY_PRIVATE).setAutoCancel(true).build();c.getSystemService(NotificationManager.class).notify("timer:"+id,1,notification);persist(Cloud.prefs(c),key(id),value.put("completion_notified",true));}
}
