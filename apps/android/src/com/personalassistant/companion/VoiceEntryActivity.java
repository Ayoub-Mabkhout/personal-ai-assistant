package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.*;
import android.view.WindowManager;
import android.widget.*;

/** Lightweight voice entry above keyguard; never requests device unlock. */
public final class VoiceEntryActivity extends Activity {
    private AppUi ui;private AppUi.ThemeWatcher themeWatcher;private long themeBusyUntil;private ScrollView contentScroll;private ChatTimeline chat;private AppUi.Meter meter;private TextView status,caption,answer;private boolean registered,resumed,startPending=true;
    private final android.content.SharedPreferences.OnSharedPreferenceChangeListener preferences=(p,key)->{if("voice_level".equals(key)&&meter!=null)meter.value(AppUi.level(this),AppUi.micActive(this));else refresh();};
    private final BroadcastReceiver voiceState=new BroadcastReceiver(){@Override public void onReceive(Context c,Intent i){refresh();}};
    @Override public void onCreate(Bundle state){
        AppUi.theme(this);super.onCreate(state);startPending=state==null||state.getBoolean("startPending",false);if(state!=null)themeBusyUntil=SystemClock.elapsedRealtime()+Math.min(2000,Math.max(0,state.getLong("themeBusyRemaining",0)));ui=new AppUi(this);themeWatcher=new AppUi.ThemeWatcher(this,()->ui.dark,this::themeReady,this::recreate);ui.window();
        if(Build.VERSION.SDK_INT>=27){setShowWhenLocked(true);setTurnScreenOn(true);}
        else getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED|WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        LinearLayout box=ui.column();box.setPadding(ui.dp(24),ui.dp(26),ui.dp(24),ui.dp(24));box.setBackground(ui.backgroundDrawable());
        LinearLayout header=ui.row();header.addView(ui.text("Voice",29,true),new LinearLayout.LayoutParams(0,-2,1));header.addView(ui.badge(getSystemService(KeyguardManager.class).isDeviceLocked()?"Phone locked":"Voice"));box.addView(header);ui.space(box,18);
        LinearLayout hero=ui.column();hero.setGravity(android.view.Gravity.CENTER_HORIZONTAL);AppUi.VoiceButton talk=ui.voiceButton(this::startTalk);talk.setTag("locked_talk");hero.addView(talk,new LinearLayout.LayoutParams(ui.dp(202),ui.dp(202)));ui.space(hero,12);status=ui.text("Starting microphone...",15,true);status.setTextColor(ui.accent);status.setGravity(android.view.Gravity.CENTER);status.setTag("locked_voice_status");hero.addView(status);meter=new AppUi.Meter(this,ui.accent);hero.addView(meter,new LinearLayout.LayoutParams(ui.dp(150),ui.dp(30)));Button stop=ui.quietButton("Stop microphone",()->{Cloud.prefs(this).edit().putBoolean("wake_enabled",false).putBoolean("voice_listening_test",false).apply();stopService(new Intent(this,VoiceService.class));refresh();});hero.addView(stop);box.addView(hero);ui.space(box,20);
        ui.label(box,"CONVERSATION");chat=new ChatTimeline(ui);box.addView(chat.rows);
        Button close=ui.quietButton("Close",this::finish);box.addView(close);ui.space(box,7);TextView note=ui.detail("Close hides this screen. Stop microphone ends listening.");note.setGravity(android.view.Gravity.CENTER);box.addView(note);
        contentScroll=new ScrollView(this);contentScroll.setFitsSystemWindows(true);contentScroll.setBackgroundColor(ui.background);contentScroll.addView(box);setContentView(contentScroll);if(state!=null){final int offset=state.getInt("voiceScrollY",0);contentScroll.addOnLayoutChangeListener(new android.view.View.OnLayoutChangeListener(){@Override public void onLayoutChange(android.view.View v,int l,int t,int r,int b,int ol,int ot,int or,int ob){if(r>l&&b>t){v.scrollTo(0,offset);v.removeOnLayoutChangeListener(this);}}});}
        Cloud.prefs(this).edit().putLong("voice_entry_created_elapsed",SystemClock.elapsedRealtime()).putLong("voice_entry_created_ns",SystemClock.elapsedRealtimeNanos()).putBoolean("voice_entry_created_locked",getSystemService(KeyguardManager.class).isDeviceLocked()).commit();
        refresh();
    }
    @Override public void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);startPending=true;}
    @Override public void onStart(){super.onStart();IntentFilter filter=new IntentFilter("com.personalassistant.companion.VOICE_STATE");if(Build.VERSION.SDK_INT>=33)registerReceiver(voiceState,filter,Context.RECEIVER_NOT_EXPORTED);else registerReceiver(voiceState,filter);registered=true;Cloud.prefs(this).registerOnSharedPreferenceChangeListener(preferences);}
    @Override public void onSaveInstanceState(Bundle state){state.putBoolean("startPending",startPending);state.putLong("themeBusyRemaining",Math.max(0,themeBusyUntil-SystemClock.elapsedRealtime()));state.putInt("voiceScrollY",contentScroll.getScrollY());super.onSaveInstanceState(state);}
    @Override public void onResume(){super.onResume();resumed=true;if(ui!=null)ui.window();if(startPending){startPending=false;startTalk();}refresh();if(themeWatcher!=null)themeWatcher.resume();}
    @Override public void onPause(){resumed=false;if(themeWatcher!=null)themeWatcher.stop();super.onPause();}
    @Override public void onDestroy(){if(themeWatcher!=null)themeWatcher.stop();super.onDestroy();}
    @Override public void onWindowFocusChanged(boolean focus){super.onWindowFocusChanged(focus);if(focus&&ui!=null)ui.window();if(focus&&themeWatcher!=null)themeWatcher.check();}
    @Override public void onStop(){if(registered){unregisterReceiver(voiceState);registered=false;}Cloud.prefs(this).unregisterOnSharedPreferenceChangeListener(preferences);super.onStop();}
    private boolean themeReady(){android.content.SharedPreferences p=Cloud.prefs(this);return resumed&&hasWindowFocus()&&!startPending&&!p.getBoolean("voice_conversation_active",false)&&!p.getBoolean("voice_listening_test",false)&&SystemClock.elapsedRealtime()>=themeBusyUntil;}
    private void refresh(){android.content.SharedPreferences prefs=Cloud.prefs(this);if(status!=null)AppUi.update(status,prefs.getString("voice_status","Microphone off"));String words=prefs.getString("voice_user_text",prefs.getString("voice_transcript",""));if(caption!=null)AppUi.update(caption,words.isEmpty()?"Your words will appear here.":words);String reply=prefs.getString("voice_reply","");if(answer!=null)AppUi.update(answer,reply.isEmpty()?"Your response will appear here.":reply);if(meter!=null)meter.value(AppUi.level(this),AppUi.micActive(this));if(chat!=null)chat.render(null);}
    private void startTalk(){
        themeBusyUntil=SystemClock.elapsedRealtime()+2000L;
        if(checkSelfPermission("android.permission.RECORD_AUDIO")!=PackageManager.PERMISSION_GRANTED){Cloud.prefs(this).edit().putString("voice_status","Grant microphone permission in Companion while unlocked, then try again.").commit();refresh();return;}
        try{Cloud.prefs(this).edit().putLong("voice_entry_talk_request_ns",SystemClock.elapsedRealtimeNanos()).apply();startForegroundService(new Intent(this,VoiceService.class).setAction(VoiceService.TALK));Cloud.prefs(this).edit().putLong("voice_entry_talk_elapsed",SystemClock.elapsedRealtime()).commit();}
        catch(Exception error){Cloud.prefs(this).edit().putString("voice_status","Microphone could not start · reopen Companion").commit();}
        refresh();
    }
}
