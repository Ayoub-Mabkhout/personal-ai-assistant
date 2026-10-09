package com.personalassistant.companion;

import android.app.PendingIntent;
import android.app.role.RoleManager;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.drawable.Icon;
import android.os.Build;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

/** Explicit user microphone control; no polling, model inference or network work. */
public final class MicrophoneTile extends TileService {
    private boolean registered;
    private final SharedPreferences.OnSharedPreferenceChangeListener changes=(prefs,key)->{if(key.equals("voice_mic_active")||key.equals("voice_metrics_elapsed")||key.equals("voice_status")||key.equals("wake_enabled")||key.equals("voice_listening_test"))update();};
    @Override public void onStartListening(){super.onStartListening();if(!registered){Cloud.prefs(this).registerOnSharedPreferenceChangeListener(changes);registered=true;}update();}
    @Override public void onStopListening(){if(registered){Cloud.prefs(this).unregisterOnSharedPreferenceChangeListener(changes);registered=false;}super.onStopListening();}
    @Override public void onDestroy(){if(registered)Cloud.prefs(this).unregisterOnSharedPreferenceChangeListener(changes);registered=false;super.onDestroy();}
    private void update(){Tile tile=getQsTile();if(tile==null)return;SharedPreferences prefs=Cloud.prefs(this);boolean on=AppUi.micActive(this);String detail=on?(prefs.getBoolean("voice_listening_test",false)?"Local wake test":"Microphone on"):(prefs.getBoolean("wake_enabled",false)?"Starting or paused":"Microphone off");tile.setIcon(Icon.createWithResource(this,R.drawable.ic_tile_mic));tile.setLabel("Assistant mic");tile.setState(on?Tile.STATE_ACTIVE:Tile.STATE_INACTIVE);if(Build.VERSION.SDK_INT>=29)tile.setSubtitle(detail);if(Build.VERSION.SDK_INT>=30)tile.setStateDescription(detail);tile.setContentDescription("Assistant microphone. "+detail);tile.updateTile();}
    @Override public void onClick(){super.onClick();SharedPreferences prefs=Cloud.prefs(this);
        if(AppUi.micActive(this)||prefs.getBoolean("wake_enabled",false)){
            prefs.edit().putBoolean("wake_enabled",false).putBoolean("voice_listening_test",false).putBoolean("ui_test_background_desired",false).apply();stopService(new Intent(this,VoiceService.class));update();return;
        }
        boolean allowed=checkSelfPermission("android.permission.RECORD_AUDIO")==PackageManager.PERMISSION_GRANTED;
        boolean assistant=false;if(Build.VERSION.SDK_INT>=29){RoleManager roles=getSystemService(RoleManager.class);assistant=roles!=null&&roles.isRoleHeld(RoleManager.ROLE_ASSISTANT);}
        if(allowed&&assistant){try{prefs.edit().putBoolean("wake_enabled",true).apply();startForegroundService(new Intent(this,VoiceService.class));update();return;}catch(Exception unavailable){prefs.edit().putBoolean("wake_enabled",false).putString("voice_status","Open the companion to start the microphone").apply();}}
        // Android's microphone restrictions need a visible app unless this is
        // the selected assistant. Opening Voice lets the user finish setup.
        Intent open=new Intent(this,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TOP);
        if(Build.VERSION.SDK_INT>=34)startActivityAndCollapse(PendingIntent.getActivity(this,225,open,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE));else startActivityAndCollapse(open);
    }
}
