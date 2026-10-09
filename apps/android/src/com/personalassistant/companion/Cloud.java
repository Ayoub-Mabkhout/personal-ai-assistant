package com.personalassistant.companion;

import android.content.*;
import org.json.*;
import java.net.*;
import java.io.*;
import java.util.UUID;

final class Cloud {
    // Serialize network syncs independently from short local outbox transactions.
    // An offline/slow request must not prevent the UI from saving a new item.
    private static final Object syncLock=new Object();
    private static String syncingId;
    static SharedPreferences prefs(Context c) { return c.getSharedPreferences("assistant",0); }
    static JSONObject cached(Context c) {
        try { return new JSONObject(prefs(c).getString("snapshot","{\"items\":[],\"recipes\":[]}")); }
        catch(Exception e) { return new JSONObject(); }
    }
    static JSONArray queue(Context c) {
        try { return new JSONArray(prefs(c).getString("outbox","[]")); }
        catch(Exception e) { throw new IllegalStateException("Saved shopping changes need recovery",e); }
    }
    /** Detached optimistic view shared by the app and widget; never edits cache. */
    static synchronized JSONObject pendingList(Context c)throws JSONException {
        JSONObject snapshot=cached(c);JSONArray rows=snapshot.optJSONArray("items");if(rows==null){rows=new JSONArray();snapshot.put("items",rows);}JSONArray pending=queue(c);
        for(int index=0;index<pending.length();index++){
            JSONObject change=pending.getJSONObject(index);String operation=change.optString("operation");
            if("complete".equals(operation))for(int row=0;row<rows.length();row++){JSONObject item=rows.getJSONObject(row);if(item.optString("id").equals(change.optString("target")))item.put("complete",change.optBoolean("complete",true)?1:0).put("pending",true);}
            if("add".equals(operation)){JSONArray additions=change.getJSONArray("items");for(int row=0;row<additions.length();row++)rows.put(new JSONObject(additions.getJSONObject(row).toString()).put("id","pending-"+change.optString("id")+"-"+row).put("version",0).put("pending",true));}
        }return snapshot;
    }
    /** Rebase a reviewed completion only; append/new IDs from other UI actions survive. */
    static synchronized boolean rebaseQueuedCompletion(Context c,String identifier,int version)throws JSONException {
        if(version<1)throw new IllegalArgumentException("Current shopping item version required");
        if(identifier.equals(syncingId))throw new IllegalStateException("This change is still being sent. Wait for it to finish before retrying.");
        JSONArray pending=queue(c);for(int index=0;index<pending.length();index++){
            JSONObject change=pending.getJSONObject(index);if(!identifier.equals(change.optString("id")))continue;
            if(!"complete".equals(change.optString("operation")))throw new IllegalStateException("Saved additions retry with their original ID.");
            if(change.optInt("version")!=version){change.put("version",version).put("id",UUID.randomUUID().toString());if(!prefs(c).edit().putString("outbox",pending.toString()).commit())throw new IllegalStateException("Phone storage failed");}
            return true;
        }return false;
    }
    static synchronized void enqueue(Context c,JSONObject change) throws JSONException {
        JSONArray q=queue(c);
        if("complete".equals(change.optString("operation")))for(int n=0;n<q.length();n++){JSONObject old=q.getJSONObject(n);if("complete".equals(old.optString("operation"))&&old.optString("target").equals(change.optString("target"))&&old.optInt("version")==change.optInt("version"))return;}
        change.put("id",UUID.randomUUID().toString());q.put(change);
        if(!prefs(c).edit().putString("outbox",q.toString()).commit()) throw new IllegalStateException("Phone storage failed");
        ShoppingWidget.update(c);SyncJob.schedule(c,false);
    }
    static String origin(String value) throws Exception {
        URI uri=new URI(value.trim());
        if(!"https".equals(uri.getScheme())||uri.getHost()==null||uri.getUserInfo()!=null||uri.getQuery()!=null||uri.getFragment()!=null||!(uri.getPath().isEmpty()||uri.getPath().equals("/"))) throw new Exception("Enter the HTTPS server address without a path");
        return "https://"+uri.getRawAuthority();
    }
    /** Non-2xx reply; the message is unchanged for older callers, the status lets newer ones tell a gone item from a retryable failure. */
    static final class HttpError extends Exception {final int status;HttpError(int status,String message){super(message);this.status=status;}}
    static Object call(Context c,String path,JSONObject body,boolean auth) throws Exception {
        final String base,token;synchronized(Cloud.class){SharedPreferences p=prefs(c);base=p.getString("origin","");token=auth?p.getString("token",""):"";}
        if(base.isEmpty()) throw new Exception("Pair the companion first");
        HttpURLConnection connection=(HttpURLConnection)new URL(base+"/groceries/v1/mobile/"+path).openConnection();
        connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(10000);connection.setReadTimeout(15000);
        if(auth) connection.setRequestProperty("Authorization","Bearer "+token);
        try {
            if(body!=null){connection.setRequestMethod("POST");connection.setRequestProperty("Content-Type","application/json");connection.setDoOutput(true);try(OutputStream out=connection.getOutputStream()){out.write(body.toString().getBytes("UTF-8"));}}
            int status=connection.getResponseCode();
            if(status<200||status>=300) throw new HttpError(status,status==401?"Disconnected. Pair the companion again.":"Server rejected change ("+status+"). Your saved changes remain on this phone.");
            ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[8192];int n;
            try(InputStream in=connection.getInputStream()){while((n=in.read(b))!=-1){out.write(b,0,n);if(out.size()>2097152)throw new Exception("Server response too large");}}
            return new JSONTokener(out.toString("UTF-8")).nextValue();
        } finally {connection.disconnect();}
    }
    /** Optional read-only settings fetch; older/offline servers retain the last valid cache. */
    static void syncPreferences(Context c)throws Exception{
        SharedPreferences p=prefs(c);final String token,origin;long now=System.currentTimeMillis();
        synchronized(Cloud.class){token=p.getString("token","");origin=p.getString("origin","");long last=p.getLong("daylight_checked",0);if(token.isEmpty()||origin.isEmpty()||p.getBoolean("push_signing_out",false)||(last>0&&now>=last&&now-last<3600000L))return;p.edit().putLong("daylight_checked",now).commit();}
        JSONObject result=(JSONObject)call(c,"preferences",null,true);JSONObject daylight=result.optJSONObject("daylight");
        synchronized(Cloud.class){
            if(!token.equals(p.getString("token",""))||!origin.equals(p.getString("origin",""))||p.getBoolean("push_signing_out",false))return;
            SharedPreferences.Editor edit=p.edit();Object latitude=daylight==null?null:daylight.opt("latitude"),longitude=daylight==null?null:daylight.opt("longitude");
            if(latitude instanceof Number&&longitude instanceof Number&&DaylightTheme.valid(((Number)latitude).doubleValue(),((Number)longitude).doubleValue()))edit.putString("daylight_latitude",Double.toString(((Number)latitude).doubleValue())).putString("daylight_longitude",Double.toString(((Number)longitude).doubleValue()));
            else edit.remove("daylight_latitude").remove("daylight_longitude");
            edit.commit();
        }
    }
    static void sync(Context c) throws Exception {synchronized(syncLock){
        while(true){
            JSONObject change;synchronized(Cloud.class){JSONArray q=queue(c);if(q.length()==0)break;change=q.getJSONObject(0);syncingId=change.getString("id");}
            try{call(c,"mutations",change,true);
              synchronized(Cloud.class){
                // Re-read after acknowledgement: the UI may have appended while
                // this request waited. Remove only the acknowledged stable ID.
                JSONArray current=queue(c),next=new JSONArray();String acknowledged=change.getString("id");
                for(int i=0;i<current.length();i++){JSONObject item=current.getJSONObject(i);if(!acknowledged.equals(item.optString("id")))next.put(item);}
                if(!prefs(c).edit().putString("outbox",next.toString()).commit())throw new Exception("Phone storage failed");
              }
            }finally{synchronized(Cloud.class){syncingId=null;}}
        }
        JSONObject list=(JSONObject)call(c,"list",null,true);
        prefs(c).edit().putString("snapshot",list.toString()).putLong("synced",System.currentTimeMillis()).putString("status","Cloud saved").commit();
        ShoppingWidget.update(c);
    }}
}
