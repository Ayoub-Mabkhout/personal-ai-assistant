package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.*;
import org.json.*;
import java.util.UUID;

/** Termux's official RUN_COMMAND contract. Persist issuance before side effects. */
final class TermuxBridge {
    static final String PERMISSION="com.termux.permission.RUN_COMMAND";
    static final String PREFIX="/data/data/com.termux/files/usr/bin/";
    static boolean installed(Context c){try{c.getPackageManager().getPackageInfo("com.termux",0);return true;}catch(Exception e){return false;}}
    static boolean permission(Context c){return c.checkSelfPermission(PERMISSION)==PackageManager.PERMISSION_GRANTED;}
    static boolean enabled(Context c){return Cloud.prefs(c).getBoolean("termux_enabled",false);}
    static String status(Context c){return !installed(c)?"Install Termux":!permission(c)?"Permission needed":!enabled(c)?"Off":"Ready";}
    private static String key(String id){return "termux_run:"+id;}
    private static synchronized JSONObject read(Context c,String id)throws Exception{return new JSONObject(Cloud.prefs(c).getString(key(id),"{}"));}
    private static synchronized void save(Context c,String id,JSONObject r)throws Exception{if(!Cloud.prefs(c).edit().putString(key(id),r.toString()).commit())throw new Exception("Could not save phone execution state");}
    static Intent commandIntent(Context c,String id,JSONObject r,JSONObject request)throws Exception{
        Intent callback=new Intent(c,TermuxResultReceiver.class).setAction("com.personalassistant.companion.TERMUX_RESULT").setData(Uri.parse("personalassistant://termux-result/"+id+"/"+r.getString("claim")));
        PendingIntent result=PendingIntent.getBroadcast(c,0,callback,PendingIntent.FLAG_ONE_SHOT|(Build.VERSION.SDK_INT>=31?PendingIntent.FLAG_MUTABLE:0));
        return new Intent("com.termux.RUN_COMMAND").setClassName("com.termux","com.termux.app.RunCommandService")
            .putExtra("com.termux.RUN_COMMAND_PATH",PREFIX+"timeout")
            .putExtra("com.termux.RUN_COMMAND_ARGUMENTS",new String[]{"-k","5",String.valueOf(request.optInt("timeout",60)),PREFIX+"bash","-lc",request.getString("script")})
            .putExtra("com.termux.RUN_COMMAND_WORKDIR",request.optString("workdir","~/"))
            .putExtra("com.termux.RUN_COMMAND_BACKGROUND",true)
            .putExtra("com.termux.RUN_COMMAND_COMMAND_LABEL",request.optString("label","Phone command"))
            .putExtra("com.termux.RUN_COMMAND_PENDING_INTENT",result);
    }
    static void issue(Context c,String id,JSONObject r,JSONObject request)throws Exception{
        // Lost callbacks/restarts must not replay a potentially executed command.
        r.put("state","issued").put("started",System.currentTimeMillis()).put("deadline",System.currentTimeMillis()+(request.optInt("timeout",60)+40)*1000L);save(c,id,r);
        try{c.startService(commandIntent(c,id,r,request));Cloud.prefs(c).edit().putString("termux_status","Running: "+request.optString("label","Phone command")).commit();}
        catch(Exception e){r.put("result",result(r,"failed","","",null,"Termux did not start: "+e.getMessage(),false)).put("state","result");save(c,id,r);}
    }
    static JSONObject result(JSONObject r,String state,String out,String err,Integer exit,String error,boolean truncated)throws Exception{
        return new JSONObject().put("claim",r.getString("claim")).put("state",state).put("stdout",clip(out,32000)).put("stderr",clip(err,32000)).put("exit_code",exit==null?JSONObject.NULL:exit).put("error",clip(error,2000)).put("truncated",truncated||out.length()>32000||err.length()>32000);
    }
    static String clip(String s,int limit){return s==null?"":s.substring(0,Math.min(limit,s.length()));}
    static synchronized void received(Context c,Intent intent)throws Exception{
        Uri u=intent.getData();if(u==null||u.getPathSegments().size()!=2)return;String id=u.getPathSegments().get(0),claim=u.getPathSegments().get(1);JSONObject r=read(c,id);
        if(!claim.equals(r.optString("claim")))return;
        Bundle b=intent.getBundleExtra("result");if(b==null)return;
        String out=b.getString("stdout",""),err=b.getString("stderr",""),error=b.getString("errmsg","");int exit=b.getInt("exitCode",-1),internal=b.getInt("err",-1);
        boolean truncated=out.length()>32000||err.length()>32000;
        try{truncated|=Long.parseLong(String.valueOf(b.get("stdout_original_length")))>out.length()||Long.parseLong(String.valueOf(b.get("stderr_original_length")))>err.length();}catch(Exception ignored){}
        JSONObject receipt=result(r,exit==0&&internal==-1?"completed":"failed",out,err,exit,error,truncated);
        r.put("state","result").put("result",receipt);save(c,id,r);
        Cloud.prefs(c).edit().putString("termux_status",receipt.getString("state")+": "+r.optString("label","Phone command")).putString("termux_last_result",receipt.toString()).commit();
        TermuxSyncJob.schedule(c,false);NativeTasks.changed(c);
    }
    static synchronized void flush(Context c)throws Exception{
        String origin=Cloud.prefs(c).getString("origin",""),phone=Cloud.prefs(c).getString("phone_id","");
        for(String k:Cloud.prefs(c).getAll().keySet())if(k.startsWith("termux_run:")){
            String id=k.substring(11);JSONObject r=read(c,id);
            if(!r.optString("origin").equals(origin)||!r.optString("phone").equals(phone))continue;
            if("issued".equals(r.optString("state"))&&System.currentTimeMillis()>r.optLong("deadline",Long.MAX_VALUE)){
                r.put("state","result").put("result",result(r,"uncertain","","",null,"No Termux result arrived. Not automatically replayed.",false));save(c,id,r);
            }
            if("result".equals(r.optString("state"))&&!r.optBoolean("local")){
                Cloud.call(c,"termux/commands/"+id+"/result",r.getJSONObject("result"),true);r.put("state","acked");save(c,id,r);
            }
        }
    }
    static void sync(Context c)throws Exception{
        if(Cloud.prefs(c).getString("token","").isEmpty())return;
        try{
            flush(c);
            Cloud.call(c,"termux/capabilities",new JSONObject().put("installed",installed(c)).put("permission",permission(c)).put("enabled",enabled(c)),true);
            if(!installed(c)||!permission(c)||!enabled(c))return;
            JSONArray commands=(JSONArray)Cloud.call(c,"termux/pending",null,true);
            for(int i=0;i<commands.length();i++){
                JSONObject cmd=commands.getJSONObject(i),request=cmd.getJSONObject("request");String id=cmd.getString("id");JSONObject r=read(c,id);
                if(!r.optString("state").isEmpty()&&!"prepared".equals(r.optString("state")))continue;
                if(r.optString("state").isEmpty()){
                    // A server-side running command with no local ledger is uncertain, never replayable.
                    if(!"queued".equals(cmd.optString("state")))continue;
                    r.put("claim",UUID.randomUUID().toString()).put("state","prepared").put("origin",Cloud.prefs(c).getString("origin","")).put("phone",Cloud.prefs(c).getString("phone_id","")).put("label",request.optString("label"));save(c,id,r);
                }
                JSONObject claimed=(JSONObject)Cloud.call(c,"termux/commands/"+id+"/claim",new JSONObject().put("claim",r.getString("claim")),true);
                if("running".equals(claimed.optString("state")))issue(c,id,r,request);
            }
            flush(c);
        }catch(Exception e){if(!String.valueOf(e.getMessage()).contains("(404)"))throw e;}
    }
    static void test(Context c)throws Exception{
        if(!installed(c)||!permission(c))throw new Exception("Install Termux and grant Run commands in Termux first");
        String id="test_"+UUID.randomUUID().toString();JSONObject r=new JSONObject().put("local",true).put("claim",UUID.randomUUID().toString()).put("label","Connection test").put("origin",Cloud.prefs(c).getString("origin","")).put("phone",Cloud.prefs(c).getString("phone_id",""));
        issue(c,id,r,new JSONObject().put("script","printf 'Companion connected to Termux\\n'; uname -m").put("timeout",10).put("label","Connection test"));
    }
}
