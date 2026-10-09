package com.personalassistant.companion;

import android.app.*;
import android.appwidget.*;
import android.content.*;
import android.content.res.Configuration;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.widget.RemoteViews;
import org.json.*;

public class ShoppingWidget extends AppWidgetProvider {
    /** Add opens MainActivity with these extras so it can land on the Shopping tab and focus the add field; builds that ignore them open the default tab. */
    static final String EXTRA_TAB="open_tab",EXTRA_FOCUS_ADD="focus_add_item";
    static PendingIntent open(Context c){return PendingIntent.getActivity(c,0,new Intent(c,MainActivity.class),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);}
    static PendingIntent add(Context c){
        Intent i=new Intent(c,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP).putExtra(EXTRA_TAB,"shopping").putExtra(EXTRA_FOCUS_ADD,true);
        return PendingIntent.getActivity(c,1,i,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
    }
    /** Rows that fit the widget's current height; the header, status lines and buttons take about 150 dp. */
    private static int rowsFit(Context c,AppWidgetManager manager,int widget){
        Bundle options=manager.getAppWidgetOptions(widget);boolean landscape=c.getResources().getConfiguration().orientation==Configuration.ORIENTATION_LANDSCAPE;
        int height=options==null?0:options.getInt(landscape?AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT:AppWidgetManager.OPTION_APPWIDGET_MAX_HEIGHT,0);
        return height<=0?6:Math.max(1,Math.min(6,(height-150)/48));
    }
    static PendingIntent action(Context c,String verb,String id,int version){
        Intent i=new Intent(c,ShoppingWidget.class).setAction(verb).setData(Uri.parse("assistantwidget://"+verb+"/"+id)).putExtra("id",id).putExtra("version",version);
        return PendingIntent.getBroadcast(c,0,i,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
    }
    static void update(Context c){
        AppWidgetManager manager=AppWidgetManager.getInstance(c);int[] ids=manager.getAppWidgetIds(new ComponentName(c,ShoppingWidget.class));
        for(int widget:ids)manager.updateAppWidget(widget,build(c,rowsFit(c,manager,widget)));
    }
    static RemoteViews build(Context c,int fit){
        RemoteViews views=new RemoteViews(c.getPackageName(),R.layout.widget);views.removeAllViews(R.id.rows);
        try{
            JSONArray rows=Cloud.pendingList(c).optJSONArray("items");int count=0;
            if(rows!=null)for(int i=0;i<rows.length();i++){
                JSONObject row=rows.getJSONObject(i);if(row.optInt("complete")!=0)continue;count++;
                if(count<=fit){
                    RemoteViews item=new RemoteViews(c.getPackageName(),R.layout.row);String quantity=row.optString("quantity").trim(),name=row.getString("name");item.setTextViewText(R.id.item,name);
                    if(!quantity.isEmpty()){item.setTextViewText(R.id.qty,quantity);item.setViewVisibility(R.id.qty,View.VISIBLE);}
                    if(row.optInt("version")>0){item.setOnClickPendingIntent(R.id.row,action(c,"complete",row.getString("id"),row.getInt("version")));item.setContentDescription(R.id.row,"Mark "+(quantity.isEmpty()?"":quantity+" ")+name+" as bought");}
                    views.addView(R.id.rows,item);
                }
            }
            String status=Cloud.prefs(c).getString("status","Pair to sync");int pending=Cloud.queue(c).length();
            if(pending>0)status=pending+(pending==1?" change":" changes")+" saved on phone · "+status;
            if(count>fit)status+=" · "+(count-fit)+(count-fit==1?" more item":" more items");
            if(Cloud.prefs(c).getLong("synced",0)>0)status+=" · "+android.text.format.DateFormat.format("HH:mm",Cloud.prefs(c).getLong("synced",0));
            views.setTextViewText(R.id.status,status);
            views.setViewVisibility(R.id.empty,count==0?View.VISIBLE:View.GONE);
            if(count==0)views.setTextViewText(R.id.empty,Cloud.prefs(c).getString("token","").isEmpty()?"Connect your phone in the app to see your list.":"Nothing to buy right now.");
        }catch(Exception e){views.setTextViewText(R.id.status,"Open the app to recover saved changes");}
        views.setOnClickPendingIntent(R.id.header,open(c));views.setOnClickPendingIntent(R.id.title,open(c));views.setOnClickPendingIntent(R.id.add,add(c));views.setOnClickPendingIntent(R.id.refresh,action(c,"refresh","refresh",0));
        return views;
    }
    @Override public void onAppWidgetOptionsChanged(Context c,AppWidgetManager m,int id,Bundle options){super.onAppWidgetOptionsChanged(c,m,id,options);update(c);}
    @Override public void onUpdate(Context c,AppWidgetManager m,int[] ids){update(c);SyncJob.schedule(c,true);SyncJob.schedule(c,false);}
    @Override public void onReceive(Context c,Intent i){
        super.onReceive(c,i);
        try{if("complete".equals(i.getAction()))Cloud.enqueue(c,new JSONObject().put("operation","complete").put("target",i.getStringExtra("id")).put("version",i.getIntExtra("version",0)).put("complete",true));
            else if("refresh".equals(i.getAction()))SyncJob.schedule(c,false);
        }catch(Exception e){Cloud.prefs(c).edit().putString("status",e.getMessage()).commit();update(c);}
    }
}
