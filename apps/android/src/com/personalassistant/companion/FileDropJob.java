package com.personalassistant.companion;
import android.app.job.*;
import android.content.*;
import java.util.concurrent.*;

/** Background download of owner-requested files; push hints and periodic event syncs only schedule it. */
public class FileDropJob extends JobService {
    static final ExecutorService executor=Executors.newSingleThreadExecutor();
    static final int ID=228;
    static void schedule(Context c){
        JobScheduler scheduler=(JobScheduler)c.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        // Rescheduling a running job would stop its download; the running pass re-lists drops that arrive meanwhile.
        if(scheduler.getPendingJob(ID)!=null)return;
        scheduler.schedule(new JobInfo.Builder(ID,new ComponentName(c,FileDropJob.class)).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setMinimumLatency(0).setPersisted(true).build());
    }
    @Override public boolean onStartJob(JobParameters p){
        if(Cloud.prefs(this).getBoolean("push_signing_out",false)||Cloud.prefs(this).getString("token","").isEmpty())return false;
        executor.execute(()->{boolean retry=false;try{FileDrops.sync(this);}catch(Exception error){retry=true;Cloud.prefs(this).edit().putString("file_drop_status","File download will retry · "+error.getMessage()).commit();}jobFinished(p,retry);});
        return true;
    }
    @Override public boolean onStopJob(JobParameters p){FileDrops.due(this);return true;}
}
