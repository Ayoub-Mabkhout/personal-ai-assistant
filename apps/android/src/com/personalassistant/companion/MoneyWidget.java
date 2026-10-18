package com.personalassistant.companion;

import android.app.PendingIntent;
import android.appwidget.*;
import android.content.*;
import android.graphics.*;
import android.graphics.drawable.*;
import android.widget.RemoteViews;
import org.json.*;
import java.text.NumberFormat;
import java.util.Locale;

/** Compact 2×2 free-to-spend snapshot; only cached published ledger data is shown. */
public final class MoneyWidget extends AppWidgetProvider {
    static void update(Context c){AppWidgetManager m=AppWidgetManager.getInstance(c);for(int id:m.getAppWidgetIds(new ComponentName(c,MoneyWidget.class)))m.updateAppWidget(id,build(c));}
    static RemoteViews build(Context c){RemoteViews v=new RemoteViews(c.getPackageName(),R.layout.money_widget);try{JSONObject s=new JSONObject(Cloud.prefs(c).getString("money_snapshot","{}"));long day=s.optLong("safe_per_day_cents",0);JSONArray a=s.optJSONArray("categories");String lead=a==null||a.length()==0?"No spending yet":a.optJSONObject(0).optString("name","Spending");v.setTextViewText(R.id.money_daily,fmt(day));v.setTextViewText(R.id.money_leading,lead);StringBuilder labels=new StringBuilder();long total=0;for(int i=0;a!=null&&i<Math.min(8,a.length());i++)total+=Math.max(0,a.optJSONObject(i).optLong("cents"));Bitmap strip=Bitmap.createBitmap(600,24,Bitmap.Config.ARGB_8888);Canvas canvas=new Canvas(strip);Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);float x=0;int[] colors={0xff8e6bff,0xffa35de2,0xffc46cf0,0xffd27cae,0xff7654ba,0xff58427d,0xffbd8cf0,0xff9878d2};for(int i=0;a!=null&&i<Math.min(8,a.length());i++){JSONObject row=a.optJSONObject(i);long cents=Math.max(0,row.optLong("cents"));if(cents==0||total<=0)continue;float next=x+600f*cents/total;paint.setColor(colors[i%colors.length]);canvas.drawRoundRect(x,0,next,24,7,7,paint);x=next;if(labels.length()>0)labels.append(" · ");labels.append(row.optString("name"));}v.setImageViewBitmap(R.id.money_strip,strip);v.setTextViewText(R.id.money_categories,labels.length()==0?"Categories appear after sync":labels.toString());if(Cloud.prefs(c).getString("token","").isEmpty())v.setTextViewText(R.id.money_status,"Pair the app to view Money");else v.setTextViewText(R.id.money_status,s.length()==0?"Waiting for ledger summary":"per day");}catch(Exception e){v.setTextViewText(R.id.money_daily,"—");v.setTextViewText(R.id.money_leading,"Waiting for data");v.setTextViewText(R.id.money_categories,"Categories appear after sync");}Intent i=new Intent(c,MainActivity.class).putExtra("open_tab","money").addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP);v.setOnClickPendingIntent(R.id.money_root,PendingIntent.getActivity(c,40,i,PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE));return v;}
    private static String fmt(long c){return NumberFormat.getCurrencyInstance(Locale.getDefault()).format(Math.max(0,c)/100.0);}
    @Override public void onUpdate(Context c,AppWidgetManager m,int[] ids){update(c);if(!Cloud.prefs(c).getString("token","").isEmpty())new Thread(()->{try{JSONObject envelope=(JSONObject)Cloud.call(c,"money",null,true),s=envelope.optJSONObject("summary");if(s!=null){Cloud.prefs(c).edit().putString("money_snapshot",s.toString()).apply();update(c);}}catch(Exception ignored){}}).start();}
}
