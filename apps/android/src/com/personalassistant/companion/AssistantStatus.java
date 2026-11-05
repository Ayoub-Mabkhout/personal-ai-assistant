package com.personalassistant.companion;

import android.app.Activity;
import android.view.View;
import org.json.JSONObject;

/** A relay-backed chip used by the app header and specialist chats. */
final class AssistantStatus {
    static void show(AppUi.StatusChip chip,String name,String state){
        boolean online="ready".equals(state)||"busy".equals(state);
        String label=name+(state.isEmpty()?" · Checking…":online?" online":" offline");
        if(label.contentEquals(chip.getText()))return;
        AppUi.update(chip,label);
        chip.tone(online?"success":state.isEmpty()?"neutral":"warning");
        chip.setContentDescription(label);
    }

    static AppUi.StatusChip worker(Activity activity,AppUi ui,Runnable openConnection){
        AppUi.StatusChip chip=ui.statusChip("Worker · Checking…","neutral");
        chip.setTag("worker_status");
        if(openConnection!=null)chip.setOnClickListener(v->openConnection.run());
        Runnable refresh=new Runnable(){
            boolean checking;

            public void run(){
                if(!chip.isAttachedToWindow()||activity.isDestroyed())return;
                chip.postDelayed(this,15000);
                if(!chip.isShown()||!chip.hasWindowFocus()||checking)return;
                if(!VoiceOutbox.networkReady(activity)){
                    show(chip,"Worker","unavailable");
                    return;
                }
                checking=true;
                new Thread(()->{
                    String state="unavailable";
                    try{
                        JSONObject result=(JSONObject)Cloud.call(activity,"voice/status",null,true);
                        JSONObject connection=result.getJSONObject("connection");
                        state=connection.optString("assistant",connection.optString("server",connection.optString("laptop","unavailable")));
                    }catch(Exception ignored){}
                    String current=state;
                    activity.runOnUiThread(()->{
                        checking=false;
                        if(chip.isAttachedToWindow())show(chip,"Worker",current);
                    });
                },"assistant-status").start();
            }
        };
        chip.addOnAttachStateChangeListener(new View.OnAttachStateChangeListener(){
            public void onViewAttachedToWindow(View view){chip.post(refresh);}
            public void onViewDetachedFromWindow(View view){chip.removeCallbacks(refresh);}
        });
        return chip;
    }
}
