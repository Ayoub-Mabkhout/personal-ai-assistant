package com.personalassistant.companion;

import android.content.*;

/** Push is a hint only. Fetch the release from the paired HTTPS origin. */
public class UpdateReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context,Intent intent){
        if("com.personalassistant.companion.RELEASE_PUBLISHED".equals(intent.getAction()))Updates.request(context);
    }
}
