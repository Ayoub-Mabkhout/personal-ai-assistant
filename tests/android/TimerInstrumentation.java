package com.personalassistant.companion;
import android.app.*;
import android.content.*;
import android.os.*;
import android.provider.AlarmClock;
import org.json.*;

/** Disposable, unpaired emulator only; actual AlarmManager, receiver and notification. */
public final class TimerInstrumentation extends Instrumentation {
    private Bundle arguments;
    @Override public void onCreate(Bundle args){super.onCreate(args);arguments=args;start();}
    void require(boolean condition,String message)throws Exception{if(!condition)throw new Exception(message);}
    JSONObject saved(Context c,String id)throws Exception{return new JSONObject(Cloud.prefs(c).getString(TimerVoice.key(id),"{}"));}
    void waitFinished(Context c,String id)throws Exception{long until=SystemClock.elapsedRealtime()+15000;while(SystemClock.elapsedRealtime()<until){if("timer_finished".equals(saved(c,id).optString("status"))&&saved(c,id).optBoolean("completion_notified"))return;SystemClock.sleep(100);}throw new Exception("Timer completion not observed: "+saved(c,id));}
    @Override public void onStart(){Context c=getTargetContext();Bundle report=new Bundle();
        try{
            require(Cloud.prefs(c).getString("token","").isEmpty(),"Do not run on a paired phone");
            if("blocked".equals(arguments.getString("mode"))){JSONObject blocked=TimerVoice.prepare(c,"timer-blocked-01","set a timer for five minutes");require("timer_blocked".equals(blocked.getString("status")),"Blocked notifications must not start a timer");report.putString("proof","blocked notifications prevented timer start");finish(-1,report);return;}
            boolean locked=c.getSystemService(KeyguardManager.class).isDeviceLocked();VoiceService.wakeCue(c);SystemClock.sleep(300);require(c.getSystemService(PowerManager.class).isInteractive(),"Screen wake cue did not wake display");if(locked)require(c.getSystemService(KeyguardManager.class).isDeviceLocked(),"Wake cue unlocked device");report.putBoolean("locked_cue",locked);
            require(TimerVoice.precise(c),"Grant Alarms and reminders to test real short deadlines");
            JSONObject first=TimerVoice.prepare(c,"timer-native-001","Hey Chat set a timer for two seconds");require("timer_active".equals(first.getString("status")),"Timer not active");long deadline=first.getLong("elapsed_deadline");
            require(TimerVoice.prepare(c,"timer-native-001","Hey Chat set a timer for two seconds").getLong("elapsed_deadline")==deadline,"Duplicate reset deadline");
            waitFinished(c,"timer-native-001");require(saved(c,"timer-native-001").getBoolean("completion_notified"),"Completion notification missing");
            boolean shown=false;for(android.service.notification.StatusBarNotification n:c.getSystemService(NotificationManager.class).getActiveNotifications())if(n.getTag().equals("timer:timer-native-001"))shown="Timer finished".equals(n.getNotification().extras.getString(Notification.EXTRA_TITLE));require(shown,"Real completion card not posted");
            TimerVoice.prepare(c,"timer-cancel-001","set a timer for thirty seconds");TimerVoice.due(c,"timer-cancel-001",true);require("timer_cancelled".equals(saved(c,"timer-cancel-001").getString("status")),"Cancellation not durable");TimerVoice.due(c,"timer-cancel-001",false);require("timer_cancelled".equals(saved(c,"timer-cancel-001").getString("status")),"Late alarm revived cancelled timer");
            JSONObject recovering=TimerVoice.prepare(c,"timer-recover-01","set a timer for thirty seconds");recovering.put("boot",-42).put("deadline",System.currentTimeMillis()+2000);TimerVoice.persist(Cloud.prefs(c),TimerVoice.key("timer-recover-01"),recovering);TimerVoice.recover(c);waitFinished(c,"timer-recover-01");
            JSONObject stale=new JSONObject().put("task_id","timer-expired-01").put("status","local_command").put("local_command","timer").put("text","set a timer for five minutes").put("created_at",java.time.Instant.now().minusSeconds(300).toString());require("timer_expired".equals(TimerVoice.apply(c,stale).getString("status")),"Stale reconnect started a timer");
            Intent intent=TimerVoice.clockIntent(5400);require(AlarmClock.ACTION_SET_TIMER.equals(intent.getAction())&&intent.getIntExtra(AlarmClock.EXTRA_LENGTH,0)==5400&&!intent.getBooleanExtra(AlarmClock.EXTRA_SKIP_UI,true),"Clock extras incorrect");require(intent.getStringExtra(AlarmClock.EXTRA_MESSAGE).contains("1 hour 30 minutes"),"Clock label incorrect");
            if("clock".equals(arguments.getString("mode"))){TimerVoice.prepare(c,"timer-clock-001","set a timer for ninety seconds");Activity activity=startActivitySync(new Intent(c,TimerActivity.class).putExtra("timer_id","timer-clock-001").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));final String[] result={""};runOnMainSync(()->{try{result[0]=TimerVoice.launch(activity,"timer-clock-001");}catch(Exception e){result[0]=e.toString();}});require("timer_delegated".equals(saved(c,"timer-clock-001").getString("status")),"Clock delegation failed: "+result[0]);String repeat=TimerVoice.launch(activity,"timer-clock-001");require(repeat.contains("no longer available"),"Duplicate Clock handoff not prevented");report.putString("clock",result[0]);}
            report.putString("proof","actual exact deadline, completion card, cancel, duplicate deadline, simulated reboot recovery, stale replay rejection and Clock intent contract passed");finish(-1,report);
        }catch(Exception error){report.putString("error",error.toString());finish(0,report);}
    }
}
