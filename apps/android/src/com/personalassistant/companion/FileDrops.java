package com.personalassistant.companion;
import android.app.*;
import android.content.*;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.webkit.MimeTypeMap;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.Set;

/** Files the owner asked the assistant for: streamed, checksum-verified download into Downloads, one "File ready" card,
 *  then a receipt so the relay deletes its copy. Saved state is recorded per drop ID, so retries never add a second copy. */
final class FileDrops {
    /** The relay's limit is configurable; this only refuses absurd declared sizes. */
    static final long MAX=512L*1024*1024;
    /** File systems limit a name to 255 UTF-8 bytes (Android 8-9 refuse longer ones outright); this leaves room for a " (n)" suffix. */
    static final int NAME_BYTES=200;
    /** Lists in one job run; drops still waiting after them are left to the job's retry. */
    static final int PASSES=40;
    /** Without a file event the waiting list is still checked this often, so a missed or expired event never strands a drop. */
    static final long RECHECK=6L*3600*1000;
    static final String APK="application/vnd.android.package-archive";
    private static final Object lock=new Object();
    static String key(String id){return "file_drop:"+id;}
    /** A file event arrived: the job lists and downloads every waiting drop. */
    static void due(Context c){Cloud.prefs(c).edit().putBoolean("file_drops_due",true).commit();}
    /** Due after a file event or a failure; otherwise the list is checked again once the last complete check is old. */
    static boolean waiting(Context c){SharedPreferences p=Cloud.prefs(c);long age=System.currentTimeMillis()-p.getLong("file_drops_listed",0);return p.getBoolean("file_drops_due",false)||age<0||age>RECHECK;}
    /** Lists and delivers every waiting drop. True when drops may still be waiting after the pass limit, so the job runs again. */
    static boolean sync(Context c)throws Exception{synchronized(lock){
        SharedPreferences p=Cloud.prefs(c);Set<String> seen=new HashSet<>();Exception failed=null;
        try{
            // The relay lists one page of waiting drops and delivered ones leave it. Re-list while a pass found drops this run has not
            // tried yet, or while a new event arrived meanwhile (a running job is not restarted for it). A failed drop waits for the retry.
            for(int pass=0;pass<PASSES;pass++){
                p.edit().putBoolean("file_drops_due",false).commit();
                // A server without file transfer (404) has nothing waiting; the periodic check must not retry against it forever.
                JSONArray items;boolean fresh=false;
                try{items=((JSONObject)Cloud.call(c,"files",null,true)).optJSONArray("items");}catch(Cloud.HttpError missing){if(missing.status!=404)throw missing;items=null;}
                if(items!=null)for(int i=0;i<items.length();i++)try{JSONObject item=items.getJSONObject(i);if(seen.add(item.optString("id"))){fresh=true;deliver(c,item);}}catch(Exception error){failed=error;}
                if(!fresh&&!p.getBoolean("file_drops_due",false)){
                    if(failed!=null)throw failed;
                    p.edit().putString("file_drop_status","").putLong("file_drops_listed",System.currentTimeMillis()).commit();
                    return false;
                }
            }
            if(failed!=null)throw failed;
        }catch(Exception error){due(c);throw error;}
        due(c);return true;
    }}
    static void deliver(Context c,JSONObject item)throws Exception{
        String id=item.getString("id"),sha=item.getString("sha256");
        if(!id.matches("[A-Za-z0-9_-]{8,64}")||!sha.matches("[0-9a-f]{64}"))throw new Exception("Invalid file record");
        SharedPreferences p=Cloud.prefs(c);JSONObject saved=new JSONObject(p.getString(key(id),"{}"));
        if(!"saved".equals(saved.optString("state"))||!sha.equals(saved.optString("sha256"))){
            // An interrupted attempt left a partial or pending copy: remove it before saving again.
            discard(c,saved);
            try{save(c,id,item);}
            catch(Cloud.HttpError gone){if(gone.status!=404&&gone.status!=410)throw gone;p.edit().remove(key(id)).commit();return;}
        }
        try{Cloud.call(c,"files/"+id+"/receipt",new JSONObject().put("sha256",sha),true);}
        catch(Cloud.HttpError gone){if(gone.status!=404&&gone.status!=410)throw gone;}
        p.edit().remove(key(id)).commit();
    }
    static void discard(Context c,JSONObject saved){
        try{
            if(saved.has("file"))new File(saved.getString("file")).delete();
            else if(saved.has("uri")&&Build.VERSION.SDK_INT>=29)c.getContentResolver().delete(Uri.parse(saved.getString("uri")),null,null);
        }catch(Exception alreadyGone){}
    }
    static void save(Context c,String id,JSONObject item)throws Exception{
        String name=safeName(item.optString("name")),declared=item.optString("mime"),sha=item.getString("sha256"),mime=mime(declared,name);long size=item.getLong("size");
        if(size<0||size>MAX)throw new Exception("Unexpected file size");
        File folder=new File(c.getCacheDir(),"file-drops");folder.mkdirs();File part=new File(folder,id+".part");
        try{
            download(c,id,size,sha,part);
            SharedPreferences p=Cloud.prefs(c);JSONObject state=new JSONObject().put("sha256",sha).put("state","saving");Uri uri;
            if(Build.VERSION.SDK_INT>=29){
                ContentResolver resolver=c.getContentResolver();ContentValues values=new ContentValues();
                values.put(MediaStore.MediaColumns.DISPLAY_NAME,name);values.put(MediaStore.MediaColumns.MIME_TYPE,mime);
                values.put(MediaStore.MediaColumns.RELATIVE_PATH,Environment.DIRECTORY_DOWNLOADS);values.put(MediaStore.MediaColumns.IS_PENDING,1);
                uri=resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI,values);if(uri==null)throw new Exception("Downloads is unavailable");
                if(!p.edit().putString(key(id),state.put("uri",uri.toString()).toString()).commit()){resolver.delete(uri,null,null);throw new Exception("Phone storage failed");}
                try(InputStream in=new FileInputStream(part);OutputStream out=resolver.openOutputStream(uri)){if(out==null)throw new Exception("Downloads is unavailable");copy(in,out);}
                values.clear();values.put(MediaStore.MediaColumns.IS_PENDING,0);resolver.update(uri,values,null,null);
                // MediaStore can change the name, e.g. add the extension of the declared type: the card names and opens what was saved.
                name=savedName(resolver,uri,name);
            }else{
                // Before Android 10 public Downloads needs a storage permission; app-specific storage is shared through FileDropProvider.
                File downloads=c.getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);if(downloads==null)throw new Exception("Phone storage is unavailable");
                downloads.mkdirs();File target=unique(downloads,name);
                if(!p.edit().putString(key(id),state.put("file",target.getAbsolutePath()).toString()).commit())throw new Exception("Phone storage failed");
                if(!part.renameTo(target))try(InputStream in=new FileInputStream(part);OutputStream out=new FileOutputStream(target)){copy(in,out);}
                uri=FileDropProvider.uri(c,target);name=target.getName();
            }
            if(!p.edit().putString(key(id),state.put("state","saved").put("uri",uri.toString()).toString()).commit())throw new Exception("Phone storage failed");
            notifyReady(c,id,name,declared,uri,item.optString("note"));
        }finally{part.delete();}
    }
    static void download(Context c,String id,long size,String sha,File part)throws Exception{
        final String base,token;synchronized(Cloud.class){base=Cloud.prefs(c).getString("origin","");token=Cloud.prefs(c).getString("token","");}
        if(base.isEmpty()||token.isEmpty())throw new Exception("Pair the companion first");
        HttpURLConnection connection=(HttpURLConnection)new URL(base+"/groceries/v1/mobile/files/"+id).openConnection();
        connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(10000);connection.setReadTimeout(30000);connection.setRequestProperty("Authorization","Bearer "+token);
        try{
            int status=connection.getResponseCode();
            if(status!=200)throw new Cloud.HttpError(status,status==401?"Disconnected. Pair the companion again.":"File download unavailable ("+status+")");
            // Streamed to a cache file, never held in memory; size and checksum are checked before anything reaches Downloads.
            MessageDigest digest=MessageDigest.getInstance("SHA-256");long received=0;byte[] buffer=new byte[65536];int count;
            try(InputStream in=connection.getInputStream();OutputStream out=new FileOutputStream(part)){
                while((count=in.read(buffer))!=-1){received+=count;if(received>size)throw new Exception("Download exceeded its declared size");digest.update(buffer,0,count);out.write(buffer,0,count);}
            }
            if(received!=size||!Updates.hex(digest.digest()).equals(sha))throw new Exception("Download did not pass its checksum");
        }finally{connection.disconnect();}
    }
    static void copy(InputStream in,OutputStream out)throws IOException{byte[] buffer=new byte[65536];int count;while((count=in.read(buffer))!=-1)out.write(buffer,0,count);}
    static String safeName(String value){
        // Format characters such as a right-to-left override, and line or paragraph separators, could disguise the real extension.
        // Joiners (Persian, Indic and emoji spelling) and emoji tag characters cannot, so they stay.
        String name=value==null?"":value.replaceAll("[\\\\/:*?\"<>|\\p{Cc}\\p{Zl}\\p{Zp}]|[\\p{Cf}&&[^\\u200C\\u200D\\x{E0020}-\\x{E007F}]]","_").trim();
        if(name.replace(".","").isEmpty())name="download";
        // The limit is in UTF-8 bytes, not characters: a short extension is kept and the stem is cut at a whole code point.
        int dot=name.lastIndexOf('.');String ext=dot>0&&utf8(name.substring(dot))<=32?name.substring(dot):"",stem=name.substring(0,name.length()-ext.length());
        int end=0;for(int used=utf8(ext),point;end<stem.length();end+=Character.charCount(point)){point=stem.codePointAt(end);used+=point<0x80?1:point<0x800?2:point<0x10000?3:4;if(used>NAME_BYTES)break;}
        return stem.substring(0,end).trim()+ext;
    }
    static int utf8(String value){return value.getBytes(StandardCharsets.UTF_8).length;}
    static String savedName(ContentResolver resolver,Uri uri,String fallback){
        try(Cursor row=resolver.query(uri,new String[]{MediaStore.MediaColumns.DISPLAY_NAME},null,null,null)){
            String name=row!=null&&row.moveToFirst()?row.getString(0):null;if(name!=null&&!name.trim().isEmpty())return name;
        }catch(Exception unreadable){}
        return fallback;
    }
    /** An app package by its saved extension or its declared type. */
    static boolean apk(String name,String declared){return "apk".equals(extension(name))||APK.equals(mime(declared,name));}
    static String extension(String name){int dot=name.lastIndexOf('.');return dot<0?"":name.substring(dot+1).toLowerCase(java.util.Locale.ROOT);}
    static String mime(String declared,String name){
        String value=declared==null?"":declared.toLowerCase(java.util.Locale.ROOT);
        if(value.matches("[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*")&&!value.equals("application/octet-stream"))return value;
        String guessed=MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension(name));
        return guessed==null?"application/octet-stream":guessed;
    }
    static File unique(File folder,String name){
        File file=new File(folder,name);int dot=name.lastIndexOf('.');String stem=dot>0?name.substring(0,dot):name,ext=dot>0?name.substring(dot):"";
        for(int n=1;file.exists();n++)file=new File(folder,stem+" ("+n+")"+ext);
        return file;
    }
    /** The name is the saved one, so the type the card opens with follows the extension the file really has. */
    static void notifyReady(Context c,String id,String name,String declared,Uri uri,String note){
        NotificationManager manager=(NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE);NativeNotifications.channels(manager);
        // An app package is saved but never opened from the card: a misleading name or type must not lead into the package installer.
        boolean pkg=apk(name,declared);
        PendingIntent folder=Build.VERSION.SDK_INT>=29?PendingIntent.getActivity(c,("file-"+id+"folder").hashCode(),new Intent(DownloadManager.ACTION_VIEW_DOWNLOADS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE):null,open=folder;
        if(!pkg){
            Intent view=new Intent(Intent.ACTION_VIEW).setDataAndType(uri,mime(null,name)).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_ACTIVITY_NEW_TASK);
            // The chooser carries the read grant to whichever app the owner picks.
            Intent chooser=Intent.createChooser(view,"Open "+name).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_ACTIVITY_NEW_TASK);
            open=PendingIntent.getActivity(c,("file-"+id).hashCode(),chooser,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        }
        String where=(Build.VERSION.SDK_INT>=29?"Saved to Downloads":"Saved in Assistant Companion's downloads")+(pkg?" · app packages are not opened from here":""),text=note==null||note.trim().isEmpty()?(pkg?where:where+" · tap to open"):note.trim();
        Notification.Builder notification=new Notification.Builder(c,"files").setSmallIcon(R.drawable.ic_stat_assistant).setColor(NativeNotifications.ACCENT)
            .setContentTitle("File ready: "+name).setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text.startsWith(where)?text:text+"\n"+where))
            .setSubText("File").setLargeIcon(NotificationStyle.icon(c,"download",NotificationStyle.DONE)).setContentIntent(open).setAutoCancel(true)
            .setGroup("assistant_events").setShowWhen(true).setVisibility(Notification.VISIBILITY_PRIVATE)
            .setPublicVersion(new Notification.Builder(c,"files").setSmallIcon(R.drawable.ic_stat_assistant).setColor(NativeNotifications.ACCENT).setContentTitle("File ready").setSubText("File").build());
        if(!pkg)notification.addAction(new Notification.Action.Builder(null,"Open with",open).build());
        if(folder!=null)notification.addAction(new Notification.Action.Builder(null,"Downloads",folder).build());
        try{manager.notify("file-"+id,230,notification.build());}
        catch(SecurityException unavailable){Cloud.prefs(c).edit().putString("file_drop_status","File saved · allow notifications to see file cards").commit();}
    }
}
