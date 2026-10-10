package com.personalassistant.companion;
import android.app.job.*;
import android.content.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

/** Background download of owner-requested files; push hints and periodic event syncs only schedule it. */
public class FileDropJob extends JobService {
    static final ExecutorService executor=Executors.newSingleThreadExecutor();
    static final int ID=228;
    /** Started jobs whose pass has not ended. The scheduler's pending job is no guide: it is also the one waiting out a failure's backoff. */
    static final AtomicInteger running=new AtomicInteger();
    /** A new file event replaces a job waiting out an earlier failure's backoff; a recovery check only schedules when none is waiting. */
    static void schedule(Context c,boolean hint){
        JobScheduler scheduler=(JobScheduler)c.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        // Rescheduling a running job would stop its download; the running pass re-lists drops that arrive meanwhile.
        if(running.get()>0||!hint&&scheduler.getPendingJob(ID)!=null)return;
        scheduler.schedule(new JobInfo.Builder(ID,new ComponentName(c,FileDropJob.class)).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setMinimumLatency(0).setPersisted(true).build());
    }
    @Override public boolean onStartJob(JobParameters p){
        if(Cloud.prefs(this).getBoolean("push_signing_out",false)||Cloud.prefs(this).getString("token","").isEmpty())return false;
        running.incrementAndGet();
        executor.execute(()->{
            boolean retry=true;try{retry=FileDrops.sync(this);}catch(Exception error){Cloud.prefs(this).edit().putString("file_drop_status","File download will retry · "+error.getMessage()).commit();}finally{running.decrementAndGet();}
            jobFinished(p,retry);
            // An event after the last listing found this job running and scheduled nothing; its drop is due, so run again now.
            if(!retry&&Cloud.prefs(this).getBoolean("file_drops_due",false))schedule(this,true);
        });
        return true;
    }
    @Override public boolean onStopJob(JobParameters p){FileDrops.due(this);return true;}
}
