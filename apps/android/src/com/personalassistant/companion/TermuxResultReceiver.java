package com.personalassistant.companion;
import android.content.*;
/** Non-exported receiver, invoked only using the one-shot PendingIntent given to Termux. */
public class TermuxResultReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context c,Intent i){try{TermuxBridge.received(c,i);}catch(Exception e){Cloud.prefs(c).edit().putString("termux_status","Could not save Termux result: "+e.getMessage()).commit();}}
}
