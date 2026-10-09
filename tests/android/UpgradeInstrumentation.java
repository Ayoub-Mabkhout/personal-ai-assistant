package com.personalassistant.companion;
import android.app.Instrumentation;
import android.content.*;
import android.os.*;

/** Framework-only signed upgrade check. Synthetic credentials never reach a server. */
public final class UpgradeInstrumentation extends Instrumentation {
    private boolean seed,unset;private int fromVersion=5,toVersion=6;
    static final String SNAPSHOT="{\"items\":[{\"id\":\"upgrade-item\",\"name\":\"Upgrade fixture\",\"version\":1,\"complete\":0}],\"recipes\":[]}",OUTBOX="[{\"id\":\"upgrade-stable-add\",\"operation\":\"add\",\"items\":[{\"name\":\"Pending fixture\",\"quantity\":\"\"}]}]";
    public void onCreate(Bundle args){super.onCreate(args);seed="seed".equals(args.getString("mode","check"));unset="unset".equals(args.getString("theme",""));fromVersion=Integer.parseInt(args.getString("from_version","5"));toVersion=Integer.parseInt(args.getString("to_version","6"));start();}
    public void onStart(){Bundle result=new Bundle();int outcome=0;try{if(!"ranchu".equals(Build.HARDWARE)&&!"goldfish".equals(Build.HARDWARE))throw new AssertionError("Disposable emulator required");Context context=getTargetContext();SharedPreferences prefs=context.getSharedPreferences("assistant",0);long version=context.getPackageManager().getPackageInfo(context.getPackageName(),0).getLongVersionCode();
        if(seed){if(version!=fromVersion||!prefs.getString("token","").isEmpty())throw new AssertionError("Unpaired previous-version fixture required");prefs.edit().clear().putString("token","upgrade-fixture-marker").putString("phone_id","upgrade-fixture-phone").putString("origin","").putString("snapshot",SNAPSHOT).putString("outbox",OUTBOX).putBoolean("wake_enabled",false).putBoolean("voice_live",false).putString("ui_theme","dark").commit();if(unset)prefs.edit().remove("ui_theme").commit();result.putBoolean("seeded_previous_version_synthetic_offline_state",true);}
        else{if(version!=toVersion)throw new AssertionError("Target upgrade version required");if(!prefs.getString("token","").equals("upgrade-fixture-marker")||!prefs.getString("phone_id","").equals("upgrade-fixture-phone")||!prefs.getString("snapshot","").equals(SNAPSHOT)||!prefs.getString("outbox","").equals(OUTBOX)||!(unset?!prefs.contains("ui_theme")&&AppUi.dark(context)==DaylightTheme.dark(System.currentTimeMillis()):prefs.getString("ui_theme","").equals("dark")))throw new AssertionError("Upgrade lost pairing/cache/pending IDs/preferences");result.putBoolean("pairing_cache_outbox_theme_preserved_on_upgrade",true);prefs.edit().clear().putBoolean("wake_enabled",false).putBoolean("voice_mic_active",false).commit();}
        result.putInt("from_version",fromVersion);result.putInt("to_version",toVersion);result.putBoolean("no_network_or_agent_dispatch",true);result.putString("stream",seed?"Previous-version offline synthetic pairing/list/outbox state saved.":"Signed update install preserved pairing, cached list, stable pending ID and theme; fixture cleaned.");
    }catch(Throwable error){result.putString("stream",android.util.Log.getStackTraceString(error));outcome=1;}finish(outcome,result);}
}
