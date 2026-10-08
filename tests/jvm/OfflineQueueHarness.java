package com.personalassistant.companion;

import android.content.Context;
import java.io.*;
import java.net.*;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;

/** Production storage classes against controlled transport: no external network. */
public final class OfflineQueueHarness {
    static CountDownLatch shoppingEntered=new CountDownLatch(1),shoppingRelease=new CountDownLatch(1),voiceEntered=new CountDownLatch(1),voiceRelease=new CountDownLatch(1);
    static final List<String> mutationIds=Collections.synchronizedList(new ArrayList<>());
    static class Connection extends HttpURLConnection {
        final ByteArrayOutputStream sent=new ByteArrayOutputStream();
        Connection(URL url){super(url);}
        public void disconnect(){}public boolean usingProxy(){return false;}public void connect(){}
        public OutputStream getOutputStream(){return sent;}
        public int getResponseCode()throws IOException {
            try{if(url.getPath().endsWith("/mutations")){mutationIds.add(new JSONObject(sent.toString("UTF-8")).getString("id"));shoppingEntered.countDown();if(!shoppingRelease.await(5,TimeUnit.SECONDS))throw new IOException("Shopping fixture timeout");}
                if(url.getPath().endsWith("/voice")){voiceEntered.countDown();if(!voiceRelease.await(5,TimeUnit.SECONDS))throw new IOException("Voice fixture timeout");}return 200;
            }catch(Exception error){throw new IOException(error);}
        }
        public InputStream getInputStream(){return new ByteArrayInputStream((url.getPath().endsWith("/voice")?"{\"status\":\"queued\",\"reply\":\"Saved\",\"text\":\"Fixture\"}":"{\"items\":[],\"recipes\":[]}").getBytes(java.nio.charset.StandardCharsets.UTF_8));}
    }
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static JSONObject change(String text)throws Exception{return new JSONObject().put("operation","add").put("items",new JSONArray().put(new JSONObject().put("name",text).put("quantity","")));}
    public static void main(String[] args)throws Exception {
        boolean baseline=args.length>0&&args[0].equals("baseline");URL.setURLStreamHandlerFactory(protocol->protocol.equals("https")?new URLStreamHandler(){protected URLConnection openConnection(URL url){return new Connection(url);}}:null);
        Context context=new Context(new File(args[baseline?1:0]));Cloud.prefs(context).edit().putString("origin","https://offline.invalid").putString("token","offline-fixture").commit();
        Cloud.enqueue(context,change("First"));check(Cloud.pendingList(context).getJSONArray("items").getJSONObject(0).getBoolean("pending"),"Pending add not displayed");check(Cloud.cached(context).getJSONArray("items").length()==0,"Optimistic view mutated cache");ExecutorService executor=Executors.newFixedThreadPool(4);Future<?> sync=executor.submit(()->{try{Cloud.sync(context);}catch(Exception error){throw new RuntimeException(error);}});check(shoppingEntered.await(2,TimeUnit.SECONDS),"Sync did not reach controlled transport");
        Future<?> append=executor.submit(()->{try{Cloud.enqueue(context,change("Second"));}catch(Exception error){throw new RuntimeException(error);}});boolean shoppingBlocked=false;try{append.get(250,TimeUnit.MILLISECONDS);}catch(TimeoutException held){shoppingBlocked=true;}shoppingRelease.countDown();sync.get(2,TimeUnit.SECONDS);append.get(2,TimeUnit.SECONDS);Cloud.sync(context);
        check(Cloud.queue(context).length()==0,"Concurrent shopping addition was not delivered");check(mutationIds.size()==2&&new HashSet<>(mutationIds).size()==2,"Addition lost or duplicate IDs sent");
        Cloud.prefs(context).edit().putString("snapshot","{\"items\":[{\"id\":\"cached\",\"name\":\"Cached\",\"complete\":0,\"version\":1}],\"recipes\":[]}").commit();Cloud.enqueue(context,new JSONObject().put("operation","complete").put("target","cached").put("version",1).put("complete",true));String completion=Cloud.queue(context).getJSONObject(0).getString("id");Cloud.enqueue(context,change("Later"));check(Cloud.pendingList(context).getJSONArray("items").getJSONObject(0).getInt("complete")==1,"Pending completion absent");check(Cloud.cached(context).getJSONArray("items").getJSONObject(0).getInt("complete")==0,"Completion edited source cache");check(Cloud.rebaseQueuedCompletion(context,completion,2),"Queued completion not found");check(Cloud.queue(context).length()==2&&Cloud.queue(context).getJSONObject(0).getInt("version")==2,"Rebase lost appended change");check(!completion.equals(Cloud.queue(context).getJSONObject(0).getString("id")),"Changed completion reused original ID");check(!Cloud.rebaseQueuedCompletion(context,completion,3),"Old acknowledged/changed ID recreated");boolean rejectedAdd=false;try{Cloud.rebaseQueuedCompletion(context,Cloud.queue(context).getJSONObject(1).getString("id"),2);}catch(IllegalStateException expected){rejectedAdd=true;}check(rejectedAdd,"Reviewed addition assigned new ID");
        String first=VoiceOutbox.save(context,new short[]{7,8,9},"fixture",true);Future<?> flush=executor.submit(()->{try{VoiceOutbox.flush(context,null);}catch(Exception error){throw new RuntimeException(error);}});check(voiceEntered.await(2,TimeUnit.SECONDS),"Upload did not reach controlled transport");
        Future<Integer> count=executor.submit(()->VoiceOutbox.pending(context));Future<String> save=executor.submit(()->VoiceOutbox.save(context,new short[]{10,11},"fixture",true));boolean voiceReadBlocked=false,voiceSaveBlocked=false;
        try{count.get(250,TimeUnit.MILLISECONDS);}catch(TimeoutException held){voiceReadBlocked=true;}try{save.get(250,TimeUnit.MILLISECONDS);}catch(TimeoutException held){voiceSaveBlocked=true;}voiceRelease.countDown();flush.get(2,TimeUnit.SECONDS);count.get(2,TimeUnit.SECONDS);String second=save.get(2,TimeUnit.SECONDS);
        check(!new File(VoiceOutbox.directory(context),first+".json").exists(),"Acknowledged voice envelope retained");check(new File(VoiceOutbox.directory(context),second+".json").isFile(),"New recording lost while older upload waited");check(VoiceOutbox.pending(context)==1,"Unexpected pending voice count");
        JSONObject receipt=new JSONObject(VoiceOutbox.read(new File(context.getFilesDir(),"voice-receipts/"+first+".json")));check(first.equals(receipt.getString("id")),"Receipt changed command ID");
        check(Cloud.prefs(context).getString("voice_user_text","").equals("Fixture")&&Cloud.prefs(context).getString("voice_reply","").equals("Saved"),"Receipt text/reply fields lost");
        JSONObject live=new JSONObject().put("task_id","live-fixture").put("text","Original request").put("status","queued").put("reply","Queued");check(VoiceHistory.record(context,live),"Initial Live receipt not saved");check(!VoiceHistory.record(context,live),"Duplicate Live acknowledgement rewrote history");check(VoiceHistory.record(context,new JSONObject().put("task_id","live-fixture").put("status","completed").put("reply","Done")),"Live completion not merged");JSONObject history=new JSONObject(VoiceOutbox.read(new File(context.getFilesDir(),"voice-receipts/live-fixture.json")));check(history.getString("text").equals("Original request")&&history.getString("reply").equals("Done"),"Live update lost original text");check(!VoiceHistory.record(context,new JSONObject().put("status","ended")),"Missing ID invented a request");boolean badId=false;try{VoiceHistory.record(context,new JSONObject().put("task_id","../unsafe"));}catch(IllegalArgumentException expected){badId=true;}check(badId,"Unsafe receipt ID accepted");
        executor.shutdownNow();JSONObject proof=new JSONObject().put("network_used",false).put("shopping_enqueue_blocked_by_network",shoppingBlocked).put("voice_pending_blocked_by_network",voiceReadBlocked).put("voice_save_blocked_by_network",voiceSaveBlocked).put("concurrent_shopping_ids_sent_once",true).put("new_recording_preserved",true).put("voice_receipt_id_preserved",true).put("optimistic_view_detached",true).put("completion_rebase_preserves_appends",true).put("add_rebase_rejected",true).put("receipt_text_reply_preserved",true).put("live_history_merge_and_idempotence",true).put("missing_history_id_not_invented",true);
        if(!baseline)check(!shoppingBlocked&&!voiceReadBlocked&&!voiceSaveBlocked,"Network lock blocks local UI/storage");System.out.println(proof);
    }
}
