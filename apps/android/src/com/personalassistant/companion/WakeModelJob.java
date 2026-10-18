package com.personalassistant.companion;

import android.app.*;
import android.app.job.*;
import android.content.*;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.zip.*;
import org.json.*;

/** Fetches the "Hey Chat" model once, outside the APK. The archive and every file are checked against the
 *  SHA-256 values the APK ships, then unpacked into the same folder the detector already uses. */
public final class WakeModelJob extends JobService {
    static final int JOB=4710;
    private Thread worker;

    static void schedule(Context c){
        JobScheduler jobs=c.getSystemService(JobScheduler.class);if(jobs==null||jobs.getPendingJob(JOB)!=null)return;
        jobs.schedule(new JobInfo.Builder(JOB,new ComponentName(c,WakeModelJob.class)).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
            .setBackoffCriteria(60_000,JobInfo.BACKOFF_POLICY_EXPONENTIAL).setPersisted(true).build());
        status(c,"Downloading the Hey Chat model…");
    }
    static void status(Context c,String text){Cloud.prefs(c).edit().putString("wake_model_status",text).apply();}

    @Override public boolean onStartJob(JobParameters params){
        worker=new Thread(()->{boolean retry=false;
            try{fetch(this);status(this,"");ready(this);}
            catch(InterruptedIOException stopped){retry=true;}
            catch(Exception error){retry=true;status(this,"Hey Chat model download will retry: "+(error.getMessage()==null?"network error":error.getMessage()));}
            jobFinished(params,retry);});
        worker.start();return true;
    }
    @Override public boolean onStopJob(JobParameters params){if(worker!=null)worker.interrupt();return true;}

    static void fetch(Context c)throws Exception{
        JSONObject settings=VoskWakeDetector.settings(c);String identity=settings.getString("model_identity");
        File folder=VoskWakeDetector.folder(c,identity),complete=new File(folder,".complete");if(complete.exists())return;
        String url=settings.getString("model_archive_url"),expected=settings.getString("model_archive_sha256"),root=settings.getString("model_archive_root");
        if(!url.startsWith("https://")||!expected.matches("[a-f0-9]{64}")||!root.matches("[A-Za-z0-9._-]+"))throw new IOException("Invalid wake model source");
        File archive=new File(c.getNoBackupFilesDir(),"wake-model-"+expected.substring(0,16)+".zip");
        if(!archive.isFile()||!sha256(archive).equals(expected))download(url,archive);
        if(!sha256(archive).equals(expected)){archive.delete();throw new IOException("checksum mismatch, discarded");}
        JSONArray files=settings.getJSONArray("model_files");java.util.HashMap<String,String> wanted=new java.util.HashMap<>();
        for(int i=0;i<files.length();i++){JSONObject f=files.getJSONObject(i);wanted.put(f.getString("path"),f.getString("sha256"));}
        if(!folder.isDirectory()&&!folder.mkdirs())throw new IOException("Cannot prepare the model folder");
        String base=folder.getCanonicalPath()+File.separator;int found=0;
        try(ZipInputStream zip=new ZipInputStream(new BufferedInputStream(new FileInputStream(archive)))){
            for(ZipEntry entry;(entry=zip.getNextEntry())!=null;){
                if(entry.isDirectory()||!entry.getName().startsWith(root+"/"))continue;
                String name=entry.getName().substring(root.length()+1),hash=wanted.get(name);if(hash==null)continue;
                File file=new File(folder,name);if(!file.getCanonicalPath().startsWith(base))throw new IOException("Model file outside its folder");
                if(!file.getParentFile().isDirectory()&&!file.getParentFile().mkdirs())throw new IOException("Cannot prepare a model file");
                MessageDigest digest=MessageDigest.getInstance("SHA-256");
                try(OutputStream out=new FileOutputStream(file)){byte[] b=new byte[65536];int n;while((n=zip.read(b))!=-1){if(Thread.interrupted())throw new InterruptedIOException();digest.update(b,0,n);out.write(b,0,n);}}
                if(!hex(digest.digest()).equals(hash))throw new IOException("Model file checksum mismatch");found++;
            }
        }
        if(found!=wanted.size())throw new IOException("Model archive is incomplete");
        try(OutputStream marker=new FileOutputStream(complete)){marker.write(identity.getBytes("US-ASCII"));}
        archive.delete();
    }
    /** Resumes a partial download where the server allows it. */
    static void download(String source,File archive)throws Exception{
        File part=new File(archive.getPath()+".part");long have=part.isFile()?part.length():0;
        HttpURLConnection http=(HttpURLConnection)new URL(source).openConnection();http.setConnectTimeout(20000);http.setReadTimeout(30000);http.setInstanceFollowRedirects(true);
        if(have>0)http.setRequestProperty("Range","bytes="+have+"-");
        int code=http.getResponseCode();if(code!=200&&code!=206)throw new IOException("server answered "+code);if(code==200)have=0;
        try(InputStream in=new BufferedInputStream(http.getInputStream());OutputStream out=new FileOutputStream(part,have>0)){
            byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1){if(Thread.interrupted())throw new InterruptedIOException();out.write(b,0,n);}
        }finally{http.disconnect();}
        if(!part.renameTo(archive))throw new IOException("Cannot finish the download");
    }
    /** Listening resumes on its own where Android allows it; otherwise a notification asks for one tap. */
    static void ready(Context c){
        if(!Cloud.prefs(c).getBoolean("wake_enabled",false))return;
        try{c.startForegroundService(new Intent(c,VoiceService.class));return;}catch(Exception backgroundStartBlocked){}
        NotificationManager manager=c.getSystemService(NotificationManager.class);NativeNotifications.channels(manager);
        PendingIntent open=PendingIntent.getActivity(c,JOB,new Intent(c,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),PendingIntent.FLAG_IMMUTABLE);
        try{manager.notify("wake_model",JOB,new Notification.Builder(c,"phone_actions").setSmallIcon(R.drawable.ic_stat_assistant).setColor(NativeNotifications.ACCENT)
            .setContentTitle("Hey Chat is ready").setContentText("Open Companion to resume background listening.").setContentIntent(open).setAutoCancel(true).build());}catch(SecurityException ignored){}
    }
    static String sha256(File file)throws Exception{MessageDigest d=MessageDigest.getInstance("SHA-256");try(InputStream in=new FileInputStream(file)){byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1)d.update(b,0,n);}return hex(d.digest());}
    static String hex(byte[] bytes){StringBuilder s=new StringBuilder();for(byte b:bytes)s.append(String.format("%02x",b));return s.toString();}
}
