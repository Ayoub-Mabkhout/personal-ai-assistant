package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.content.pm.ShortcutInfo;
import android.content.pm.ShortcutManager;
import android.graphics.drawable.Icon;
import android.os.*;
import org.json.*;
import java.util.Arrays;

/** Opens the last task's conversation. Task details are private, so a locked phone is asked to unlock first. */
public final class LastTaskActivity extends Activity {
    @Override public void onCreate(Bundle state){
        super.onCreate(state);
        if(Build.VERSION.SDK_INT>=27)setShowWhenLocked(true);
        KeyguardManager keyguard=getSystemService(KeyguardManager.class);
        if(keyguard!=null&&keyguard.isKeyguardLocked())keyguard.requestDismissKeyguard(this,new KeyguardManager.KeyguardDismissCallback(){
            @Override public void onDismissSucceeded(){open();}
            @Override public void onDismissCancelled(){finish();}
            @Override public void onDismissError(){finish();}});
        else open();
    }
    private void open(){
        String[] task=last(this);Intent intent=new Intent(this,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP);
        if(task!=null)intent.putExtra("task_kind",task[0]).putExtra("task_id",task[1]);else intent.putExtra("open_tab","activity");
        startActivity(intent);finish();
    }
    /** The task last opened on this phone, or else the newest task in the cached history: {kind,id,title}. */
    static String[] last(Context c){
        android.content.SharedPreferences p=Cloud.prefs(c);String id=p.getString("last_task_id","");
        if(!id.isEmpty())return new String[]{p.getString("last_task_kind","agent"),id,p.getString("last_task_title","")};
        JSONArray items=NativeTasks.cachedHistory(c).optJSONArray("items");JSONObject first=items==null?null:items.optJSONObject(0);
        if(first==null||first.optString("id").isEmpty())return null;
        return new String[]{first.optString("kind","agent"),first.optString("id"),first.optString("request",first.optString("title",""))};
    }
    static void remember(Context c,String kind,String id,String title){
        Cloud.prefs(c).edit().putString("last_task_kind",kind).putString("last_task_id",id).putString("last_task_title",title==null?"":title).apply();shortcuts(c);
    }
    static android.graphics.Bitmap adaptive(Context c,int res){int size=(int)(108*c.getResources().getDisplayMetrics().density);android.graphics.drawable.Drawable d=c.getDrawable(res);
        android.graphics.Bitmap b=android.graphics.Bitmap.createBitmap(size,size,android.graphics.Bitmap.Config.ARGB_8888);android.graphics.Canvas canvas=new android.graphics.Canvas(b);
        if(d instanceof android.graphics.drawable.AdaptiveIconDrawable){android.graphics.drawable.AdaptiveIconDrawable a=(android.graphics.drawable.AdaptiveIconDrawable)d;for(android.graphics.drawable.Drawable layer:new android.graphics.drawable.Drawable[]{a.getBackground(),a.getForeground()}){if(layer==null)continue;layer.setBounds(0,0,size,size);layer.draw(canvas);}}
        else{d.setBounds(0,0,size,size);d.draw(canvas);}return b;}
    /** Long-press shortcuts on the app icon: New task, and Resume with the last task's own title. */
    static void shortcuts(Context c){
        try{ShortcutManager manager=c.getSystemService(ShortcutManager.class);if(manager==null)return;
            ShortcutInfo create=new ShortcutInfo.Builder(c,"new_task").setShortLabel("New task").setLongLabel("New task")
                .setIcon(Icon.createWithAdaptiveBitmap(adaptive(c,R.mipmap.ic_new_task))).setIntent(new Intent(c,QuickTaskActivity.class).setAction(Intent.ACTION_VIEW)).setRank(0).build();
            String[] task=last(c);String title=task==null||task[2].trim().isEmpty()?"Last task":task[2].trim();
            String shortTitle=title.length()>24?title.substring(0,23)+"…":title,longTitle=title.length()>40?title.substring(0,39)+"…":title;
            ShortcutInfo resume=new ShortcutInfo.Builder(c,"last_task").setShortLabel(shortTitle).setLongLabel("Resume: "+longTitle)
                .setIcon(Icon.createWithAdaptiveBitmap(adaptive(c,R.mipmap.ic_last_task))).setIntent(new Intent(c,LastTaskActivity.class).setAction(Intent.ACTION_VIEW)).setRank(1).build();
            manager.setDynamicShortcuts(Arrays.asList(create,resume));
        }catch(Exception ignored){}
    }
}
