package com.personalassistant.companion;

import android.content.*;
import java.util.*;
import java.util.concurrent.*;

/**
 * Drives the real TaskVoice against the in-memory shims of tests/test_task_voice.py: no network, phone, microphone or paid
 * service. Prints one JSON object describing each scenario.
 */
public final class TaskVoiceHarness {
    /** Records what TaskVoice asks of VoiceService; released() can end the conversation or start a newer turn. */
    static final class Recorder implements TaskVoice.Host {
        final String task,onRelease;volatile boolean current=true,talking=true;volatile int pollsAtRelease=-1;volatile Thread worker;
        final List<String> events=Collections.synchronizedList(new ArrayList<String>());
        Recorder(String task,String onRelease){this.task=task;this.onRelease=onRelease;}
        public boolean current(){return current;}
        public boolean talking(){return current&&talking;}
        public void state(String message){worker=Thread.currentThread();events.add("state:"+message);}
        public void sent(){events.add("sent");}
        public void released(){pollsAtRelease=NativeTasks.polls(task);events.add("released");if(onRelease.equals("ended"))talking=false;else if(onRelease.equals("newer"))current=false;}
        public void reply(String text,boolean end){events.add((end?"end:":"reply:")+text);}
        public void done(String message){events.add("done:"+message);}
    }

    /** ASCII JSON, so the report survives any console code page. */
    static String quote(String s){StringBuilder b=new StringBuilder("\"");for(char ch:s.toCharArray()){if(ch=='"'||ch=='\\')b.append('\\').append(ch);else if(ch<0x20||ch>0x7e)b.append(String.format("\\u%04x",(int)ch));else b.append(ch);}return b.append('"').toString();}
    static String json(Object v){
        if(v instanceof String)return quote((String)v);
        if(v instanceof Map){StringBuilder b=new StringBuilder("{");for(Map.Entry<?,?> e:((Map<?,?>)v).entrySet()){if(b.length()>1)b.append(',');b.append(quote(String.valueOf(e.getKey()))).append(':').append(json(e.getValue()));}return b.append('}').toString();}
        if(v instanceof Collection){StringBuilder b=new StringBuilder("[");for(Object item:(Collection<?>)v){if(b.length()>1)b.append(',');b.append(json(item));}return b.append(']').toString();}
        return String.valueOf(v);
    }

    static Set<Thread> workers(){Set<Thread> found=new HashSet<Thread>();for(Thread t:Thread.getAllStackTraces().keySet())if(t.getName().equals("assistant-task-voice"))found.add(t);return found;}

    public static void main(String[] args)throws Exception{
        Context c=new Context();Map<String,Object> result=new LinkedHashMap<String,Object>();

        // Spoken follow-ups: the answer; a conversation ended, or a newer turn begun, once the microphone is free; a newer turn
        // begun while the answer is still being polled for; and a follow-up kept offline.
        String[][] turns={{"answer","none"},{"ended","ended"},{"newer","newer"},{"late","none"},{"offline","none"}};
        Map<String,Recorder> hosts=new LinkedHashMap<String,Recorder>();NativeTasks.offline.add("offline");NativeTasks.running.add("late");
        long started=System.currentTimeMillis();
        for(String[] turn:turns){Recorder host=new Recorder(turn[0],turn[1]);hosts.put(turn[0],host);TaskVoice.turn(c,new short[3200],turn[0],false,false,host);}
        Recorder late=hosts.get("late");long until=System.currentTimeMillis()+20000;
        while(NativeTasks.polls("late")<1&&System.currentTimeMillis()<until)Thread.sleep(20);
        long flipped=System.currentTimeMillis();late.current=false;Thread lateWorker=late.worker;if(lateWorker!=null)lateWorker.join(5000);
        result.put("late_stop_ms",System.currentTimeMillis()-flipped);
        for(Thread t:workers())t.join(20000);
        boolean alive=false;for(Thread t:workers())alive|=t.isAlive();
        for(Recorder host:hosts.values()){Map<String,Object> row=new LinkedHashMap<String,Object>();row.put("events",new ArrayList<String>(host.events));row.put("polls_at_release",host.pollsAtRelease);row.put("polls",NativeTasks.polls(host.task));result.put(host.task,row);}
        result.put("workers_alive",alive);result.put("turns_ms",System.currentTimeMillis()-started);

        // Stop dictation names its own action, never the conversation's end.
        Intent finish=TaskVoice.finish(c,"task-1");
        result.put("finish_action",finish.getAction());result.put("finish_task",finish.getStringExtra("task_id"));result.put("finish_rejects_bad_ids",TaskVoice.finish(c,"bad id/..")==null);

        // The screen's main-thread take must not wait for a disk write, nor for one that deliver() makes under the lock.
        SharedPreferences.commitDelay=1500;SharedPreferences.commits.clear();
        Thread writer=new Thread(()->TaskVoice.deliver(c,"lock","Check the totals"));long deliverStart=System.currentTimeMillis();writer.start();Thread.sleep(50);
        long t0=System.currentTimeMillis();String taken=TaskVoice.take(c,"lock");long takeMs=System.currentTimeMillis()-t0;writer.join();long deliverMs=System.currentTimeMillis()-deliverStart;
        if(taken.isEmpty())taken=TaskVoice.take(c,"lock");
        String again=TaskVoice.take(c,"lock");
        Thread noter=new Thread(()->TaskVoice.note(c,"lock","Added to your draft"));noter.start();Thread.sleep(50);
        t0=System.currentTimeMillis();String note=TaskVoice.takeNote(c,"lock");long noteMs=System.currentTimeMillis()-t0;noter.join();
        if(note.isEmpty())note=TaskVoice.takeNote(c,"lock");
        Map<String,Object> locks=new LinkedHashMap<String,Object>();locks.put("taken",taken);locks.put("again",again);locks.put("note",note);locks.put("note_again",TaskVoice.takeNote(c,"lock"));locks.put("take_ms",takeMs);locks.put("note_ms",noteMs);locks.put("deliver_ms",deliverMs);locks.put("commits",new ArrayList<String>(SharedPreferences.commits));
        SharedPreferences.commitDelay=0;

        // Read-and-remove stays atomic: concurrent deliveries and takes neither lose nor repeat a word.
        final int words=400;ExecutorService pool=Executors.newFixedThreadPool(4);List<Future<?>> jobs=new ArrayList<Future<?>>();
        for(int i=0;i<words;i++){final int n=i;jobs.add(pool.submit(()->TaskVoice.deliver(c,"race","w"+n)));}
        StringBuilder drafted=new StringBuilder();while(true){boolean busy=false;for(Future<?> job:jobs)busy|=!job.isDone();String part=TaskVoice.take(c,"race");if(!part.isEmpty())drafted.append(' ').append(part);if(!busy&&part.isEmpty())break;}
        pool.shutdown();
        List<String> seen=new ArrayList<String>(Arrays.asList(drafted.toString().trim().split(" ")));Set<String> unique=new HashSet<String>(seen);
        locks.put("race_words",seen.size());locks.put("race_unique",unique.size());
        result.put("locks",locks);
        System.out.println(json(result));
    }
}
