package com.personalassistant.companion;
import android.app.job.*;
import android.content.*;
import java.util.concurrent.*;

public class SyncJob extends JobService {
    static final ExecutorService executor=Executors.newSingleThreadExecutor();
    static void schedule(Context c,boolean periodic){
        JobInfo.Builder b=new JobInfo.Builder(periodic?210:211,new ComponentName(c,SyncJob.class)).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY);
        if(periodic)b.setPeriodic(1800000).setPersisted(true);else b.setMinimumLatency(0);
        ((JobScheduler)c.getSystemService(Context.JOB_SCHEDULER_SERVICE)).schedule(b.build());
    }
    static void scheduleUpdate(Context c){
        JobInfo.Builder b=new JobInfo.Builder(212,new ComponentName(c,SyncJob.class)).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setMinimumLatency(0).setPersisted(true);
        ((JobScheduler)c.getSystemService(Context.JOB_SCHEDULER_SERVICE)).schedule(b.build());
    }
    @Override public boolean onStartJob(JobParameters p){executor.execute(()->{
        boolean retry=false;BatterySampler.record(this);
        if(p.getJobId()!=212)try{Cloud.sync(this);}catch(Exception e){retry=true;Cloud.prefs(this).edit().putString("status",e.getMessage()).commit();ShoppingWidget.update(this);}
        if(p.getJobId()==212||Cloud.prefs(this).getBoolean("update_pending",false))try{Updates.check(this,true);}catch(Exception e){retry=true;Cloud.prefs(this).edit().putString("update_status","Update check unavailable · will retry").commit();}jobFinished(p,retry);
    });return true;}
    @Override public boolean onStopJob(JobParameters p){return true;}
}
