package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.*;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.*;
import java.util.Locale;

/** Lightweight voice entry above keyguard; never requests device unlock. */
public final class VoiceEntryActivity extends Activity {
    private AppUi ui;private ChatTimeline chat;private AppUi.Meter meter;private AppUi.VoiceButton talk;private TextView status,detail;private boolean registered,startPending=true,themeRecreate,orbLive;
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final Runnable themeCheck=this::checkTheme;
    private final android.content.SharedPreferences.OnSharedPreferenceChangeListener preferences=(p,key)->{if("voice_level".equals(key)&&meter!=null){boolean mic=AppUi.micActive(this);float level=AppUi.level(this);meter.value(level,mic);if(talk!=null)talk.level(level,mic&&orbLive);}else refresh();};
    private final BroadcastReceiver voiceState=new BroadcastReceiver(){@Override public void onReceive(Context c,Intent i){refresh();}};
    @Override public void onCreate(Bundle state){
        AppUi.theme(this);super.onCreate(state);ui=new AppUi(this);ui.window();startPending=state==null||!state.getBoolean("themed");
        if(Build.VERSION.SDK_INT>=27){setShowWhenLocked(true);setTurnScreenOn(true);}
        else getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED|WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        boolean locked=getSystemService(KeyguardManager.class).isDeviceLocked();
        LinearLayout box=ui.column();box.setPadding(ui.dp(24),ui.dp(22),ui.dp(24),ui.dp(16));
        LinearLayout header=ui.row();header.addView(ui.display("Voice"),new LinearLayout.LayoutParams(0,-2,1));header.addView(ui.badge(locked?"Phone locked":"Hands-free"));box.addView(header);ui.space(box,8);
        LinearLayout hero=ui.column();hero.setGravity(Gravity.CENTER_HORIZONTAL);
        talk=ui.voiceButton(this::startTalk);talk.setTag("locked_talk");hero.addView(talk,new LinearLayout.LayoutParams(ui.dp(244),ui.dp(244)));ui.space(hero,6);
        status=ui.title("Starting microphone...");status.setGravity(Gravity.CENTER);status.setTag("locked_voice_status");status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);hero.addView(status,new LinearLayout.LayoutParams(-1,-2));ui.space(hero,6);
        detail=ui.detail("");detail.setGravity(Gravity.CENTER);hero.addView(detail,new LinearLayout.LayoutParams(-1,-2));
        meter=new AppUi.Meter(this,ui);LinearLayout.LayoutParams mp=new LinearLayout.LayoutParams(ui.dp(150),ui.dp(25));mp.topMargin=ui.dp(14);mp.bottomMargin=ui.dp(16);hero.addView(meter,mp);
        Button stop=ui.stopButton("Stop microphone",()->{Cloud.prefs(this).edit().putBoolean("wake_enabled",false).putBoolean("voice_listening_test",false).apply();stopService(new Intent(this,VoiceService.class));refresh();});hero.addView(stop,new LinearLayout.LayoutParams(-1,-2));box.addView(hero);ui.space(box,24);
        ui.label(box,"CONVERSATION");chat=new ChatTimeline(ui);box.addView(chat.rows);
        box.addView(new View(this),new LinearLayout.LayoutParams(1,0,1));ui.space(box,12);
        box.addView(ui.ghostButton("Close",this::finish),new LinearLayout.LayoutParams(-1,-2));ui.space(box,2);TextView note=ui.detail("Close hides this screen. Stop microphone ends listening.");note.setTextSize(13);note.setGravity(Gravity.CENTER);box.addView(note,new LinearLayout.LayoutParams(-1,-2));
        ScrollView scroll=new ScrollView(this);scroll.setFitsSystemWindows(true);scroll.setFillViewport(true);scroll.setBackground(ui.pageBackground());scroll.addView(box);setContentView(scroll);
        Cloud.prefs(this).edit().putLong("voice_entry_created_elapsed",SystemClock.elapsedRealtime()).putLong("voice_entry_created_ns",SystemClock.elapsedRealtimeNanos()).putBoolean("voice_entry_created_locked",locked).commit();
        refresh();
    }
    @Override public void onSaveInstanceState(Bundle state){state.putBoolean("themed",themeRecreate&&!startPending);super.onSaveInstanceState(state);}
    @Override public void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);startPending=true;}
    @Override public void onStart(){super.onStart();IntentFilter filter=new IntentFilter("com.personalassistant.companion.VOICE_STATE");if(Build.VERSION.SDK_INT>=33)registerReceiver(voiceState,filter,Context.RECEIVER_NOT_EXPORTED);else registerReceiver(voiceState,filter);registered=true;Cloud.prefs(this).registerOnSharedPreferenceChangeListener(preferences);}
    @Override public void onResume(){super.onResume();if(ui==null)return;if(AppUi.dark(this)!=ui.dark){themeRecreate=true;recreate();return;}ui.window();if(startPending){startPending=false;startTalk();}refresh();watchTheme();}
    @Override public void onPause(){handler.removeCallbacks(themeCheck);super.onPause();}
    @Override public void onWindowFocusChanged(boolean focus){super.onWindowFocusChanged(focus);if(focus&&ui!=null)ui.window();}
    @Override public void onStop(){if(registered){unregisterReceiver(voiceState);registered=false;}Cloud.prefs(this).unregisterOnSharedPreferenceChangeListener(preferences);super.onStop();}
    /** The sunrise and sunset theme flips while the screen is open, so re-check at the computed moment. */
    private void watchTheme(){handler.removeCallbacks(themeCheck);if(!"sun".equals(Cloud.prefs(this).getString("ui_theme","sun")))return;long now=System.currentTimeMillis();handler.postDelayed(themeCheck,Math.max(1000,DaylightTheme.nextChange(now)-now+1000));}
    private void checkTheme(){if(isFinishing()||isDestroyed())return;if(AppUi.dark(this)!=ui.dark){themeRecreate=true;recreate();}else watchTheme();}
    private static boolean live(String orb){return orb.equals("listening")||orb.equals("conversation");}
    /** Friendly {title, detail, orb state} for the raw voice_status; shared with the assistant overlay. */
    static String[] describe(Context c){
        android.content.SharedPreferences p=Cloud.prefs(c);boolean mic=AppUi.micActive(c),wake=p.getBoolean("wake_enabled",false);
        String raw=p.getString("voice_status","Microphone off"),low=raw.toLowerCase(Locale.ROOT);
        if(low.contains("starting")||low.contains("preparing")||low.contains("loading"))return new String[]{"Getting ready...","The microphone is starting.","working"};
        if(low.contains("sending")||low.contains("connecting"))return new String[]{"Connecting...","Your audio is buffered while the connection starts.","working"};
        if(low.startsWith("open "))return new String[]{"Open the app to start",raw,"attention"};
        if(low.contains("no internet")||low.contains("saved on this phone")||low.contains("cloud unavailable"))return new String[]{VoiceOutbox.pending(c)>0?"Saved offline":wake&&mic?"Listening offline":"Offline",raw,"offline"};
        if(low.contains("permission")||low.contains("interrupted")||low.contains("could not")||low.contains("unavailable")||low.contains("voice stopped")||low.contains("connection lost"))return new String[]{"Needs attention",raw,"attention"};
        if(mic&&low.contains("listening to your command"))return new String[]{"Listening to you","Say your full request, then pause.","listening"};
        if(mic&&(p.getBoolean("voice_conversation_mode",false)||p.getBoolean("voice_conversation_active",false)||low.contains("live voice")||low.contains("live microphone")||low.contains("conversation mode")))return new String[]{"Conversation active","Speak naturally. Say That was all to end.","conversation"};
        if(low.contains("no speech"))return new String[]{"No speech heard","Tap the orb to try again.","idle"};
        if(wake&&mic)return new String[]{"Listening for Hey Chat","You can leave this screen or lock your phone.","idle"};
        if(mic)return new String[]{"Microphone ready","Tap the orb to start a request.","idle"};
        return new String[]{"Microphone off","Tap the orb to start talking.","idle"};
    }
    private void refresh(){
        String[] s=describe(this);boolean mic=AppUi.micActive(this);
        orbLive=live(s[2]);if(talk!=null){talk.state(s[2]);talk.level(AppUi.level(this),mic&&orbLive);}
        AppUi.update(status,s[0]);AppUi.update(detail,s[1]);
        if(meter!=null)meter.value(AppUi.level(this),mic);
        if(chat!=null)chat.render(null);
    }
    private void startTalk(){
        if(checkSelfPermission("android.permission.RECORD_AUDIO")!=PackageManager.PERMISSION_GRANTED){Cloud.prefs(this).edit().putString("voice_status","Grant microphone permission in Companion while unlocked, then try again.").commit();refresh();return;}
        try{Cloud.prefs(this).edit().putLong("voice_entry_talk_request_ns",SystemClock.elapsedRealtimeNanos()).apply();startForegroundService(new Intent(this,VoiceService.class).setAction(VoiceService.TALK));Cloud.prefs(this).edit().putLong("voice_entry_talk_elapsed",SystemClock.elapsedRealtime()).commit();}
        catch(Exception error){Cloud.prefs(this).edit().putString("voice_status","Microphone could not start · reopen Companion").commit();}
        refresh();
    }
}
