package com.personalassistant.companion;

import android.content.*;
import android.os.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Records battery readings for BatteryUsage in a bounded private file. It never wakes the phone itself: readings ride on
 *  the running voice service (which already holds its wake lock), its screen and charger events, and the existing sync job. */
final class BatterySampler {
    static final long PERIOD_MS=15*60000L,DEBOUNCE_MS=30000L;static final int MAX_SAMPLES=2000;
    private static final String FILE="battery-samples.tsv";
    private static List<BatteryUsage.Sample> cache;private static long cacheStamp=-1;
    private BatterySampler(){}

    static synchronized void record(Context context){
        try{Context c=context.getApplicationContext();Intent battery=c.registerReceiver(null,new IntentFilter(Intent.ACTION_BATTERY_CHANGED));if(battery==null)return;
            int raw=battery.getIntExtra(BatteryManager.EXTRA_LEVEL,-1),scale=battery.getIntExtra(BatteryManager.EXTRA_SCALE,100);if(raw<0||scale<=0)return;
            BatteryManager manager=(BatteryManager)c.getSystemService(Context.BATTERY_SERVICE);long charge=manager==null?0:manager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CHARGE_COUNTER);if(charge==Integer.MIN_VALUE||charge<0)charge=0;
            PowerManager power=(PowerManager)c.getSystemService(Context.POWER_SERVICE);boolean screen=power==null||power.isInteractive();
            SharedPreferences p=Cloud.prefs(c);int mode=BatteryUsage.mode(AppUi.micActive(c),p.getBoolean("wake_enabled",false),p.getBoolean("voice_conversation_active",false),p.getBoolean("voice_conversation_mode",false),p.getString("task_voice",""));
            BatteryUsage.Sample sample=new BatteryUsage.Sample(System.currentTimeMillis(),SystemClock.elapsedRealtime(),SystemClock.uptimeMillis(),Math.round(raw*100f/scale),charge,battery.getIntExtra(BatteryManager.EXTRA_PLUGGED,0)!=0,screen,mode,p.getLong("voice_wake_count",0));
            List<BatteryUsage.Sample> all=samples(c);BatteryUsage.Sample last=all.isEmpty()?null:all.get(all.size()-1);
            if(last!=null&&sample.sameState(last)&&sample.elapsed-last.elapsed>=0&&sample.elapsed-last.elapsed<DEBOUNCE_MS)return;
            File file=new File(c.getFilesDir(),FILE);
            if(all.size()>=MAX_SAMPLES+200){StringBuilder kept=new StringBuilder();for(int i=all.size()-MAX_SAMPLES+1;i<all.size();i++)kept.append(all.get(i).line()).append('\n');kept.append(sample.line()).append('\n');
                File temp=new File(c.getFilesDir(),FILE+".tmp");try(OutputStream out=new FileOutputStream(temp)){out.write(kept.toString().getBytes(StandardCharsets.UTF_8));}if(!temp.renameTo(file))throw new IOException("rename");}
            else try(OutputStream out=new FileOutputStream(file,true)){out.write((sample.line()+"\n").getBytes(StandardCharsets.UTF_8));}
            cacheStamp=-1;
        }catch(Exception ignored){}
    }

    /** Parsed readings, cached until the file changes. */
    static synchronized List<BatteryUsage.Sample> samples(Context context){
        File file=new File(context.getApplicationContext().getFilesDir(),FILE);long stamp=file.exists()?file.length()*31+file.lastModified():0;
        if(cache!=null&&stamp==cacheStamp)return cache;List<String> lines=new ArrayList<>();
        if(file.exists())try(BufferedReader in=new BufferedReader(new InputStreamReader(new FileInputStream(file),StandardCharsets.UTF_8))){String line;while((line=in.readLine())!=null)lines.add(line);}catch(IOException ignored){}
        cache=Collections.unmodifiableList(BatteryUsage.parse(lines));cacheStamp=stamp;return cache;
    }
    static BatteryUsage.Report report(Context c){return BatteryUsage.report(samples(c));}
    static synchronized void reset(Context c){new File(c.getApplicationContext().getFilesDir(),FILE).delete();cache=null;cacheStamp=-1;record(c);}

    /** Lives inside VoiceService: screen and charger events plus a 15 minute reading while the service's wake lock is held. */
    static final class Watch {
        private final Context context;private final Handler main=new Handler(Looper.getMainLooper());private boolean on;
        private final Runnable tick=new Runnable(){public void run(){record(context);main.postDelayed(this,PERIOD_MS);}};
        private final BroadcastReceiver events=new BroadcastReceiver(){@Override public void onReceive(Context c,Intent i){record(context);}};
        Watch(Context context){this.context=context;}
        void start(){if(on)return;on=true;IntentFilter filter=new IntentFilter(Intent.ACTION_SCREEN_ON);filter.addAction(Intent.ACTION_SCREEN_OFF);filter.addAction(Intent.ACTION_POWER_CONNECTED);filter.addAction(Intent.ACTION_POWER_DISCONNECTED);
            if(Build.VERSION.SDK_INT>=33)context.registerReceiver(events,filter,Context.RECEIVER_NOT_EXPORTED);else context.registerReceiver(events,filter);
            record(context);main.postDelayed(tick,60000);}
        void stop(){if(!on)return;on=false;main.removeCallbacks(tick);try{context.unregisterReceiver(events);}catch(Exception ignored){}record(context);}
    }
}
