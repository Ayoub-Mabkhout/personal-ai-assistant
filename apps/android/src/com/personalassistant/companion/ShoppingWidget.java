package com.personalassistant.companion;

import android.app.*;
import android.appwidget.*;
import android.content.*;
import android.net.Uri;
import android.widget.RemoteViews;
import org.json.*;

public class ShoppingWidget extends AppWidgetProvider {
    static PendingIntent open(Context c){return PendingIntent.getActivity(c,0,new Intent(c,MainActivity.class),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);}
    static PendingIntent action(Context c,String verb,String id,int version){
        Intent i=new Intent(c,ShoppingWidget.class).setAction(verb).setData(Uri.parse("assistantwidget://"+verb+"/"+id)).putExtra("id",id).putExtra("version",version);
        return PendingIntent.getBroadcast(c,0,i,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
    }
    static void update(Context c){
        AppWidgetManager manager=AppWidgetManager.getInstance(c);int[] ids=manager.getAppWidgetIds(new ComponentName(c,ShoppingWidget.class));
        for(int widget:ids){
            RemoteViews views=new RemoteViews(c.getPackageName(),R.layout.widget);views.removeAllViews(R.id.rows);
            try{
                JSONArray rows=Cloud.pendingList(c).optJSONArray("items");int count=0;
                if(rows!=null)for(int i=0;i<rows.length();i++){
                    JSONObject row=rows.getJSONObject(i);if(row.optInt("complete")!=0)continue;count++;
                    if(count<=6){RemoteViews item=new RemoteViews(c.getPackageName(),R.layout.row);item.setTextViewText(R.id.item,"○  "+row.optString("quantity")+" "+row.getString("name"));if(row.optInt("version")>0)item.setOnClickPendingIntent(R.id.item,action(c,"complete",row.getString("id"),row.getInt("version")));views.addView(R.id.rows,item);}
                }
                String status=Cloud.prefs(c).getString("status","Pair to sync");int pending=Cloud.queue(c).length();
                if(pending>0)status=pending+" changes saved on phone · "+status;
                if(count>6)status+=" · "+(count-6)+" more items";
                if(Cloud.prefs(c).getLong("synced",0)>0)status+=" · "+android.text.format.DateFormat.format("HH:mm",Cloud.prefs(c).getLong("synced",0));
                views.setTextViewText(R.id.status,status);
            }catch(Exception e){views.setTextViewText(R.id.status,"Open the app to recover saved changes");}
            views.setOnClickPendingIntent(R.id.title,open(c));views.setOnClickPendingIntent(R.id.add,open(c));views.setOnClickPendingIntent(R.id.refresh,action(c,"refresh","refresh",0));
            manager.updateAppWidget(widget,views);
        }
    }
    @Override public void onUpdate(Context c,AppWidgetManager m,int[] ids){update(c);SyncJob.schedule(c,true);SyncJob.schedule(c,false);}
    @Override public void onReceive(Context c,Intent i){
        super.onReceive(c,i);
        try{if("complete".equals(i.getAction()))Cloud.enqueue(c,new JSONObject().put("operation","complete").put("target",i.getStringExtra("id")).put("version",i.getIntExtra("version",0)).put("complete",true));
            else if("refresh".equals(i.getAction()))SyncJob.schedule(c,false);
        }catch(Exception e){Cloud.prefs(c).edit().putString("status",e.getMessage()).commit();update(c);}
    }
}
