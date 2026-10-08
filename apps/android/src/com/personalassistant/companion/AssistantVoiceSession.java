package com.personalassistant.companion;
import android.service.voice.VoiceInteractionSession;
import android.content.*;
import android.os.Bundle;
import android.widget.*;
public class AssistantVoiceSession extends VoiceInteractionSession {
    AssistantVoiceSession(Context context){super(context);}
    @Override public android.view.View onCreateContentView(){LinearLayout box=new LinearLayout(getContext());box.setOrientation(1);box.setPadding(32,32,32,32);TextView title=new TextView(getContext());title.setText("Assistant voice");title.setTextSize(22);box.addView(title);Button open=new Button(getContext());open.setText("Open voice controls");open.setOnClickListener(v->{getContext().startActivity(new Intent(getContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));hide();});box.addView(open);Button stop=new Button(getContext());stop.setText("Stop microphone");stop.setOnClickListener(v->{getContext().stopService(new Intent(getContext(),VoiceService.class));hide();});box.addView(stop);return box;}
    @Override public void onShow(Bundle args,int flags){super.onShow(args,flags);try{if(getContext().checkSelfPermission("android.permission.RECORD_AUDIO")==android.content.pm.PackageManager.PERMISSION_GRANTED)getContext().startForegroundService(new Intent(getContext(),VoiceService.class).setAction(VoiceService.TALK));else getContext().startActivity(new Intent(getContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));}catch(Exception error){Cloud.prefs(getContext()).edit().putString("voice_status","Open voice controls to start microphone").commit();}}
}
