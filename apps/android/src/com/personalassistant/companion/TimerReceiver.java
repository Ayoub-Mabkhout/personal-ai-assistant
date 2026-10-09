package com.personalassistant.companion;
import android.content.*;
/** Rebuild alarms after reboot; no server, microphone or background Activity launch. */
public final class TimerReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context c,Intent intent){try{String id=intent.getStringExtra("timer_id");if(id==null)TimerVoice.recover(c);else TimerVoice.due(c,id,"timer_cancel".equals(intent.getAction()));}catch(Exception error){Cloud.prefs(c).edit().putString("timer_error","Timer recovery failed; check your timer.").apply();}}
}
