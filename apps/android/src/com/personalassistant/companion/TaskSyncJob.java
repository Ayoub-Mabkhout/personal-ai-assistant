package com.personalassistant.companion;
import android.app.job.*;
import android.content.*;
import java.util.concurrent.*;

/** Recovery jobs supplement event push; they are not the push delivery mechanism. */
public class TaskSyncJob extends JobService {
    static final ExecutorService executor=Executors.newSingleThreadExecutor();
    static void schedule(Context c,boolean periodic){
        JobInfo.Builder job=new JobInfo.Builder(periodic?218:219,new ComponentName(c,TaskSyncJob.class)).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY);
        if(periodic)job.setPeriodic(1800000).setPersisted(true);else job.setMinimumLatency(0).setPersisted(true);
        ((JobScheduler)c.getSystemService(Context.JOB_SCHEDULER_SERVICE)).schedule(job.build());
    }
    @Override public boolean onStartJob(JobParameters p){if(Cloud.prefs(this).getBoolean("push_signing_out",false)||Cloud.prefs(this).getString("token","").isEmpty())return false;executor.execute(()->{boolean retry=false;try{NativeTasks.sync(this);retry=Cloud.prefs(this).getBoolean("push_more",false);}catch(Exception error){retry=true;Cloud.prefs(this).edit().putString("task_sync_error",error.getMessage()).commit();}if(Features.background(this))retry=true;try{Cloud.syncPreferences(this);}catch(Exception optionalSettingsUnavailable){}jobFinished(p,retry);});return true;}
    @Override public boolean onStopJob(JobParameters p){return true;}
}
