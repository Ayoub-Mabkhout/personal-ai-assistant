package com.personalassistant.companion;
import android.content.Context;
import java.util.concurrent.*;
import org.json.*;

/** Actual NativeTasks under blocked/lost-ack transport and concurrent UI writes. */
public class NativeTaskQueueHarness {
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception{
        Context c=new Context();
        NativeTasks.enqueueFollowup(c,"original-task-001","First instruction");
        Cloud.block=true;
        ExecutorService worker=Executors.newSingleThreadExecutor();Future<?> sending=worker.submit(()->{try{NativeTasks.flush(c);}catch(Exception e){throw new RuntimeException(e);}});
        check(Cloud.entered.await(2,TimeUnit.SECONDS),"transport did not block");
        long start=System.nanoTime();String second=NativeTasks.enqueueFollowup(c,"original-task-001","New instruction while offline");
        double writeMs=(System.nanoTime()-start)/1e6;
        check(writeMs<300,"network held local outbox lock");
        Cloud.release.countDown();sending.get(3,TimeUnit.SECONDS);
        check(NativeTasks.pending(c).length()==0,"acknowledgement lost concurrent append");
        check(Cloud.executions==2,"expected two distinct followups");
        String lost=NativeTasks.enqueueFollowup(c,"original-task-001","Lost acknowledgement");Cloud.dropAck=true;
        try{NativeTasks.flush(c);throw new AssertionError("lost ack not simulated");}catch(java.io.IOException expected){}
        check(NativeTasks.pending(c).getJSONObject(0).getString("id").equals(lost),"lost ack changed ID");
        NativeTasks.flush(c);
        check(Cloud.executions==3,"lost ack repeated remote execution");
        check(NativeTasks.pending(c).length()==0,"retry did not clear receipt");
        NativeTasks.enqueueFollowupWithId(c,"original-task-001","Notification reply","reply-stable-id");
        NativeTasks.enqueueFollowupWithId(c,"original-task-001","Notification reply","reply-stable-id");
        check(NativeTasks.pending(c).length()==1,"repeated notification event duplicated outbox");
        NativeTasks.flush(c);
        String invalid=NativeTasks.enqueueFollowup(c,"missing-task-001","Needs review");Cloud.rejectId=invalid;
        NativeTasks.enqueueFollowup(c,"original-task-001","Continue valid thread");
        try{NativeTasks.flush(c);throw new AssertionError("rejection absent");}catch(Exception expected){}
        check(NativeTasks.pending(c).getJSONObject(0).optString("state").equals("needs_review"),"hard rejection repeated automatically");
        NativeTasks.flush(c);check(NativeTasks.pending(c).length()==1,"rejected item blocked later instruction");
        NativeTasks.enqueueFollowup(c,"original-task-001","Different server must not receive this");int before=Cloud.executions;
        Cloud.prefs(c).edit().putString("origin","https://different.example").commit();NativeTasks.flush(c);
        check(Cloud.executions==before,"follow-up replayed to another server");
        worker.shutdownNow();
        JSONObject report=new JSONObject().put("passed",true).put("local_append_ms",writeMs).put("lost_ack_same_id",true)
            .put("distinct_executions",Cloud.executions).put("concurrent_append_preserved",true).put("notification_retry_dedup",true)
            .put("hard_rejection_review",true).put("paid_calls",0);
        System.out.println(report.toString());
    }
}
