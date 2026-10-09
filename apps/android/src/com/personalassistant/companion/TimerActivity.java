package com.personalassistant.companion;

import android.app.Activity;
import android.os.Bundle;
import android.widget.LinearLayout;
import android.content.Intent;
import android.net.Uri;
import org.json.JSONObject;

/** User-initiated foreground Clock handoff; never tries to bypass a locked screen. */
public final class TimerActivity extends Activity {
    @Override public void onCreate(Bundle saved){
        AppUi.theme(this);super.onCreate(saved);AppUi ui=new AppUi(this);ui.window();LinearLayout box=ui.column();box.setPadding(ui.dp(24),ui.dp(32),ui.dp(24),ui.dp(24));box.addView(ui.display("Timer"));
        String id=getIntent().getStringExtra("timer_id"),message;
        try{JSONObject receipt=new JSONObject(Cloud.prefs(this).getString(TimerVoice.key(id),"{}"));long left=Math.max(0,(TimerVoice.remaining(this,receipt)+999)/1000);message=TimerCommand.duration(receipt.getInt("timer_seconds"))+" timer · "+("timer_active".equals(receipt.optString("status"))?TimerCommand.duration((int)left)+" remaining":receipt.optString("reply"));}catch(Exception error){message="Timer details unavailable.";}
        ui.space(box,16);box.addView(ui.detail(message));ui.space(box,24);
        box.addView(ui.ghostButton("Cancel timer",()->{try{TimerVoice.due(this,id,true);}catch(Exception ignored){}finish();}));
        box.addView(ui.ghostButton("Use Clock instead",()->{try{android.widget.Toast.makeText(this,TimerVoice.launch(this,id),android.widget.Toast.LENGTH_LONG).show();}catch(Exception error){android.widget.Toast.makeText(this,"Could not hand off. Check Clock before repeating.",android.widget.Toast.LENGTH_LONG).show();}}));
        if(!TimerVoice.precise(this)&&android.os.Build.VERSION.SDK_INT>=31){ui.space(box,16);box.addView(ui.detail("Android can delay this alert during sleep. Allow alarms and reminders for precise timers. Reopening this screen updates active timers."));box.addView(ui.ghostButton("Allow precise timers",()->{try{startActivity(new Intent(android.provider.Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,Uri.parse("package:"+getPackageName())));}catch(Exception error){android.widget.Toast.makeText(this,"Open Android Settings → Apps → Special access → Alarms and reminders.",android.widget.Toast.LENGTH_LONG).show();}}));}
        ui.space(box,24);box.addView(ui.ghostButton("Close",this::finish));setContentView(box);
    }
    @Override public void onResume(){super.onResume();TimerVoice.recover(this);}
}
