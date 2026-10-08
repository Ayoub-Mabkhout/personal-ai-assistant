package com.personalassistant.wakeprobe;
import android.app.Activity;
import android.os.Bundle;
import android.widget.*;
import android.content.Intent;
import android.provider.Settings;
/** Optional user-driven device probe: select as assistant, inspect, restore previous assistant. */
public final class ProbeActivity extends Activity {
    @Override public void onCreate(Bundle args){super.onCreate(args);LinearLayout box=new LinearLayout(this);box.setOrientation(1);box.setPadding(24,24,24,24);TextView instructions=new TextView(this);instructions.setText("Read-only hardware probe. It never records or changes enrollment. Select this app as Digital assistant, then return to view the result. Restore your previous Digital assistant afterward.");box.addView(instructions);Button choose=new Button(this);choose.setText("Open Default Apps");choose.setOnClickListener(v->startActivity(new Intent(Settings.ACTION_MANAGE_DEFAULT_APPS_SETTINGS)));box.addView(choose);TextView result=new TextView(this);result.setText(getSharedPreferences("probe",0).getString("result","No result yet; the service runs when selected as assistant."));ScrollView scroll=new ScrollView(this);scroll.addView(result);box.addView(scroll);setContentView(box);}
}
