package com.personalassistant.companion;

import android.app.Activity;
import android.os.Build;
import android.window.OnBackInvokedDispatcher;

/** Share the same navigation between the Android back gesture and legacy button. */
final class AppBack {
    private AppBack(){}
    static void install(Activity activity,Runnable back){
        if(Build.VERSION.SDK_INT>=33)activity.getOnBackInvokedDispatcher().registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT,back::run);
    }
}
