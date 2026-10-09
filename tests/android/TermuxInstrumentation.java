package com.personalassistant.companion;
import android.app.Instrumentation;
import android.content.*;
import android.os.*;
import org.json.*;

/** Real Termux integration on a disposable emulator; no network or owner account. */
public class TermuxInstrumentation extends Instrumentation {
    @Override public void onCreate(Bundle b){super.onCreate(b);start();}
    @Override public void onStart(){
        Context c=getTargetContext();SharedPreferences p=Cloud.prefs(c);String oldOrigin=p.getString("origin",""),oldToken=p.getString("token","");Bundle report=new Bundle();
        try{
            p.edit().remove("token").remove("origin").remove("termux_last_result").commit();
            if(!TermuxBridge.installed(c)||!TermuxBridge.permission(c))throw new Exception("Termux and RUN_COMMAND permission required");
            TermuxBridge.test(c);long until=SystemClock.elapsedRealtime()+20000;String result="";
            while(SystemClock.elapsedRealtime()<until){result=p.getString("termux_last_result","");if(!result.isEmpty())break;SystemClock.sleep(100);}
            JSONObject r=new JSONObject(result);
            if(!r.getString("stdout").contains("Companion connected to Termux")||r.getInt("exit_code")!=0||!r.getString("state").equals("completed"))throw new Exception("Unexpected Termux result: "+r);
            report.putString("proof",r.toString());finish(-1,report);
        }catch(Exception e){report.putString("error",e.toString());finish(0,report);}
        finally{p.edit().putString("token",oldToken).putString("origin",oldOrigin).commit();}
    }
}
