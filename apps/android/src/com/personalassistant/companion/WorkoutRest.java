package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.os.Build;

/** Rest-over alert when the app is in the background. On-phone only, so it works with no signal. */
public final class WorkoutRest extends BroadcastReceiver {
    private static PendingIntent pending(Context c){return PendingIntent.getBroadcast(c,7301,new Intent(c,WorkoutRest.class),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);}
    static void schedule(Context c,long at){AlarmManager alarms=(AlarmManager)c.getSystemService(Context.ALARM_SERVICE);if(alarms==null)return;if(Build.VERSION.SDK_INT<31||alarms.canScheduleExactAlarms())alarms.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,at,pending(c));else alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,at,pending(c));}
    static void cancel(Context c){AlarmManager alarms=(AlarmManager)c.getSystemService(Context.ALARM_SERVICE);if(alarms!=null)alarms.cancel(pending(c));NotificationManager m=(NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE);if(m!=null)m.cancel(7301);}
    @Override public void onReceive(Context c,Intent intent){NotificationManager m=(NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE);if(m==null)return;NotificationStyle.channel(m,"workout_rest","Workout rest timer",NotificationManager.IMPORTANCE_HIGH,"Tells you when your rest between sets is over");
        Intent open=new Intent(c,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP).putExtra("open_tab","train");
        m.notify(7301,new Notification.Builder(c,"workout_rest").setSmallIcon(R.drawable.ic_stat_assistant).setContentTitle("Rest over").setContentText("Time for your next set.").setCategory(Notification.CATEGORY_ALARM).setAutoCancel(true).setTimeoutAfter(120000).setContentIntent(PendingIntent.getActivity(c,7302,open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE)).build());}
}
