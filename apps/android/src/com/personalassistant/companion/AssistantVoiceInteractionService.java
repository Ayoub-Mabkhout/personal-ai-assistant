package com.personalassistant.companion;
import android.service.voice.VoiceInteractionService;
import android.content.Intent;
import android.content.pm.PackageManager;
public class AssistantVoiceInteractionService extends VoiceInteractionService {
    private boolean inactive;
    @Override public void onReady(){super.onReady();if(inactive||!isActiveService(this,new android.content.ComponentName(this,AssistantVoiceInteractionService.class)))return;if(Cloud.prefs(this).getBoolean("wake_enabled",false)&&checkSelfPermission("android.permission.RECORD_AUDIO")==PackageManager.PERMISSION_GRANTED)try{startForegroundService(new Intent(this,VoiceService.class));}catch(Exception e){Cloud.prefs(this).edit().putString("voice_status","Open the companion to restart wake listening").commit();}}
    @Override public void onLaunchVoiceAssistFromKeyguard(){if(inactive)return;Cloud.prefs(this).edit().putLong("voice_keyguard_callback_elapsed",android.os.SystemClock.elapsedRealtime()).putLong("voice_keyguard_callback_ns",android.os.SystemClock.elapsedRealtimeNanos()).apply();startActivity(new Intent(this,VoiceEntryActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TOP));}
    @Override public void onShutdown(){inactive=true;stopService(new Intent(this,VoiceService.class));super.onShutdown();}
    @Override public void onDestroy(){inactive=true;super.onDestroy();}
}
