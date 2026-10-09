package com.personalassistant.companion;
import android.app.*;
import android.content.*;
import android.net.Uri;
import android.provider.Settings;
import android.widget.*;
import org.json.*;

/** Setup and a real local round-trip test; uses the existing app visual controls. */
final class TermuxSetup {
    static void show(Activity a,AppUi ui){
        LinearLayout box=ui.column();box.setPadding(ui.dp(22),ui.dp(8),ui.dp(22),ui.dp(8));
        box.addView(ui.type("Run phone scripts through Termux. Install and open Termux once, then enable external commands and grant Companion permission.",14,20,400,0,ui.text));
        box.addView(ui.type("Status: "+TermuxBridge.status(a)+"\n"+Cloud.prefs(a).getString("termux_status","No commands yet"),13,19,400,0,ui.muted));
        Switch enabled=ui.switchControl(TermuxBridge.enabled(a),"Enable phone commands");enabled.setText("Enable phone commands");enabled.setOnCheckedChangeListener((b,on)->{Cloud.prefs(a).edit().putBoolean("termux_enabled",on).commit();TermuxSyncJob.schedule(a,true);TermuxSyncJob.schedule(a,false);});box.addView(enabled);
        box.addView(ui.primaryButton(TermuxBridge.installed(a)?"Open Termux":"Install Termux",()->{try{Intent i=TermuxBridge.installed(a)?a.getPackageManager().getLaunchIntentForPackage("com.termux"):new Intent(Intent.ACTION_VIEW,Uri.parse("https://f-droid.org/packages/com.termux/"));if(i!=null)a.startActivity(i);}catch(Exception e){Toast.makeText(a,e.getMessage(),Toast.LENGTH_LONG).show();}}));
        box.addView(ui.primaryButton("Copy Termux setup command",()->{String command="mkdir -p ~/.termux; touch ~/.termux/termux.properties; grep -q '^allow-external-apps=true$' ~/.termux/termux.properties || printf '\\nallow-external-apps=true\\n' >> ~/.termux/termux.properties; termux-reload-settings";((ClipboardManager)a.getSystemService(Context.CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("Termux setup",command));Toast.makeText(a,"Paste and run in Termux",Toast.LENGTH_LONG).show();}));
        box.addView(ui.primaryButton("Grant command permission",()->{if(TermuxBridge.installed(a)&&!TermuxBridge.permission(a))a.requestPermissions(new String[]{TermuxBridge.PERMISSION},303);else a.startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.parse("package:"+a.getPackageName())));}));
        box.addView(ui.primaryButton("Test connection",()->{try{TermuxBridge.test(a);Toast.makeText(a,"Test sent. Reopen this page to see the result.",Toast.LENGTH_LONG).show();}catch(Exception e){Toast.makeText(a,e.getMessage(),Toast.LENGTH_LONG).show();}}));
        String last=Cloud.prefs(a).getString("termux_last_result","");if(!last.isEmpty())try{JSONObject r=new JSONObject(last);box.addView(ui.type("Latest result\n"+r.optString("stdout")+"\n"+r.optString("stderr")+"\n"+r.optString("error"),13,18,400,0,ui.text));}catch(Exception ignored){}
        box.addView(ui.type("Background execution uses Android permissions and battery settings. Install Termux:API from the same source for contacts, sensors and other phone APIs. Commands have a time limit; uncertain results are never automatically rerun.",12,18,400,0,ui.muted));
        ScrollView scroll=new ScrollView(a);scroll.addView(box);new AlertDialog.Builder(a).setTitle("Phone scripting").setView(scroll).setPositiveButton("Close",null).show();
    }
}
