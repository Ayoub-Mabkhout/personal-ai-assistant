package com.personalassistant.companion;

import java.util.*;

/** Drives the pure specialist chat rules: immediate local bubbles, streaming into one reply slot, retry IDs and chip wording. */
public final class SpecialistChatHarness {
    static void equal(Object expected,Object actual){if(!Objects.equals(expected,actual))throw new AssertionError(expected+" != "+actual);}
    static void check(boolean value,String what){if(!value)throw new AssertionError(what);}
    static List<String> keys(List<SpecialistThread.Row> rows){List<String> out=new ArrayList<>();for(SpecialistThread.Row r:rows)out.add(r.key+"="+r.kind);return out;}
    static SpecialistThread.Row row(List<SpecialistThread.Row> rows,String key){for(SpecialistThread.Row r:rows)if(r.key.equals(key))return r;throw new AssertionError("missing "+key);}

    public static void main(String[] args){
        thread();
        retry();
        readiness();
        System.out.println("Specialist chats passed");
    }

    static void thread(){
        SpecialistThread t=new SpecialistThread();
        equal(0,t.rows("Coach",true).size());
        // Sending: the user's bubble is there before any network answer, with no reply slot yet.
        t.local("m1","How heavy?",100,SpecialistThread.SENDING,"");
        List<SpecialistThread.Row> rows=t.rows("Coach",true);
        equal(Arrays.asList("m1|user=user"),keys(rows));equal("Sending…",rows.get(0).label);equal(0.0,rows.get(0).time);check(t.waiting(),"sending waits");
        // Accepted by the server but not listed yet: "Sent" plus a queued reply slot.
        t.local("m1","How heavy?",0,SpecialistThread.ACCEPTED,"");
        rows=t.rows("Coach",false);
        equal(Arrays.asList("m1|user=user","m1|reply=status"),keys(rows));equal("Sent",rows.get(0).note);equal(100.0,rows.get(0).time);
        check(row(rows,"m1|reply").text.contains("back online"),"offline queue wording");
        // The server row replaces the local one by ID; the same reply key moves through thinking, partial and answer.
        t.replace(Arrays.asList(new SpecialistThread.Message("m1","How heavy?",101).state("running")));
        rows=t.rows("Coach",true);equal(2,rows.size());equal("You",rows.get(0).label);equal("",rows.get(0).note);equal("Coach is thinking…",row(rows,"m1|reply").text);
        t.replace(Arrays.asList(new SpecialistThread.Message("m1","How heavy?",101).state("running").partial("Start with")));
        rows=t.rows("Coach",true);equal("partial",row(rows,"m1|reply").kind);equal("Start with",row(rows,"m1|reply").text);equal("Coach · Answering…",row(rows,"m1|reply").label);
        t.replace(Arrays.asList(new SpecialistThread.Message("m1","How heavy?",101).state("running").partial("Start with 60 kg")));
        equal("Start with 60 kg",row(t.rows("Coach",true),"m1|reply").text);
        t.replace(Arrays.asList(new SpecialistThread.Message("m1","How heavy?",101).state("completed").answer("Start with **60 kg**.",130)));
        rows=t.rows("Coach",true);SpecialistThread.Row answer=row(rows,"m1|reply");
        equal("answer",answer.kind);equal("Coach",answer.label);equal(130.0,answer.time);check(!t.waiting(),"answered stops waiting");
        // A late local update for a listed message cannot resurrect a duplicate bubble.
        t.local("m1","How heavy?",0,SpecialistThread.UNSENT,"x");equal(2,t.rows("Coach",true).size());
        // Unsent: kept on the phone with Retry/Edit and a reason; it does not make the screen poll faster.
        t.local("m2","And sets?",140,SpecialistThread.UNSENT,SpecialistThread.problem(0));
        rows=t.rows("Coach",true);SpecialistThread.Row unsent=row(rows,"m2|user");
        check(unsent.retry,"unsent offers retry");equal("Not sent",unsent.label);check(unsent.note.contains("No connection"),"reason shown");check(!t.waiting(),"unsent does not poll fast");
        equal(Arrays.asList("m1|user=user","m1|reply=answer","m2|user=user"),keys(rows));
        // Local messages stay after listed ones even with a skewed phone clock; Money pages accumulate with put().
        t.put(new SpecialistThread.Message("m0","Earlier",50).answer("Old answer",60));
        equal(Arrays.asList("m0|user=user","m0|reply=answer","m1|user=user","m1|reply=answer","m2|user=user"),keys(t.rows("Money specialist",true)));
        t.put(new SpecialistThread.Message("m2","And sets?",141).state("queued"));
        equal(Arrays.asList("m0|user=user","m0|reply=answer","m1|user=user","m1|reply=answer","m2|user=user","m2|reply=status"),keys(t.rows("Money specialist",true)));
        check(t.waiting(),"queued server message waits");
        // A failed answer stays in its slot with a warning instead of an endless "thinking".
        t.put(new SpecialistThread.Message("m2","And sets?",141).state("failed"));
        equal("Money specialist couldn't answer. Ask again.",row(t.rows("Money specialist",true),"m2|reply").text);check(!t.waiting(),"failed stops waiting");
        // Forget hides an edited unsent message without touching listed ones.
        t.local("m3","draft",150,SpecialistThread.UNSENT,"");t.forget("m3");t.forget("m1");equal(6,t.rows("Coach",true).size());
    }

    static void retry(){
        equal("saved",SpecialistThread.retryId("hi\n[]","saved","hi\n[]","fresh"));
        equal("fresh",SpecialistThread.retryId("hi\n[]","saved","hi again\n[]","fresh"));
        equal("fresh",SpecialistThread.retryId("","", "hi\n[]","fresh"));
        check(SpecialistThread.retryable(0)&&SpecialistThread.retryable(503)&&SpecialistThread.retryable(429),"transient failures retry");
        check(!SpecialistThread.retryable(409)&&!SpecialistThread.retryable(422),"refusals need an edit");
        check(SpecialistThread.problem(409).contains("Edit"),"conflict asks for an edit");
        check(SpecialistThread.problem(401).contains("pairing"),"401 asks for pairing");
    }

    static void readiness(){
        equal("Worker · Checking…",WorkerReadiness.label("Worker",""));equal("neutral",WorkerReadiness.tone(""));
        equal("Worker online",WorkerReadiness.label("Worker","ready"));equal("success",WorkerReadiness.tone("ready"));
        equal("Coach online",WorkerReadiness.label("Coach","busy"));
        equal("Worker · Usage limit",WorkerReadiness.label("Worker","blocked"));equal("warning",WorkerReadiness.tone("blocked"));
        check(WorkerReadiness.description("Worker","blocked").contains("usage limit"),"blocked explains the quota");
        equal("Worker offline",WorkerReadiness.label("Worker","unavailable"));equal("warning",WorkerReadiness.tone("unavailable"));
        equal("Worker · Not paired",WorkerReadiness.label("Worker","unpaired"));equal("neutral",WorkerReadiness.tone("unpaired"));
        equal("Worker · Phone offline",WorkerReadiness.label("Worker","no_network"));
        equal("Worker · Server unreachable",WorkerReadiness.label("Worker","unreachable"));
        equal("Worker · No response",WorkerReadiness.label("Worker","timeout"));
        equal("Money specialist offline",WorkerReadiness.label("Money specialist","something-new"));
        // Every non-empty state resolves: only an empty state reads "Checking…".
        for(String s:new String[]{"ready","busy","blocked","unavailable","unpaired","no_network","unreachable","timeout","x"})check(!WorkerReadiness.label("W",s).contains("Checking"),s);
        // voice/status: assistant lane first, then the VPS server worker, then the laptop.
        equal("blocked",WorkerReadiness.pick("blocked","ready","ready"));
        equal("ready",WorkerReadiness.pick("","ready","unavailable"));
        equal("unavailable",WorkerReadiness.pick(null,"","unavailable"));
        equal("unavailable",WorkerReadiness.pick(null,null,null));
        equal("unpaired",WorkerReadiness.failure(401));equal("unreachable",WorkerReadiness.failure(502));
        check(WorkerReadiness.TIMEOUT_MS<=15000,"timeout resolves before the next periodic check");
    }
}
