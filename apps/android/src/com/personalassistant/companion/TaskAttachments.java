package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.security.MessageDigest;
import java.util.*;

/** Private durable originals shared by new-task and follow-up drafts. */
final class TaskAttachments {
    static final long MAX=25L*1024*1024;static final int COUNT=10;
    static File file(Context c,String id){if(!id.matches("[A-Za-z0-9_-]{8,64}"))throw new IllegalArgumentException("Invalid file ID");File dir=new File(c.getFilesDir(),"task-attachments");dir.mkdirs();return new File(dir,id);}
    static synchronized JSONArray draft(Context c,String key){try{return new JSONArray(Cloud.prefs(c).getString("attachment_draft:"+key,"[]"));}catch(Exception e){throw new IllegalStateException("Saved attachments need recovery",e);}}
    static JSONObject metadata(Context c,String id)throws Exception{return new JSONObject(Cloud.prefs(c).getString("task_attachment:"+id,"{}"));}
    static JSONArray ids(JSONArray rows)throws Exception{JSONArray ids=new JSONArray();for(int n=0;n<rows.length();n++)ids.put(rows.getJSONObject(n).getString("id"));return ids;}
    static String size(long bytes){return bytes>=1024*1024?String.format(java.util.Locale.ROOT,"%.1f MB",bytes/1048576.0):Math.max(1,(bytes+1023)/1024)+" KB";}
    static void choose(Activity a,String draft){new AlertDialog.Builder(a).setTitle("Attach to task").setItems(new String[]{"Photos and screenshots","Files and documents"},(d,n)->a.startActivity(new Intent(a,AttachmentPickerActivity.class).putExtra("draft",draft).putExtra("images",n==0))).show();}
    static void add(Context c,String key,Uri uri)throws Exception{
        if(draft(c,key).length()>=COUNT)throw new Exception("Up to 10 files per message");
            String name="Attachment",mime=c.getContentResolver().getType(uri);long declared=-1;
        try(Cursor cursor=c.getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE},null,null,null)){if(cursor!=null&&cursor.moveToFirst()){name=cursor.getString(0);if(!cursor.isNull(1))declared=cursor.getLong(1);}}
        if(declared>MAX)throw new Exception("Choose files up to 25 MB each");
        name=name==null?"Attachment":name.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]","_").trim();if(name.isEmpty())name="Attachment";while(name.getBytes("UTF-8").length>160)name=name.substring(0,name.offsetByCodePoints(name.length(),-1));
        String id="att-"+UUID.randomUUID().toString().replace("-","");File target=file(c,id);long length=0;MessageDigest digest=MessageDigest.getInstance("SHA-256");
        try(InputStream input=c.getContentResolver().openInputStream(uri);OutputStream output=new FileOutputStream(target)){if(input==null)throw new Exception("This file could not be opened");byte[] bytes=new byte[65536];int n;while((n=input.read(bytes))!=-1){length+=n;if(length>MAX)throw new Exception("Choose files up to 25 MB each");digest.update(bytes,0,n);output.write(bytes,0,n);}}
        catch(Exception error){target.delete();throw error;}
        StringBuilder hash=new StringBuilder();for(byte b:digest.digest())hash.append(String.format("%02x",b&255));
        JSONObject row=new JSONObject().put("id",id).put("name",name).put("mime",mime==null?"application/octet-stream":mime).put("size",length).put("sha256",hash.toString());
        synchronized(TaskAttachments.class){JSONArray rows=draft(c,key);if(rows.length()>=COUNT){target.delete();throw new Exception("Up to 10 files per message");}rows.put(row);if(!Cloud.prefs(c).edit().putString("task_attachment:"+id,row.toString()).putString("attachment_draft:"+key,rows.toString()).commit()){target.delete();throw new Exception("Phone storage failed");}}
        NativeTasks.changed(c);
    }
    static synchronized void remove(Context c,String key,String id)throws Exception{JSONArray next=new JSONArray(),rows=draft(c,key);for(int n=0;n<rows.length();n++)if(!id.equals(rows.getJSONObject(n).optString("id")))next.put(rows.getJSONObject(n));Cloud.prefs(c).edit().putString("attachment_draft:"+key,next.toString()).commit();NativeTasks.changed(c);}
    static void renderDraft(Activity a,AppUi ui,LinearLayout box,String key,Runnable changed){
        JSONArray rows=draft(a,key);String signature=rows.toString();if(signature.equals(box.getTag()))return;box.setTag(signature);box.removeAllViews();box.setVisibility(rows.length()==0?View.GONE:View.VISIBLE);
        for(int n=0;n<rows.length();n++){JSONObject row=rows.optJSONObject(n);if(row==null)continue;LinearLayout line=ui.row();line.setPadding(ui.dp(8),ui.dp(3),0,ui.dp(3));TextView title=ui.detail(row.optString("name")+" - "+size(row.optLong("size")));title.setMaxLines(2);line.addView(title,new LinearLayout.LayoutParams(0,-2,1));ImageButton remove=ui.iconButton("x","Remove "+row.optString("name"),()->{try{remove(a,key,row.optString("id"));box.setTag(null);renderDraft(a,ui,box,key,changed);changed.run();}catch(Exception ignored){}});line.addView(remove,new LinearLayout.LayoutParams(ui.dp(40),ui.dp(40)));box.addView(line);}
    }
    static HttpURLConnection connection(Context c,String id,String suffix,String method)throws Exception{
        String origin=Cloud.origin(Cloud.prefs(c).getString("origin","")),token=Cloud.prefs(c).getString("token","");if(token.isEmpty())throw new Exception("Pair Companion first");
        HttpURLConnection con=(HttpURLConnection)new URL(origin+"/groceries/v1/mobile/task-attachments/"+id+suffix).openConnection();con.setInstanceFollowRedirects(false);con.setConnectTimeout(10000);con.setReadTimeout(60000);con.setRequestMethod(method);con.setRequestProperty("Authorization","Bearer "+token);return con;
    }
    static void check(HttpURLConnection con)throws Exception{int code=con.getResponseCode();if(code<200||code>=300)throw new Cloud.HttpError(code,code==413?"File is too large (25 MB maximum)":code==507?"Server attachment storage is full":"Attachment transfer failed ("+code+")");}
    static void upload(Context c,JSONArray ids)throws Exception{
        for(int n=0;n<ids.length();n++){String id=ids.getString(n);JSONObject row=metadata(c,id);if(row.length()==0)throw new Exception("An attachment needs recovery");
            try{JSONObject remote=(JSONObject)Cloud.call(c,"task-attachments/"+id,null,true);if(row.optString("sha256").equals(remote.optString("sha256"))&&row.optLong("size")==remote.optLong("size"))continue;throw new Exception("Attachment content changed");}catch(Cloud.HttpError error){if(error.status!=404)throw error;}
            File file=file(c,id);if(!file.isFile()||file.length()!=row.getLong("size"))throw new Exception("The saved attachment is unavailable");
            Cloud.prefs(c).edit().putString("task_attachment_transfer","Uploading "+row.getString("name")+" ("+(n+1)+"/"+ids.length()+")").apply();
            HttpURLConnection con=connection(c,id,"","PUT");try{JSONObject manifest=new JSONObject(row.toString());manifest.remove("id");con.setRequestProperty("X-Attachment-Manifest",android.util.Base64.encodeToString(manifest.toString().getBytes("UTF-8"),android.util.Base64.NO_WRAP));con.setRequestProperty("Content-Type","application/octet-stream");con.setDoOutput(true);con.setFixedLengthStreamingMode(file.length());try(InputStream in=new FileInputStream(file);OutputStream out=con.getOutputStream()){byte[] bytes=new byte[65536];int k;while((k=in.read(bytes))!=-1)out.write(bytes,0,k);}check(con);}finally{con.disconnect();Cloud.prefs(c).edit().remove("task_attachment_transfer").apply();}
        }
    }
    static void show(Activity a,AppUi ui,LinearLayout box,JSONArray rows){
        for(int n=0;rows!=null&&n<rows.length();n++){JSONObject row=rows.optJSONObject(n);if(row==null)continue;Button button=ui.quietButton(row.optString("name")+" - "+size(row.optLong("size")),()->open(a,row));box.addView(button,new LinearLayout.LayoutParams(-1,-2));}
    }
    static void open(Activity a,JSONObject row){Toast.makeText(a,"Opening "+row.optString("name"),Toast.LENGTH_SHORT).show();new Thread(()->{try{String id=row.getString("id");File target=file(a,id);
        if(!target.isFile()||target.length()!=row.getLong("size")||!hash(target).equals(row.getString("sha256"))){HttpURLConnection con=connection(a,id,"/content","GET");File part=new File(target.getPath()+".part");try{check(con);long total=0;try(InputStream in=con.getInputStream();OutputStream out=new FileOutputStream(part)){byte[] b=new byte[65536];int k;while((k=in.read(b))!=-1){total+=k;if(total>row.getLong("size")||total>MAX)throw new Exception("Unexpected attachment size");out.write(b,0,k);}}if(total!=row.getLong("size")||!hash(part).equals(row.getString("sha256")))throw new Exception("Attachment checksum mismatch");if(!part.renameTo(target))throw new Exception("Could not save attachment");}finally{con.disconnect();part.delete();}}
        Cloud.prefs(a).edit().putString("task_attachment:"+id,row.toString()).commit();Uri uri=Uri.parse("content://"+a.getPackageName()+".taskattachments/"+id);a.runOnUiThread(()->{try{a.startActivity(new Intent(Intent.ACTION_VIEW).setDataAndType(uri,row.optString("mime","application/octet-stream")).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION));}catch(Exception e){Toast.makeText(a,"No app can open this file type",Toast.LENGTH_LONG).show();}});
    }catch(Exception e){a.runOnUiThread(()->Toast.makeText(a,String.valueOf(e.getMessage()),Toast.LENGTH_LONG).show());}}).start();}
    static String hash(File file)throws Exception{MessageDigest digest=MessageDigest.getInstance("SHA-256");try(InputStream in=new FileInputStream(file)){byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1)digest.update(b,0,n);}StringBuilder hex=new StringBuilder();for(byte b:digest.digest())hex.append(String.format("%02x",b&255));return hex.toString();}
}
