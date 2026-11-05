package com.personalassistant.companion;

import android.app.Activity;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.View;
import android.view.ViewTreeObserver;
import org.json.JSONObject;
import java.util.*;

/**
 * Relay-backed worker chip for the app header, task sheets and quick task. One shared request serves every chip; a new
 * chip shows the last result at once, a gained window focus (cold start, resume, closing a sheet) refreshes it, and a
 * chip still checking after {@link WorkerReadiness#TIMEOUT_MS} says the status did not arrive instead of spinning.
 */
final class AssistantStatus {
    private static final long PERIOD_MS=15000,MIN_GAP_MS=4000;
    private static final Handler MAIN=new Handler(Looper.getMainLooper());
    private static final Set<AppUi.StatusChip> chips=Collections.newSetFromMap(new WeakHashMap<>());
    private static String cached=WorkerReadiness.CHECKING;
    private static long cachedAt,startedAt=-MIN_GAP_MS;
    private static boolean checking;

    /** Specialist chips (Coach, Money) pass their own readiness here. */
    static void show(AppUi.StatusChip chip,String name,String state){
        String label=WorkerReadiness.label(name,state);
        chip.setContentDescription(WorkerReadiness.description(name,state));
        if(label.contentEquals(chip.getText()))return;
        AppUi.update(chip,label);
        chip.tone(WorkerReadiness.tone(state));
    }

    /** Readiness that needs no request: an unpaired phone, or no network at all. */
    static String local(Context context){
        android.content.SharedPreferences p=Cloud.prefs(context);
        if(p.getString("origin","").isEmpty()||p.getString("token","").isEmpty()||p.getString("status","").startsWith("Disconnected."))return WorkerReadiness.UNPAIRED;
        if(!VoiceOutbox.networkReady(context))return WorkerReadiness.NO_NETWORK;
        return null;
    }

    /** What a failed specialist request says about readiness. */
    static String failure(Context context,Exception error){
        String known=local(context);if(known!=null)return known;
        return error instanceof Cloud.HttpError?WorkerReadiness.failure(((Cloud.HttpError)error).status):WorkerReadiness.UNREACHABLE;
    }

    /** Puts a "Checking…" chip into a resolved state when its first answer has not come within the timeout. */
    static void timeout(AppUi.StatusChip chip,String name){
        chip.postDelayed(()->{if(chip.isAttachedToWindow()&&WorkerReadiness.label(name,"").contentEquals(chip.getText()))show(chip,name,WorkerReadiness.TIMEOUT);},WorkerReadiness.TIMEOUT_MS);
    }

    static AppUi.StatusChip worker(Activity activity,AppUi ui,Runnable openConnection){
        Context app=activity.getApplicationContext();
        AppUi.StatusChip chip=ui.statusChip(WorkerReadiness.label("Worker",""),"neutral");
        chip.setTag("worker_status");
        String known=local(app);
        if(known!=null)show(chip,"Worker",known);
        else if(!cached.isEmpty()&&SystemClock.elapsedRealtime()-cachedAt<WorkerReadiness.FRESH_MS)show(chip,"Worker",cached);
        if(openConnection!=null)chip.setOnClickListener(v->openConnection.run());
        Runnable tick=new Runnable(){public void run(){
            if(!chip.isAttachedToWindow()||activity.isDestroyed())return;
            chip.postDelayed(this,PERIOD_MS);
            if(chip.isShown()&&chip.hasWindowFocus())refresh(app,false);
        }};
        ViewTreeObserver.OnWindowFocusChangeListener focus=has->{if(has&&chip.isShown())refresh(app,true);};
        chip.addOnAttachStateChangeListener(new View.OnAttachStateChangeListener(){
            public void onViewAttachedToWindow(View view){
                chips.add(chip);chip.getViewTreeObserver().addOnWindowFocusChangeListener(focus);
                // The first check does not wait for window focus: on a cold start focus arrives after attach.
                refresh(app,true);chip.postDelayed(tick,PERIOD_MS);timeout(chip,"Worker");
            }
            public void onViewDetachedFromWindow(View view){
                chips.remove(chip);chip.removeCallbacks(tick);chip.getViewTreeObserver().removeOnWindowFocusChangeListener(focus);
            }
        });
        return chip;
    }

    /** One request at a time for all chips; a forced refresh (focus, attach) still waits {@link #MIN_GAP_MS} after the last one. */
    static void refresh(Context app,boolean force){
        String known=local(app);
        if(known!=null){publish(known);return;}
        long now=SystemClock.elapsedRealtime();
        if(checking||now-startedAt<(force?MIN_GAP_MS:PERIOD_MS-1000))return;
        checking=true;startedAt=now;
        new Thread(()->{
            String state;
            try{
                JSONObject connection=((JSONObject)Cloud.call(app,"voice/status",null,true)).getJSONObject("connection");
                state=WorkerReadiness.pick(connection.optString("assistant"),connection.optString("server"),connection.optString("laptop"));
            }catch(Exception error){state=failure(app,error);}
            String result=state;
            MAIN.post(()->{checking=false;publish(result);});
        },"assistant-status").start();
    }

    private static void publish(String state){
        cached=state;cachedAt=SystemClock.elapsedRealtime();
        for(AppUi.StatusChip chip:new ArrayList<>(chips))if(chip.isAttachedToWindow())show(chip,"Worker",state);
    }
}
