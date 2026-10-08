package com.personalassistant.wakeprobe;

import android.app.role.RoleManager;
import android.content.*;
import android.content.pm.*;
import android.os.Build;
import android.service.voice.VoiceInteractionService;
import org.json.*;
import java.lang.reflect.*;
import java.util.List;

/** Optional capability probe. No recorder, network, enrollment or recognition starts. */
public final class ProbeService extends VoiceInteractionService {
    @Override public void onReady(){super.onReady();write(snapshot());}
    private JSONObject snapshot(){JSONObject out=new JSONObject();try{
        out.put("sdk",Build.VERSION.SDK_INT).put("hardware",Build.HARDWARE);
        out.put("assistant_role",getSystemService(RoleManager.class).isRoleHeld(RoleManager.ROLE_ASSISTANT));
        out.put("active_voice_service",isActiveService(this,new ComponentName(this,ProbeService.class)));
        JSONArray permissions=new JSONArray();PackageManager pm=getPackageManager();
        for(String name:new String[]{"CAPTURE_AUDIO_HOTWORD","MANAGE_HOTWORD_DETECTION","MANAGE_VOICE_KEYPHRASES","MANAGE_SOUND_TRIGGER"}){
            JSONObject p=new JSONObject().put("name",name).put("granted",checkSelfPermission("android.permission."+name)==PackageManager.PERMISSION_GRANTED);
            try{PermissionInfo info=pm.getPermissionInfo("android.permission."+name,0);p.put("protection_level",info.protectionLevel).put("protection_hex",Integer.toHexString(info.protectionLevel));}catch(Exception e){p.put("metadata_error",e.toString());}
            permissions.put(p);
        }out.put("permissions",permissions);
        JSONArray methods=new JSONArray();for(Method method:VoiceInteractionService.class.getMethods())if(method.getName().contains("Hotword")||method.getName().equals("listModuleProperties"))methods.put(method.toString());out.put("visible_framework_methods",methods);
        JSONArray supported=new JSONArray();for(String phrase:new String[]{"Hey Chat","Hey Google"}){
            JSONObject phraseResult=new JSONObject().put("phrase",phrase).put("locale","en-US");
            try{Method method=VoiceInteractionService.class.getMethod("isKeyphraseAndLocaleSupportedForHotword",String.class,java.util.Locale.class);phraseResult.put("supported",method.invoke(this,phrase,java.util.Locale.US));}
            catch(InvocationTargetException e){phraseResult.put("query_error",String.valueOf(e.getCause()));}
            catch(Exception e){phraseResult.put("query_error",e.toString());}supported.put(phraseResult);
        }out.put("enrollment_keyphrase_support",supported);
        // Reflection is a read-only capability test, not a hidden-API policy bypass.
        try{Method method=VoiceInteractionService.class.getMethod("listModuleProperties");Object modules=method.invoke(this);out.put("dsp_modules",String.valueOf(modules));if(modules instanceof List)out.put("dsp_module_count",((List<?>)modules).size());}
        catch(NoSuchMethodException e){out.put("dsp_query_status","Not accessible to this SDK app; this does not prove hardware absent");}
        catch(InvocationTargetException e){out.put("dsp_query_error",String.valueOf(e.getCause()));}
        catch(Exception e){out.put("dsp_query_error",e.toString());}
        JSONArray enrollment=new JSONArray();Intent query=new Intent("com.android.intent.action.MANAGE_VOICE_KEYPHRASES");
        for(ResolveInfo item:pm.queryIntentActivities(query,PackageManager.GET_META_DATA)){
            ActivityInfo activity=item.activityInfo;JSONObject p=new JSONObject().put("package",activity.packageName).put("activity",activity.name).put("required_permission",String.valueOf(activity.permission));
            ApplicationInfo app=pm.getApplicationInfo(activity.packageName,PackageManager.GET_META_DATA);p.put("system_app",(app.flags&ApplicationInfo.FLAG_SYSTEM)!=0);p.put("enrollment_metadata_present",app.metaData!=null&&app.metaData.containsKey("android.voice_enrollment"));enrollment.put(p);
        }out.put("visible_enrollment_providers",enrollment).put("audio_started",false).put("network_used",false);
    }catch(Exception e){try{out.put("error",e.toString());}catch(Exception ignored){}}return out;}
    private void write(JSONObject result){String text=result.toString();getSharedPreferences("probe",0).edit().putString("result",text).commit();android.util.Log.i("AssistantWakeProbe",text);try{java.io.FileOutputStream file=openFileOutput("hardware-probe.json",0);file.write(text.getBytes("UTF-8"));file.close();}catch(Exception ignored){}}
}
