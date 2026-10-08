package com.personalassistant.companion;
import android.content.Context;
import com.google.firebase.FirebaseApp;
import com.google.firebase.messaging.FirebaseMessaging;
import org.json.JSONObject;

/** Public Firebase app metadata is build configuration; paired bearer/token stay private. */
final class PushRegistration {
    static void clearLocal(Context c){Cloud.prefs(c).edit().remove("fcm_registered_token").remove("fcm_registered_phone").remove("push_cursor").remove("push_more").putString("push_status","Notifications disconnected").commit();}
    static synchronized void unregister(Context c)throws Exception{try{Cloud.call(c,"push/unregister",new JSONObject(),true);}finally{clearLocal(c);}}
    static void start(Context c){
        Context app=c.getApplicationContext();
        if(Cloud.prefs(app).getString("token","").isEmpty()||Cloud.prefs(app).getBoolean("push_signing_out",false))return;
        try{
            FirebaseApp initialized=FirebaseApp.initializeApp(app);
            if(initialized==null){Cloud.prefs(app).edit().putString("push_status","Push provider is not configured for this build").commit();return;}
            FirebaseMessaging.getInstance().getToken().addOnCompleteListener(task->{
                if(Cloud.prefs(app).getBoolean("push_signing_out",false)||Cloud.prefs(app).getString("token","").isEmpty())return;
                if(task.isSuccessful()&&task.getResult()!=null){Cloud.prefs(app).edit().putString("fcm_token",task.getResult()).commit();TaskSyncJob.schedule(app,false);}
                else Cloud.prefs(app).edit().putString("push_status","Notification registration will retry").commit();
            });
        }catch(Exception error){Cloud.prefs(app).edit().putString("push_status","Notification registration will retry").commit();}
    }
    static synchronized void sync(Context c)throws Exception{
        if(Cloud.prefs(c).getBoolean("push_signing_out",false)||Cloud.prefs(c).getString("token","").isEmpty())return;
        String token=Cloud.prefs(c).getString("fcm_token",""),phone=Cloud.prefs(c).getString("phone_id","");if(token.isEmpty()||(token.equals(Cloud.prefs(c).getString("fcm_registered_token",""))&&phone.equals(Cloud.prefs(c).getString("fcm_registered_phone",""))))return;
        Cloud.call(c,"push/register",new JSONObject().put("provider","fcm").put("token",token),true);
        Cloud.prefs(c).edit().putString("fcm_registered_token",token).putString("fcm_registered_phone",phone).putString("push_status","Native notifications connected").commit();
    }
}
