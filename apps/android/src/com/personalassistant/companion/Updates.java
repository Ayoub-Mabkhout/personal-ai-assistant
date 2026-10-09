package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.content.pm.*;
import android.os.Build;
import android.provider.Settings;
import android.net.Uri;
import org.json.*;
import java.io.*;
import java.net.*;
import java.security.*;

final class Updates {
    static final int INSTALL_PERMISSION=304;
    private static final java.util.Map<Activity,AlertDialog> prompts=new java.util.WeakHashMap<>();
    static boolean promptVisible(Activity activity){AlertDialog dialog=prompts.get(activity);return dialog!=null&&dialog.isShowing();}
    static void dismissPrompt(Activity activity){AlertDialog dialog=prompts.remove(activity);if(dialog!=null)dialog.dismiss();}
    // Foreground recovery only. Scheduled shopping sync does not poll releases.
    static final long INTERVAL=5*60*1000L;
    static void request(Context c){
        if(Cloud.prefs(c).getString("origin","").isEmpty())return;
        long now=System.currentTimeMillis();
        if(now-Cloud.prefs(c).getLong("update_push_received",0)<60000)return;
        Cloud.prefs(c).edit().putLong("update_push_received",now).putBoolean("update_pending",true).commit();
        SyncJob.scheduleUpdate(c);
    }
    static File apk(Context c){return new File(c.getFilesDir(),"companion-update.apk");}
    static long version(PackageInfo p){return Build.VERSION.SDK_INT>=28?p.getLongVersionCode():p.versionCode;}
    static String hex(byte[] data){StringBuilder out=new StringBuilder();for(byte b:data)out.append(String.format("%02x",b&255));return out.toString();}
    static String hash(File file)throws Exception{
        MessageDigest digest=MessageDigest.getInstance("SHA-256");byte[] buffer=new byte[8192];int count;
        try(InputStream in=new FileInputStream(file)){while((count=in.read(buffer))!=-1)digest.update(buffer,0,count);}return hex(digest.digest());
    }
    static String certificate(PackageInfo p)throws Exception{
        android.content.pm.Signature[] signatures=Build.VERSION.SDK_INT>=28?p.signingInfo.getApkContentsSigners():p.signatures;
        if(signatures==null||signatures.length!=1)throw new Exception("Unexpected update signing identity");
        return hex(MessageDigest.getInstance("SHA-256").digest(signatures[0].toByteArray()));
    }
    static void validate(Context c,JSONObject release,File file)throws Exception{
        if(!hash(file).equals(release.getString("sha256")))throw new Exception("Update download did not pass its checksum");
        int flags=Build.VERSION.SDK_INT>=28?PackageManager.GET_SIGNING_CERTIFICATES:PackageManager.GET_SIGNATURES;
        PackageInfo installed=c.getPackageManager().getPackageInfo(c.getPackageName(),flags);
        PackageInfo candidate=c.getPackageManager().getPackageArchiveInfo(file.getAbsolutePath(),flags);
        if(candidate==null||!c.getPackageName().equals(candidate.packageName)||!candidate.packageName.equals(release.getString("package_name")))throw new Exception("This update is for a different app");
        if(version(candidate)!=release.getLong("version_code")||version(candidate)<=version(installed))throw new Exception("Update version is invalid or already installed");
        if(!certificate(installed).equals(certificate(candidate)))throw new Exception("Update signing key does not match this app");
    }
    static synchronized String check(Context c,boolean force)throws Exception{
        if(Cloud.prefs(c).getString("origin","").isEmpty())return "Connect to your server to check updates";
        if(!force&&System.currentTimeMillis()-Cloud.prefs(c).getLong("update_checked",0)<INTERVAL)return Cloud.prefs(c).getString("update_status","");
        JSONObject release=(JSONObject)Cloud.call(c,"release",null,false);
        long installed=version(c.getPackageManager().getPackageInfo(c.getPackageName(),0));
        if(release.getLong("version_code")<=installed){
            Cloud.prefs(c).edit().putBoolean("update_pending",false).putLong("update_checked",System.currentTimeMillis()).putString("update_status","App is up to date").remove("update_release").commit();apk(c).delete();return "App is up to date";
        }
        if(release.getInt("min_sdk")>Build.VERSION.SDK_INT)throw new Exception("Update requires a newer Android version");
        long size=release.getLong("size");if(size<1||size>64*1024*1024)throw new Exception("Unexpected update size");
        File target=apk(c);
        if(!target.isFile()||!hash(target).equals(release.getString("sha256"))){
            File temporary=new File(c.getFilesDir(),"companion-update.part");
            HttpURLConnection connection=(HttpURLConnection)new URL(Cloud.prefs(c).getString("origin","")+"/groceries/v1/mobile/companion.apk").openConnection();
            connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(10000);connection.setReadTimeout(30000);
            try{
                if(connection.getResponseCode()!=200)throw new Exception("Update download unavailable");
                long received=0;byte[] buffer=new byte[8192];int count;
                try(InputStream in=connection.getInputStream();OutputStream out=new FileOutputStream(temporary)){
                    while((count=in.read(buffer))!=-1){received+=count;if(received>size)throw new Exception("Update download exceeded its declared size");out.write(buffer,0,count);}
                }
                if(received!=size)throw new Exception("Incomplete update download");
                validate(c,release,temporary);
                if(!temporary.renameTo(target))throw new Exception("Unable to save downloaded update");
            }finally{connection.disconnect();temporary.delete();}
        }
        validate(c,release,target);
        String message="Update "+release.getString("version_name")+" downloaded · tap Install update";
        Cloud.prefs(c).edit().putBoolean("update_pending",false).putLong("update_checked",System.currentTimeMillis()).putString("update_status",message).putString("update_release",release.toString()).commit();notifyReady(c,release);return message;
    }
    static void notifyReady(Context c,JSONObject release)throws Exception{
        long code=release.getLong("version_code");if(Cloud.prefs(c).getLong("update_notified",0)==code)return;
        if(Build.VERSION.SDK_INT>=33&&c.checkSelfPermission("android.permission.POST_NOTIFICATIONS")!=PackageManager.PERMISSION_GRANTED)return;
        NotificationManager manager=(NotificationManager)c.getSystemService(Context.NOTIFICATION_SERVICE);
        NotificationStyle.channel(manager,"app-updates","App updates",NotificationManager.IMPORTANCE_DEFAULT,"New Assistant Companion versions, downloaded and verified");
        PendingIntent open=PendingIntent.getActivity(c,301,new Intent(c,MainActivity.class),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        String text="Version "+release.getString("version_name")+" is downloaded and verified. Open the app to install it.";
        manager.notify(301,new Notification.Builder(c,"app-updates").setSmallIcon(R.drawable.ic_stat_assistant).setColor(NativeNotifications.ACCENT).setLargeIcon(NotificationStyle.icon(c,"download",NotificationStyle.BRAND))
            .setContentTitle("Update ready").setContentText(text).setStyle(new Notification.BigTextStyle().bigText(text)).setSubText("App update").setShowWhen(true).setContentIntent(open).setAutoCancel(true).build());
        Cloud.prefs(c).edit().putLong("update_notified",code).commit();
    }
    static void install(Activity activity){
        try{
            JSONObject release=new JSONObject(Cloud.prefs(activity).getString("update_release","{}"));validate(activity,release,apk(activity));
            if(!activity.getPackageManager().canRequestPackageInstalls()){
                Cloud.prefs(activity).edit().putBoolean("update_install_pending",true).commit();
                activity.startActivityForResult(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,Uri.parse("package:"+activity.getPackageName())),INSTALL_PERMISSION);
                ToastMessage.show(activity,"Allow updates from Assistant Companion. Installation will open when you return.");return;
            }
            Cloud.prefs(activity).edit().putBoolean("update_install_pending",false).commit();
            Uri uri=Uri.parse("content://"+activity.getPackageName()+".updates/companion.apk");
            activity.startActivity(new Intent(Intent.ACTION_VIEW).setDataAndType(uri,"application/vnd.android.package-archive").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION));
        }catch(Exception error){ToastMessage.show(activity,error.getMessage());}
    }
    static void continueInstall(Activity activity){
        if(!Cloud.prefs(activity).getBoolean("update_install_pending",false))return;
        Cloud.prefs(activity).edit().putBoolean("update_install_pending",false).commit();
        if(activity.getPackageManager().canRequestPackageInstalls())install(activity);
        else ToastMessage.show(activity,"Update saved. You can install it later from Settings.");
    }
    /** One prompt for each verified, downloaded release; callbacks cannot nag repeatedly. */
    static boolean prompt(Activity activity){
        try{JSONObject release=new JSONObject(Cloud.prefs(activity).getString("update_release","{}"));long candidate=release.getLong("version_code");
            if(candidate<=version(activity.getPackageManager().getPackageInfo(activity.getPackageName(),0))||Cloud.prefs(activity).getLong("update_prompted_version",0)>=candidate)return false;
            if(!apk(activity).isFile())return false;
            Cloud.prefs(activity).edit().putLong("update_prompted_version",candidate).commit();
            AlertDialog dialog=new AlertDialog.Builder(activity).setTitle("Update ready").setMessage("Version "+release.getString("version_name")+" is ready to install. Your connection, lists and history will stay here.").setPositiveButton("Install",(d,w)->install(activity)).setNegativeButton("Later",null).create();
            prompts.put(activity,dialog);dialog.setOnDismissListener(d->{prompts.remove(activity);if(activity instanceof MainActivity)((MainActivity)activity).show();});dialog.show();return true;
        }catch(Exception ignored){return false;}
    }
    static final class ToastMessage{static void show(Context c,String value){android.widget.Toast.makeText(c,value,android.widget.Toast.LENGTH_LONG).show();}}
}
