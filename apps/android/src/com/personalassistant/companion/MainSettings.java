package com.personalassistant.companion;

import android.app.NotificationManager;
import android.app.role.RoleManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.*;
import android.provider.Settings;
import android.text.InputType;
import android.view.*;
import android.widget.*;

/** Settings tab: grouped icon-tile rows, the pairing form and the app footer. */
final class MainSettings {
    private final MainActivity a;private final AppUi ui;
    final EditText server,code;final Button connect,install;final TextView pairStatus,accountStatus,pushStatus,updateStatus;final LinearLayout pairBox;
    private long checkedAt;private boolean online,granted,role,unrestricted,notifying=true;private final AppUi.StatusChip micChip,accountChip;private final AppUi.Icon accountGlyph,micChevron;private final FrameLayout accountTile;private final AppUi.ActionRow assistant,battery,sensitivity,appearance,notifications,disconnect,features;

    MainSettings(MainActivity a,AppUi ui,LinearLayout page){
        this.a=a;this.ui=ui;SharedPreferences prefs=Cloud.prefs(a);
        page.addView(ui.header("Settings","Voice, connection and phone setup."));ui.space(page,14);

        ui.label(page,"Phone setup");LinearLayout setup=ui.rowsCard();
        LinearLayout mic=tileRow("voice",a::microphonePermission);mic.addView(ui.type("Microphone permission",15,21,500,0,ui.text),MainParts.weighted(ui,1,14,0,8,0));micChip=ui.statusChip("Allowed","success");mic.addView(micChip);micChevron=MainParts.icon(ui,"arrow",ui.muted);mic.addView(micChevron,new LinearLayout.LayoutParams(ui.dp(18),ui.dp(18)));setup.addView(mic);
        assistant=row(setup,"Digital assistant","sparkle","Set up",a::chooseAssistant);battery=row(setup,"Battery settings","battery","",()->a.openSettings(new android.content.Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)));
        row(setup,"Phone scripting","code","Termux",()->TermuxSetup.show(a,ui)).setTag("termux_setup");
        line(setup);note(setup,"Choose Unrestricted for battery. Enable Background listening, wait until ready, then lock your phone.");page.addView(setup);

        ui.label(page,"Voice & appearance");LinearLayout voice=ui.rowsCard();
        LinearLayout preview=tileRow("chat",null);preview.addView(labels("Transcription preview","Show words without executing commands."),MainParts.weighted(ui,1,14,0,8,0));
        Switch toggle=ui.switchControl(prefs.getBoolean("voice_preview",false),"Transcription preview");toggle.setTag("transcription_preview");
        toggle.setOnCheckedChangeListener((button,on)->Cloud.prefs(a).edit().putBoolean("voice_preview",on).apply());preview.addView(toggle,new LinearLayout.LayoutParams(ui.dp(60),ui.dp(48)));preview.setClickable(true);preview.setFocusable(true);preview.setOnClickListener(v->toggle.performClick());preview.setBackground(ui.pressable(null,16));preview.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);voice.addView(preview);
        sensitivity=row(voice,"Wake sensitivity","waveform","Balanced",a::sensitivity);sensitivity.setTag("wake_sensitivity");appearance=row(voice,"Appearance","appearance","",a::appearance);appearance.setTag("appearance");
        line(voice);note(voice,"Hey Chat handles one command, then returns to standby. Start conversation mode keeps listening until you say That was all.");page.addView(voice);

        ui.label(page,"Account");LinearLayout account=ui.rowsCard();
        LinearLayout status=tileRow("shield-check",null);accountTile=(FrameLayout)status.getChildAt(0);accountGlyph=(AppUi.Icon)accountTile.getChildAt(0);
        LinearLayout words=ui.column();accountStatus=ui.type("",15,21,500,0,ui.text);words.addView(accountStatus);pushStatus=ui.type(prefs.getString("push_status","Notification connection will be set up after pairing."),12,16,400,0,ui.muted);pushStatus.setTag("push_status");words.addView(pushStatus,MainParts.params(ui,-1,-2,0,2,0,0));
        status.addView(words,MainParts.weighted(ui,1,14,0,8,0));accountChip=ui.statusChip("Not connected","neutral");status.addView(accountChip);account.addView(status);
        pairBox=ui.column();pairBox.setPadding(ui.dp(14),ui.dp(2),ui.dp(14),ui.dp(10));
        server=ui.field("HTTPS server address",prefs.getString("origin",""));server.setTag("server_address");server.setContentDescription("Server address");server.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_URI);pairBox.addView(server);ui.space(pairBox,10);
        code=ui.field("One-use pairing code","");code.setTag("pairing_code");code.setContentDescription("Pairing code");code.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);pairBox.addView(code);ui.space(pairBox,10);
        pairStatus=ui.type("Open Groceries on the web and tap \"Phone widget & alarms\" for a code.",13,18,400,0,ui.muted);pairStatus.setTag("pairing_status");pairStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);pairBox.addView(pairStatus,MainParts.params(ui,-1,-2,4,0,4,0));
        connect=ui.primaryButton("Connect phone",a::pair);connect.setTag("pair");pairBox.addView(connect,MainParts.params(ui,-1,-2,0,14,0,0));account.addView(pairBox);
        disconnect=ui.dangerRow("Disconnect phone","logout",a::disconnect);account.addView(disconnect,new LinearLayout.LayoutParams(-1,-2));page.addView(account);

        ui.label(page,"App & shortcuts");LinearLayout app=ui.rowsCard();
        features=row(app,"Features checklist","checklist","",a::features);features.setTag("features_checklist");
        row(app,"Check for updates","download","",()->a.checkUpdates(true));updateStatus=ui.type("",13,18,400,0,ui.muted);updateStatus.setTag("update_status");app.addView(updateStatus,MainParts.params(ui,-1,-2,66,0,14,8));
        install=ui.primaryButton("Install update",()->Updates.install(a));install.setTag("install_update");install.setVisibility(View.GONE);app.addView(install,MainParts.params(ui,-1,-2,14,2,14,10));
        notifications=row(app,"Notifications","bell","",a::notificationSettings);row(app,"Microphone Quick Settings tile","tile","",a::addMicrophoneTile).setTag("add_mic_tile");
        line(app);note(app,"Shopping widget: long press your Home screen, then Widgets. Task details and follow-ups open in Companion.");page.addView(app);

        String version="";try{version=a.getPackageManager().getPackageInfo(a.getPackageName(),0).versionName;}catch(Exception ignored){}
        TextView footer=ui.type("Assistant Companion \u00b7 version "+version,12,16,400,0,ui.muted);footer.setGravity(Gravity.CENTER);page.addView(footer,MainParts.params(ui,-1,-2,0,4,0,8));
    }

    /** Row with a 36 dp icon tile at 16 dp, so text, dividers and footnotes share one start edge (66 dp). */
    private LinearLayout tileRow(String icon,Runnable action){
        LinearLayout row=ui.row();row.setMinimumHeight(ui.dp(56));row.setPadding(ui.dp(16),ui.dp(8),ui.dp(14),ui.dp(8));
        int[] tone=ui.iconTone(icon);FrameLayout tile=new FrameLayout(a);tile.setBackground(ui.outline(tone[1],12,0,0));tile.addView(MainParts.icon(ui,icon,tone[0]),new FrameLayout.LayoutParams(ui.dp(20),ui.dp(20),Gravity.CENTER));row.addView(tile,new LinearLayout.LayoutParams(ui.dp(36),ui.dp(36)));
        if(action!=null){row.setBackground(ui.pressable(null,16));row.setClickable(true);row.setFocusable(true);row.setOnClickListener(v->action.run());AppUi.press(row);}
        return row;
    }
    private AppUi.ActionRow row(LinearLayout card,String title,String icon,String value,Runnable action){AppUi.ActionRow row=ui.actionRow(title,icon,value,action);card.addView(row,new LinearLayout.LayoutParams(-1,-2));return row;}
    private LinearLayout labels(String title,String detail){LinearLayout box=ui.column();box.addView(ui.type(title,15,21,500,0,ui.text));box.addView(ui.type(detail,13,18,400,0,ui.muted),MainParts.params(ui,-2,-2,0,1,0,0));return box;}
    private void line(LinearLayout card){ui.hairline(card,66,2,14);}
    private void note(LinearLayout card,String text){card.addView(ui.type(text,13,18,400,0,ui.muted),MainParts.params(ui,-1,-2,66,8,14,12));}

    void pairing(boolean busy){connect.setEnabled(!busy);connect.setText(busy?"Connecting...":"Connect phone");}
    void pairNote(String message){AppUi.update(pairStatus,message);}

    private static void value(AppUi.ActionRow row,String value){if(!row.value.equals(value))row.value(value);}
    /** Without privately configured coordinates the sun mode follows System; the dialog spells that out, the row value stays narrow enough for the title on 360 dp phones. */
    static String themeName(Context c,String value,boolean full){return value.equals("light")?"Light":value.equals("dark")?"Dark":value.equals("system")?"System":AppUi.daylightConfigured(c)?"Sunrise & sunset":full?"Sunrise & sunset · System until configured":"Sun · System";}

    /** Prefs-derived state refreshes on every call; system queries only while the tab is open and at most every 1.5 s. */
    void refresh(boolean full,boolean paired){
        SharedPreferences p=Cloud.prefs(a);boolean expired=p.getString("status","").startsWith("Disconnected.");
        pairBox.setVisibility(paired?View.GONE:View.VISIBLE);disconnect.setVisibility(paired?View.VISIBLE:View.GONE);
        AppUi.update(pushStatus,p.getString("push_status","Notification connection will be set up after pairing."));AppUi.update(updateStatus,a.updating()?"Checking for updates...":p.getString("update_status","Updates arrive through release notifications."));install.setVisibility(p.contains("update_release")?View.VISIBLE:View.GONE);
        if(!full)return;
        long now=SystemClock.uptimeMillis();
        if(now-checkedAt>1500){checkedAt=now;online=VoiceOutbox.networkReady(a);granted=a.checkSelfPermission("android.permission.RECORD_AUDIO")==PackageManager.PERMISSION_GRANTED;role=false;if(Build.VERSION.SDK_INT>=29){RoleManager manager=a.getSystemService(RoleManager.class);role=manager!=null&&manager.isRoleHeld(RoleManager.ROLE_ASSISTANT);}
            PowerManager power=a.getSystemService(PowerManager.class);unrestricted=power!=null&&power.isIgnoringBatteryOptimizations(a.getPackageName());NotificationManager notes=a.getSystemService(NotificationManager.class);notifying=notes==null||notes.areNotificationsEnabled();}
        String host=Uri.parse(p.getString("origin","")).getHost();
        AppUi.update(accountStatus,paired?(host==null?"Phone connected":host):expired?"Connection expired. Pair again; saved changes stay on this phone.":"Connect this phone to your assistant server.");
        String chip=paired?(online?"Online":"Offline"):expired?"Expired":"Not connected",tone=paired?(online?"success":"warning"):expired?"danger":"neutral";
        if(!chip.equals(accountChip.getText().toString())){accountChip.setText(chip);accountChip.tone(tone);}
        String glyph=paired?"shield-check":expired?"alert":"link";if(!glyph.equals(accountGlyph.kind)){int[] c=ui.iconTone(glyph);accountGlyph.kind(glyph);accountGlyph.color(c[0]);accountTile.setBackground(ui.outline(c[1],12,0,0));}
        String access=granted?"Allowed":"Off";if(!access.equals(micChip.getText().toString())){micChip.setText(access);micChip.tone(granted?"success":"warning");}micChevron.setVisibility(granted?View.GONE:View.VISIBLE);
        value(assistant,role?"Selected":"Set up");value(battery,unrestricted?"Unrestricted":"Optimized");
        value(sensitivity,"sensitive".equals(p.getString("wake_sensitivity","balanced"))?"Sensitive":"Balanced");value(appearance,themeName(a,p.getString("ui_theme","sun"),false));value(notifications,notifying?"On":"Off");
        String open="";try{java.util.List<FeatureBoard.Item> list=Features.board(a);int count=FeatureBoard.open(list);open=list.isEmpty()?"":count==0?"All done":count+" open";}catch(RuntimeException ignored){}value(features,open);
    }
    void refreshNow(boolean paired){checkedAt=0;refresh(true,paired);}
}
