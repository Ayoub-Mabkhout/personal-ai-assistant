package com.personalassistant.companion;
import android.app.job.*;
import android.content.*;
public class VoiceRetryJob extends JobService {
    static void schedule(Context c){((JobScheduler)c.getSystemService(Context.JOB_SCHEDULER_SERVICE)).schedule(new JobInfo.Builder(216,new ComponentName(c,VoiceRetryJob.class)).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setMinimumLatency(1000).setBackoffCriteria(10000,JobInfo.BACKOFF_POLICY_EXPONENTIAL).setPersisted(true).build());}
    @Override public boolean onStartJob(JobParameters p){VoiceOutbox.executor.execute(()->{boolean retry=false;try{if(Cloud.prefs(this).getBoolean("voice_listening_test",false))retry=true;else VoiceOutbox.flush(this,null);}catch(Exception e){retry=true;}jobFinished(p,retry);});return true;}
    @Override public boolean onStopJob(JobParameters p){return true;}
}
