package com.personalassistant.companion;
import android.app.*;
import android.app.job.*;
import android.content.*;
import android.os.Build;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;

/** Drives the real FileDrops, FileDropJob and NativeNotifications against the framework shims in tests/test_android_file_drops.py,
 *  an in-memory relay and an in-memory HTTPS download handler: no network, phone or paid service. Each mode prints one ASCII JSON line. */
public class FileDropsHarness {
    static final Relay relay=new Relay();
    static final String ORIGIN="https://relay.example.test";

    /** The relay's phone API: a page of waiting drops, receipts, and the native event journal. */
    static final class Relay implements Cloud.Server {
        final Map<String,JSONObject> ready=new LinkedHashMap<>();final Map<String,byte[]> bytes=new HashMap<>();final Map<String,Integer> failures=new HashMap<>();
        JSONArray events=new JSONArray();int page=50,lists,receipts;boolean down;Runnable onList;
        void add(String id,String name,String mime,byte[] data)throws Exception{
            ready.put(id,new JSONObject().put("id",id).put("name",name).put("mime",mime).put("size",data.length).put("sha256",Updates.hex(MessageDigest.getInstance("SHA-256").digest(data))).put("note",""));bytes.put(id,data);
        }
        public synchronized Object call(String path,JSONObject body)throws Exception{
            if(path.equals("files")){
                if(down)throw new IOException("offline");lists++;if(onList!=null)onList.run();
                JSONArray items=new JSONArray();for(JSONObject item:ready.values())if(items.length()<page)items.put(item);return new JSONObject().put("items",items);
            }
            if(path.startsWith("files/")&&path.endsWith("/receipt")){String id=path.substring(6,path.length()-8);receipts++;if(ready.remove(id)==null)throw new Cloud.HttpError(404,"File not found.");return new JSONObject().put("id",id).put("state","delivered");}
            if(path.startsWith("events?cursor=")){
                long cursor=Long.parseLong(path.substring(14));JSONArray items=new JSONArray();
                for(int i=0;i<events.length();i++)if(events.getJSONObject(i).getLong("sequence")>cursor)items.put(events.getJSONObject(i));
                return new JSONObject().put("items",items).put("more",false);
            }
            if(path.equals("events/receipt"))return new JSONObject().put("received",body.getLong("cursor"));
            throw new Cloud.HttpError(404,"Not Found");
        }
    }

    /** GET /groceries/v1/mobile/files/{id} served from the relay's memory. */
    static final class Download extends HttpURLConnection {
        Download(URL url){super(url);}
        String id(){String path=url.getPath();return path.substring(path.lastIndexOf('/')+1);}
        @Override public int getResponseCode(){synchronized(relay){Integer failure=relay.failures.get(id());return failure!=null?failure:relay.ready.containsKey(id())?200:410;}}
        @Override public InputStream getInputStream(){return new ByteArrayInputStream(relay.bytes.get(id()));}
        @Override public void connect(){}
        @Override public void disconnect(){}
        @Override public boolean usingProxy(){return false;}
    }

    static String ascii(String text){StringBuilder b=new StringBuilder();for(char ch:text.toCharArray())if(ch<0x7f)b.append(ch);else b.append(String.format("\\u%04x",(int)ch));return b.toString();}
    static boolean due(){return Context.prefs.getBoolean("file_drops_due",false);}
    static String intent(PendingIntent pending){
        if(pending==null)return "none";
        Intent intent=pending.intent;if(DownloadManager.ACTION_VIEW_DOWNLOADS.equals(intent.action))return "downloads";
        return Intent.ACTION_CHOOSER.equals(intent.action)?"view:"+intent.target.type:intent.action;
    }
    /** Starts the job the scheduler holds, as JobScheduler would, and waits until its pass and any follow-up scheduling are done. */
    static boolean run(FileDropJob job)throws Exception{
        JobScheduler scheduler=Context.scheduler;JobParameters p=new JobParameters();synchronized(scheduler){p.job=scheduler.pending;scheduler.executing=true;}
        if(!job.onStartJob(p))throw new AssertionError("job refused to start");
        Boolean retry=JobService.finished.poll(10,TimeUnit.SECONDS);if(retry==null)throw new AssertionError("job did not finish");
        FileDropJob.executor.submit(()->{}).get(10,TimeUnit.SECONDS);
        return retry;
    }

    public static void main(String[] args)throws Exception{
        PrintStream out=new PrintStream(new FileOutputStream(FileDescriptor.out),true,"UTF-8");
        URL.setURLStreamHandlerFactory(protocol->"https".equals(protocol)?new URLStreamHandler(){@Override protected URLConnection openConnection(URL url){return new Download(url);}}:null);
        Context.root=new File(args[1]);Cloud.server=relay;Context c=new Context();
        Context.prefs.edit().putString("origin",ORIGIN).putString("token","fixture").commit();
        JSONObject report=new JSONObject();
        switch(args[0]){
            case "names":{
                // Each input line is a JSON string; each output line is [safe name, its UTF-8 bytes].
                BufferedReader in=new BufferedReader(new InputStreamReader(System.in,StandardCharsets.UTF_8));String line;
                while((line=in.readLine())!=null){String name=FileDrops.safeName((String)new JSONTokener(line).nextValue());out.println(ascii(new JSONArray().put(name).put(FileDrops.utf8(name)).toString()));}
                return;
            }
            case "paging":{
                Build.VERSION.SDK_INT=29;
                for(int n=0;n<120;n++)relay.add(String.format("drop-%04d",n),"report-"+n+".pdf","application/pdf",("report "+n).getBytes(StandardCharsets.UTF_8));
                boolean more=FileDrops.sync(c);
                report.put("more",more).put("delivered",relay.receipts).put("waiting",relay.ready.size()).put("lists",relay.lists).put("saved",Context.resolver.bytes.size())
                    .put("cards",Context.notifications.posted.size()).put("due",due()).put("listed",Context.prefs.getLong("file_drops_listed",0)>0);
                break;
            }
            case "failing":{
                Build.VERSION.SDK_INT=29;
                for(int n=0;n<60;n++)relay.add(String.format("drop-%04d",n),"photo-"+n+".png","image/png",("photo "+n).getBytes(StandardCharsets.UTF_8));
                relay.failures.put("drop-0003",500);boolean threw=false;
                try{FileDrops.sync(c);}catch(Exception expected){threw=true;}
                report.put("threw",threw).put("delivered",relay.receipts).put("waiting",relay.ready.size()).put("due",due()).put("listed",Context.prefs.getLong("file_drops_listed",0)>0);
                break;
            }
            case "stuck":{
                Build.VERSION.SDK_INT=29;
                for(int n=0;n<3;n++)relay.add(String.format("drop-%04d",n),"page-"+n+".txt","text/plain",("page "+n).getBytes(StandardCharsets.UTF_8));
                // Listed as ready, but its bytes are gone: the download answers 410 and no receipt is sent.
                relay.failures.put("drop-0000",410);
                boolean more=FileDrops.sync(c);
                report.put("more",more).put("lists",relay.lists).put("delivered",relay.receipts).put("waiting",relay.ready.size());
                break;
            }
            case "missing":{
                // A server without file transfer answers the list with 404: nothing waits and the check is recorded.
                Cloud.server=(path,body)->{throw new Cloud.HttpError(404,"Not Found");};
                report.put("more",FileDrops.sync(c)).put("due",due()).put("listed",Context.prefs.getLong("file_drops_listed",0)>0);
                break;
            }
            case "save":{
                String cjk=new String(new char[150]).replace('\0','\u6587');
                Object[][] cases={
                    {29,"holiday.jpg",FileDrops.APK},{29,"photo.png","image/png"},{29,"setup.apk","application/octet-stream"},{29,"notes","text/plain"},
                    {28,"setup.apk","image/png"},{28,"invoice\u202egnp.apk","image/png"},{28,cjk+".pdf","application/pdf"},{28,"scan.png","image/png"},{28,"scan.png","image/png"},
                };
                JSONArray results=new JSONArray();File folder=c.getExternalFilesDir("Download");
                for(int n=0;n<cases.length;n++){
                    Build.VERSION.SDK_INT=(Integer)cases[n][0];String id=String.format("drop-%04d",n);Set<String> before=new HashSet<>(Arrays.asList(folder.list()));
                    relay.add(id,(String)cases[n][1],(String)cases[n][2],("file "+n).getBytes(StandardCharsets.UTF_8));FileDrops.sync(c);
                    Notification card=Context.notifications.posted.get("file-"+id);JSONArray actions=new JSONArray();
                    for(Notification.Action action:card.actions)actions.put(action.title.toString());
                    Set<String> added=new HashSet<>(Arrays.asList(folder.list()));added.removeAll(before);
                    String saved=Build.VERSION.SDK_INT>=29?Context.resolver.lastName:added.size()==1?added.iterator().next():"";
                    results.put(new JSONObject().put("sdk",cases[n][0]).put("title",card.title.toString()).put("text",card.text.toString()).put("open",intent(card.contentIntent)).put("actions",actions)
                        .put("saved",saved).put("saved_bytes",saved.getBytes(StandardCharsets.UTF_8).length).put("delivered",!relay.ready.containsKey(id)));
                }
                report.put("cases",results);
                break;
            }
            case "schedule":{
                Build.VERSION.SDK_INT=29;JobScheduler scheduler=Context.scheduler;FileDropJob job=new FileDropJob();
                // A failed pass leaves the job waiting out its backoff.
                FileDropJob.schedule(c,true);relay.down=true;
                report.put("failure_retries",run(job)).put("backoff_pending",scheduler.pending!=null).put("due_after_failure",due());
                int before=scheduler.scheduled;FileDropJob.schedule(c,false);
                report.put("recovery_keeps_backoff",scheduler.scheduled==before);
                FileDropJob.schedule(c,true);
                report.put("new_event_replaces_backoff",scheduler.scheduled==before+1&&scheduler.pending!=null);
                // While a pass runs, a new event never restarts the job. One that lands after the pass's last listing runs it again.
                relay.down=false;relay.add("drop-0001","a.pdf","application/pdf","a".getBytes(StandardCharsets.UTF_8));
                final int[] during={-1};final boolean[] late={false};
                relay.onList=()->{if(during[0]<0){int was=scheduler.scheduled;FileDropJob.schedule(c,true);during[0]=scheduler.scheduled-was;}};
                SharedPreferences.hook=pending->{if(pending.containsKey("file_drops_listed")&&!late[0]){late[0]=true;FileDrops.due(c);FileDropJob.schedule(c,true);}};
                int start=scheduler.scheduled;boolean retry=run(job);SharedPreferences.hook=null;
                report.put("event_while_running_ignored",during[0]==0&&scheduler.stopped==0).put("pass_succeeded",!retry).put("delivered",relay.receipts)
                    .put("late_event_runs_again",late[0]&&scheduler.scheduled==start+1&&scheduler.pending!=null);
                break;
            }
            case "events":{
                Build.VERSION.SDK_INT=29;JobScheduler scheduler=Context.scheduler;double now=System.currentTimeMillis()/1000.0;
                // The file event expired a day ago; its drop is kept for days longer.
                relay.events.put(new JSONObject().put("sequence",1).put("id","event-file-1").put("created",now-172800).put("expires",now-86400)
                    .put("payload",new JSONObject().put("type","file").put("tag","file-drop-0001").put("file_id","drop-0001").put("title","File ready: a.pdf").put("message","a.pdf")));
                Context.prefs.edit().putLong("file_drops_listed",System.currentTimeMillis()).commit();
                scheduler.pending=new JobInfo();
                NativeNotifications.sync(c);
                report.put("expired_file_event_marks_due",due()).put("new_event_replaces_backoff",scheduler.scheduled==1).put("cursor",Context.prefs.getLong("push_cursor",0));
                NativeNotifications.sync(c);
                report.put("recovery_keeps_backoff",scheduler.scheduled==1);
                Context.prefs.edit().putBoolean("file_drops_due",false).putLong("file_drops_listed",System.currentTimeMillis()-3600000L).commit();scheduler.pending=null;
                NativeNotifications.sync(c);
                report.put("recent_check_stays_idle",scheduler.scheduled==1);
                Context.prefs.edit().putLong("file_drops_listed",System.currentTimeMillis()-7*3600000L).commit();
                NativeNotifications.sync(c);
                report.put("old_check_runs_again",scheduler.scheduled==2);
                break;
            }
            default:throw new IllegalArgumentException(args[0]);
        }
        out.println(ascii(report.toString()));
        FileDropJob.executor.shutdownNow();
    }
}
