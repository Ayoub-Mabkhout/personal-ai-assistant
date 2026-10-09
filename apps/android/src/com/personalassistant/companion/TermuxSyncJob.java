package com.personalassistant.companion;
import android.app.job.*;
import android.content.*;
import java.util.concurrent.*;
public class TermuxSyncJob extends JobService {
    static final ExecutorService executor=Executors.newSingleThreadExecutor();
    static void schedule(Context c,boolean periodic){JobInfo.Builder b=new JobInfo.Builder(periodic?224:225,new ComponentName(c,TermuxSyncJob.class)).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setPersisted(true);if(periodic)b.setPeriodic(900000);else b.setMinimumLatency(0);((JobScheduler)c.getSystemService(Context.JOB_SCHEDULER_SERVICE)).schedule(b.build());}
    @Override public boolean onStartJob(JobParameters p){executor.execute(()->{boolean retry=false;try{TermuxBridge.sync(this);}catch(Exception e){retry=true;Cloud.prefs(this).edit().putString("termux_status","Phone command sync pending: "+e.getMessage()).commit();}jobFinished(p,retry);});return true;}
    @Override public boolean onStopJob(JobParameters p){return true;}
}
