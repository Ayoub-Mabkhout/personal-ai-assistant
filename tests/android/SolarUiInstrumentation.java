package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.content.res.Configuration;
import android.os.*;
import android.view.View;
import android.widget.EditText;
import java.lang.reflect.Field;
import java.util.*;
import java.util.function.BooleanSupplier;

/** Isolated lifecycle proof with neutral drafts, no pairing, network or microphone use. */
public final class SolarUiInstrumentation extends Instrumentation {
    private Context target;private SharedPreferences prefs;private volatile Activity active;
    private final List<Activity> created=new ArrayList<>();
    private final Bundle result=new Bundle();
    private Application application;private boolean disposable;
    private final Application.ActivityLifecycleCallbacks lifecycle=new Application.ActivityLifecycleCallbacks(){
        public void onActivityCreated(Activity a,Bundle state){created.add(a);}
        public void onActivityResumed(Activity a){active=a;}
        public void onActivityStarted(Activity a){} public void onActivityPaused(Activity a){}
        public void onActivityStopped(Activity a){} public void onActivitySaveInstanceState(Activity a,Bundle state){}
        public void onActivityDestroyed(Activity a){}
    };

    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void callActivityOnCreate(Activity activity,Bundle state){
        // Exercise the saved-state entry path without launching an audio session.
        if(activity instanceof VoiceEntryActivity&&state==null){state=new Bundle();state.putBoolean("startPending",false);}
        super.callActivityOnCreate(activity,state);
    }
    @Override public void onStart(){
        try{
            target=getTargetContext();prefs=Cloud.prefs(target);application=(Application)target.getApplicationContext();
            check("ranchu".equals(Build.HARDWARE)||"goldfish".equals(Build.HARDWARE),"Solar proof requires a disposable emulator");
            check(prefs.getString("token","").isEmpty()&&prefs.getString("origin","").isEmpty(),"Solar proof requires an unpaired app");
            disposable=true;
            runOnMainSync(()->application.registerActivityLifecycleCallbacks(lifecycle));
            prefs.edit().clear().putString("ui_theme","light").putBoolean("notification_permission_requested",true).putString("voice_status","Synthetic idle voice").commit();
            startActivitySync(new Intent(target,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            waitFor(()->active instanceof MainActivity,"Initial activity did not resume");
            MainActivity first=(MainActivity)active;
            click(first,"nav_shopping");
            runOnMainSync(()->{EditText input=edit(first,"input");input.setText("Neutral shopping draft");input.requestFocus();input.setSelection(3,9);});
            prefs.edit().putBoolean("voice_conversation_active",true).putString("ui_theme","dark").commit();
            SystemClock.sleep(1250);waitForIdleSync();
            check(active==first&&!ui(first).dark,"Theme interrupted active capture");
            prefs.edit().putBoolean("voice_conversation_active",false).commit();
            MainActivity dark=changedMain(first,true);
            assertDraft(dark,"input","Neutral shopping draft",3,9,1);
            result.putBoolean("capture_defers_palette_and_preserves_shopping_draft_caret_tab",true);

            final AlertDialog[] dialog=new AlertDialog[1];
            runOnMainSync(()->dialog[0]=new AlertDialog.Builder(dark).setTitle("Synthetic theme dialog").setMessage("Keep this open during appearance reevaluation.").setPositiveButton("Close",null).show());
            waitForIdleSync();prefs.edit().putString("ui_theme","light").commit();
            SystemClock.sleep(1250);waitForIdleSync();
            check(active==dark&&dialog[0].isShowing()&&ui(dark).dark,"Theme interrupted an open dialog");
            runOnMainSync(()->dialog[0].dismiss());
            MainActivity light=changedMain(dark,false);
            assertDraft(light,"input","Neutral shopping draft",3,9,1);
            result.putBoolean("dialog_defers_palette_until_dismissal",true);

            click(light,"nav_settings");
            runOnMainSync(()->{edit(light,"server").setText("https://example.test");EditText code=edit(light,"code");code.setText("NEUTRAL-PAIRING-DRAFT");code.requestFocus();code.setSelection(4,9);});
            prefs.edit().putString("ui_theme","dark").commit();
            MainActivity pair=changedMain(light,true);
            assertDraft(pair,"code","NEUTRAL-PAIRING-DRAFT",4,9,3);
            check(edit(pair,"server").getText().toString().equals("https://example.test"),"Pairing server draft changed");
            result.putBoolean("pairing_drafts_focus_caret_and_tab_preserved",true);

            boolean systemDark=(target.getResources().getConfiguration().uiMode&Configuration.UI_MODE_NIGHT_MASK)==Configuration.UI_MODE_NIGHT_YES;
            MainActivity opposite=pair;
            if(ui(pair).dark==systemDark){prefs.edit().putString("ui_theme",systemDark?"light":"dark").commit();opposite=changedMain(pair,!systemDark);}
            prefs.edit().remove("daylight_latitude").remove("daylight_longitude").putString("ui_theme","sun").commit();
            MainActivity fallback=changedMain(opposite,systemDark);
            check(!AppUi.daylightConfigured(target)&&ui(fallback).dark==systemDark,"Unset coordinates did not follow System");
            check(AppUi.nextThemeChange(target,System.currentTimeMillis())==Long.MAX_VALUE,"Unconfigured appearance schedules a solar timer");
            result.putBoolean("unset_daylight_follows_system_without_timer",true);

            // Installer permission/handoff state must defer the same lifecycle path.
            prefs.edit().putBoolean("update_install_pending",true).putString("ui_theme",systemDark?"light":"dark").commit();
            SystemClock.sleep(1250);waitForIdleSync();
            check(active==fallback,"Theme interrupted installer handoff state");
            prefs.edit().putBoolean("update_install_pending",false).commit();
            MainActivity afterInstall=changedMain(fallback,!systemDark);
            assertDraft(afterInstall,"code","NEUTRAL-PAIRING-DRAFT",4,9,3);
            result.putBoolean("installer_handoff_defers_palette",true);

            prefs.edit().putString("ui_theme","light").putBoolean("voice_conversation_active",false).remove("voice_entry_talk_request_ns").commit();
            startActivitySync(new Intent(target,VoiceEntryActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            waitFor(()->active instanceof VoiceEntryActivity,"Idle voice entry did not resume");
            VoiceEntryActivity voice=(VoiceEntryActivity)active;
            waitFor(()->!ui(voice).dark,"Voice entry initial palette is wrong");
            prefs.edit().putString("ui_theme","dark").commit();
            waitFor(()->active instanceof VoiceEntryActivity&&active!=voice&&ui(active).dark,"Idle voice entry did not refresh");
            check(prefs.getLong("voice_entry_talk_request_ns",0)==0,"Voice entry recreation requested another recording");
            check(!prefs.getBoolean("voice_mic_active",false),"Lifecycle proof opened the microphone");
            result.putBoolean("voice_entry_recreation_does_not_restart_talk",true);
            result.putBoolean("no_network_pairing_or_audio_used",prefs.getString("token","").isEmpty()&&prefs.getString("origin","").isEmpty());
            result.putBoolean("passed",true);result.putString("stream","Appearance lifecycle deferral, draft/caret/tab preservation, System fallback and idle voice entry recreation passed; no pairing, network or audio.");
            cleanup();finish(0,result);
        }catch(Throwable error){String trace=android.util.Log.getStackTraceString(error);result.putString("error",trace);result.putString("stream",trace);try{cleanup();}catch(Throwable ignored){}finish(1,result);}
    }

    private void cleanup(){if(!disposable)return;runOnMainSync(()->{if(application!=null)application.unregisterActivityLifecycleCallbacks(lifecycle);for(Activity activity:new ArrayList<>(created))if(!activity.isFinishing())activity.finish();if(prefs!=null)prefs.edit().clear().commit();});waitForIdleSync();}
    private static Object field(Object owner,String name){try{Field f=owner.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(owner);}catch(Exception error){throw new RuntimeException(error);}}
    private static AppUi ui(Activity a){return (AppUi)field(a,"ui");}
    /** The shopping draft lives in the Shopping page, the pairing drafts in the Settings page. */
    private static EditText edit(MainActivity a,String name){return (EditText)field(field(a,name.equals("input")?"shopping":"settings"),name);}
    private void click(Activity a,String tag){runOnMainSync(()->{View v=a.getWindow().getDecorView().findViewWithTag(tag);check(v!=null,"Missing view "+tag);v.performClick();});waitForIdleSync();}
    private MainActivity changedMain(MainActivity old,boolean dark){waitFor(()->active instanceof MainActivity&&active!=old&&ui(active).dark==dark,"Main appearance did not refresh safely");waitForIdleSync();return (MainActivity)active;}
    private void assertDraft(MainActivity a,String name,String text,int start,int end,int tab){runOnMainSync(()->{EditText e=edit(a,name);check(e.getText().toString().equals(text)&&e.hasFocus()&&e.getSelectionStart()==start&&e.getSelectionEnd()==end,"Draft/focus/caret changed for "+name);check(((Integer)field(a,"selected"))==tab,"Selected tab changed");});}
    private void waitFor(BooleanSupplier condition,String message){long end=SystemClock.elapsedRealtime()+8000;while(SystemClock.elapsedRealtime()<end){waitForIdleSync();if(condition.getAsBoolean())return;SystemClock.sleep(50);}throw new AssertionError(message);}
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
