package com.personalassistant.companion;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Handler;
import android.os.Looper;
import org.json.*;
import java.io.*;
import java.net.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;

/** Immutable cloud assets, prefetched by frequency and cached for offline use. */
final class MoneyLogos {
    interface Ready {void show(Bitmap bitmap);}
    private static final ExecutorService pool=Executors.newFixedThreadPool(2);
    private static final Map<String,ArrayList<Ready>> pending=new HashMap<>();
    private static final Handler main=new Handler(Looper.getMainLooper());
    private MoneyLogos(){}
    static String id(JSONObject descriptor){String value=descriptor==null?"":descriptor.optString("cache_id","");return value.matches("[a-f0-9]{64}")?value:"";}
    static File file(Context context,String id){return new File(new File(context.getCacheDir(),"money-logos"),id+".png");}
    static Bitmap decode(File path){if(!path.isFile()||path.length()>32768)return null;BitmapFactory.Options options=new BitmapFactory.Options();options.inJustDecodeBounds=true;BitmapFactory.decodeFile(path.toString(),options);if(options.outWidth<8||options.outWidth>256||options.outHeight<8||options.outHeight>256)return null;return BitmapFactory.decodeFile(path.toString());}
    static void load(Context context,JSONObject descriptor,Ready callback){
        String key=id(descriptor);if(key.isEmpty())return;Bitmap hit=decode(file(context,key));if(hit!=null){if(callback!=null)callback.show(hit);return;}
        synchronized(pending){ArrayList<Ready> wait=pending.get(key);if(wait!=null){if(callback!=null)wait.add(callback);return;}wait=new ArrayList<>();if(callback!=null)wait.add(callback);pending.put(key,wait);}
        Context app=context.getApplicationContext();pool.execute(()->{Bitmap bitmap=null;try{bitmap=fetch(app,key,descriptor.optString("url",""));}catch(Exception ignored){}Bitmap value=bitmap;ArrayList<Ready> wait;synchronized(pending){wait=pending.remove(key);}if(value!=null&&wait!=null)main.post(()->{for(Ready ready:wait)ready.show(value);});});
    }
    static Bitmap fetch(Context context,String id,String path)throws Exception{
        String expected="/groceries/v1/mobile/money/logos/"+id;if(!expected.equals(path))throw new IOException("Invalid logo path");
        String origin,token;synchronized(Cloud.class){origin=Cloud.prefs(context).getString("origin","");token=Cloud.prefs(context).getString("token","");}
        if(origin.isEmpty()||token.isEmpty())throw new IOException("Not paired");
        HttpURLConnection connection=(HttpURLConnection)new URL(Cloud.origin(origin)+path).openConnection();connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(8000);connection.setReadTimeout(10000);connection.setRequestProperty("Authorization","Bearer "+token);
        byte[] bytes;try{if(connection.getResponseCode()!=200)throw new IOException("Logo unavailable");ByteArrayOutputStream out=new ByteArrayOutputStream();try(InputStream in=connection.getInputStream()){byte[] buffer=new byte[4096];int n;while((n=in.read(buffer))!=-1){out.write(buffer,0,n);if(out.size()>32768)throw new IOException("Logo too large");}}bytes=out.toByteArray();}finally{connection.disconnect();}
        StringBuilder hash=new StringBuilder();for(byte value:MessageDigest.getInstance("SHA-256").digest(bytes))hash.append(String.format(Locale.ROOT,"%02x",value&255));if(!id.equals(hash.toString()))throw new IOException("Logo checksum mismatch");
        File destination=file(context,id);destination.getParentFile().mkdirs();File temp=File.createTempFile("logo-",".png",destination.getParentFile());try{try(FileOutputStream out=new FileOutputStream(temp)){out.write(bytes);}Bitmap decoded=decode(temp);if(decoded==null)throw new IOException("Invalid logo image");if(!temp.renameTo(destination)&&!destination.isFile())throw new IOException("Logo cache failed");return decoded;}finally{temp.delete();}
    }
    static void preload(Context context,JSONObject summary){JSONObject logos=summary.optJSONObject("merchant_logos");if(logos==null)return;HashMap<String,Integer> frequency=new HashMap<>();JSONArray rows=summary.optJSONArray("transactions");for(int i=0;rows!=null&&i<rows.length();i++){JSONObject row=rows.optJSONObject(i);if(row!=null){String name=row.optString("merchant_name","");frequency.put(name,frequency.getOrDefault(name,0)+1);}}ArrayList<String> names=new ArrayList<>();Iterator<String> keys=logos.keys();while(keys.hasNext())names.add(keys.next());Collections.sort(names,(a,b)->Integer.compare(frequency.getOrDefault(b,0),frequency.getOrDefault(a,0)));for(int i=0;i<Math.min(12,names.size());i++)load(context,logos.optJSONObject(names.get(i)),null);}
}
