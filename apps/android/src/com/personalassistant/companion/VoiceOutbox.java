package com.personalassistant.companion;

import android.content.Context;
import android.util.Base64;
import java.io.*;
import java.net.*;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;

/** Durable command audio. A lost HTTP acknowledgement resends the same command ID. */
final class VoiceOutbox {
    static final ExecutorService executor=Executors.newSingleThreadExecutor();
    private static final Object uploadLock=new Object();
    interface Listener {void received(JSONObject result);void unavailable(String message);}
    static File directory(Context c){File d=new File(c.getFilesDir(),"voice-outbox");d.mkdirs();return d;}
    static boolean networkReady(Context c){android.net.ConnectivityManager manager=(android.net.ConnectivityManager)c.getSystemService(Context.CONNECTIVITY_SERVICE);android.net.NetworkCapabilities capabilities=manager.getNetworkCapabilities(manager.getActiveNetwork());return capabilities!=null&&capabilities.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_INTERNET)&&capabilities.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_VALIDATED);}
    static void refreshGroceries(Context c){SyncJob.executor.execute(()->{try{JSONObject list=(JSONObject)Cloud.call(c,"list",null,true);Cloud.prefs(c).edit().putString("snapshot",list.toString()).putLong("synced",System.currentTimeMillis()).putString("status","Cloud saved").commit();ShoppingWidget.update(c);c.sendBroadcast(new android.content.Intent("com.personalassistant.companion.GROCERY_STATE").setPackage(c.getPackageName()));}catch(Exception error){SyncJob.schedule(c,false);}});}
    static synchronized int pending(Context c){File[] files=directory(c).listFiles((d,n)->n.endsWith(".json"));return files==null?0:files.length;}
    static synchronized String save(Context c,short[] audio,String session,boolean dryRun) throws Exception {
        String id=UUID.randomUUID().toString();JSONObject envelope=new JSONObject().put("id",id).put("created_at",java.time.Instant.now().toString()).put("timezone",TimeZone.getDefault().getID()).put("session_id",session).put("sample_rate",16000).put("format","wav").put("dry_run",dryRun).put("native_timers",true).put("audio_base64",Base64.encodeToString(wav(audio),Base64.NO_WRAP));
        File temp=new File(directory(c),id+".part"),target=new File(directory(c),id+".json");try(FileOutputStream out=new FileOutputStream(temp)){out.write(envelope.toString().getBytes("UTF-8"));out.getFD().sync();}if(!temp.renameTo(target))throw new IOException("Could not save the voice command");return id;
    }
    static byte[] wav(short[] pcm) throws IOException {ByteArrayOutputStream out=new ByteArrayOutputStream(44+pcm.length*2);out.write("RIFF".getBytes("US-ASCII"));le(out,36+pcm.length*2,4);out.write("WAVEfmt ".getBytes("US-ASCII"));le(out,16,4);le(out,1,2);le(out,1,2);le(out,16000,4);le(out,32000,4);le(out,2,2);le(out,16,2);out.write("data".getBytes("US-ASCII"));le(out,pcm.length*2,4);for(short sample:pcm)le(out,sample,2);return out.toByteArray();}
    static void le(OutputStream out,int value,int bytes)throws IOException{for(int i=0;i<bytes;i++)out.write((value>>>(8*i))&255);}
    static void retry(Context c,Listener listener){retry(c,null,listener);}
    static void retry(Context c,String commandId,Listener listener){executor.execute(()->{try{flush(c,null);if(listener!=null&&commandId!=null){File receipt=new File(c.getFilesDir(),"voice-receipts/"+commandId+".json");if(receipt.isFile())listener.received(new JSONObject(read(receipt)));else listener.unavailable("Voice command saved; acknowledgement pending");}}catch(Exception error){Cloud.prefs(c).edit().putString("voice_status","Cloud unavailable · "+pending(c)+" voice command(s) saved on this phone").commit();if(listener!=null)listener.unavailable(error.getMessage());}});}
    static void flush(Context c,Listener listener)throws Exception{synchronized(uploadLock){
        File[] files=directory(c).listFiles((d,n)->n.endsWith(".json"));if(files==null)return;Arrays.sort(files,Comparator.comparingLong(File::lastModified));
        for(File file:files){JSONObject body=new JSONObject(read(file));JSONObject response=TimerVoice.apply(c,upload(c,body).put("id",body.getString("id")));File receipts=new File(c.getFilesDir(),"voice-receipts");receipts.mkdirs();File receipt=new File(receipts,body.getString("id")+".json");try(FileOutputStream out=new FileOutputStream(receipt)){out.write(response.toString().getBytes("UTF-8"));out.getFD().sync();}if(!file.delete())throw new IOException("Voice receipt saved, pending file cleanup failed");Cloud.prefs(c).edit().putString("voice_last",response.toString()).putString("voice_transcript",response.optString("text","")).putString("voice_user_text",response.optString("text","")).putString("voice_reply",response.optString("reply",response.optString("status","Cloud acknowledged"))).putString("voice_status",response.optString("reply",response.optString("status","Cloud acknowledged"))).commit();recordChat(c,body,response);if(response.optBoolean("grocery_changed",false))refreshGroceries(c);c.sendBroadcast(new android.content.Intent("com.personalassistant.companion.VOICE_STATE").setPackage(c.getPackageName()));if(listener!=null)listener.received(response);}
    }}
    static void recordChat(Context c,JSONObject body,JSONObject response){
        long created=System.currentTimeMillis();try{created=java.time.Instant.parse(body.optString("created_at")).toEpochMilli();}catch(Exception ignored){}
        String task=response.optString("task_id",""),id=task.isEmpty()?body.optString("id"):task,status=response.optString("status");
        VoiceChat.user(c,response.optString("user_message_id",id),response.optString("text"),created);
        VoiceChat.assistant(c,id,response.optString("reply",status),System.currentTimeMillis(),status.equals("queued")||status.equals("running")?"acknowledgement":"answer",task);
    }
    static String read(File file)throws IOException{ByteArrayOutputStream out=new ByteArrayOutputStream();try(InputStream in=new FileInputStream(file)){byte[] bytes=new byte[8192];int n;while((n=in.read(bytes))!=-1){out.write(bytes,0,n);if(out.size()>5000000)throw new IOException("Saved audio is too large");}}return out.toString("UTF-8");}
    static JSONObject upload(Context c,JSONObject body)throws Exception{
        String token=Cloud.prefs(c).getString("token","");if(token.isEmpty())throw new IOException("Pair the phone first");
        HttpURLConnection connection=(HttpURLConnection)new URL(Cloud.origin(Cloud.prefs(c).getString("origin",""))+"/groceries/v1/mobile/voice").openConnection();connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(10000);connection.setReadTimeout(90000);connection.setRequestProperty("Authorization","Bearer "+token);connection.setRequestProperty("Content-Type","application/json");connection.setRequestMethod("POST");connection.setDoOutput(true);
        try{byte[] bytes=body.toString().getBytes("UTF-8");connection.setFixedLengthStreamingMode(bytes.length);try(OutputStream out=connection.getOutputStream()){out.write(bytes);}int code=connection.getResponseCode();if(code<200||code>=300)throw new IOException(code==401?"Pairing expired. Reconnect this phone.":"Voice server unavailable ("+code+")");ByteArrayOutputStream result=new ByteArrayOutputStream();try(InputStream in=connection.getInputStream()){byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1){result.write(b,0,n);if(result.size()>2097152)throw new IOException("Voice response too large");}}return new JSONObject(result.toString("UTF-8"));}finally{connection.disconnect();}
    }
}
