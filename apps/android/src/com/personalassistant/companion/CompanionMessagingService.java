package com.personalassistant.companion;

import com.google.firebase.FirebaseApp;
import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

/** FCM hints fetch authenticated durable events and open native task screens. */
public class CompanionMessagingService extends FirebaseMessagingService {
    @Override public void onCreate(){super.onCreate();FirebaseApp.initializeApp(this);}
    @Override public void onNewToken(String token){
        Cloud.prefs(this).edit().putString("fcm_token",token).remove("fcm_registered_token").commit();
        if(!Cloud.prefs(this).getString("token","").isEmpty()&&!Cloud.prefs(this).getBoolean("push_signing_out",false))TaskSyncJob.schedule(this,false);
    }
    @Override public void onMessageReceived(RemoteMessage message){
        if(!"assistant_event".equals(message.getData().get("type")))return;
        if(Cloud.prefs(this).getString("token","").isEmpty()||Cloud.prefs(this).getBoolean("push_signing_out",false))return;
        // Job is durable before the short push callback tries delivery. On failure,
        // the server journal and recovery cursor prevent lost task updates.
        TaskSyncJob.schedule(this,false);
        try{NativeNotifications.sync(this);}catch(Exception error){Cloud.prefs(this).edit().putString("push_status","Update saved on the server · retrying delivery").commit();}
    }
}
