package com.personalassistant.companion;

import android.content.*;
import android.graphics.Insets;
import android.os.Build;
import android.view.*;
import android.widget.*;
import java.util.*;

/** Conversation pieces of the task screens; a long press on a bubble copies its text. */
final class TaskViews {
    private TaskViews(){}

    static long day(long at){Calendar c=Calendar.getInstance();c.setTimeInMillis(at);return c.get(Calendar.YEAR)*1000L+c.get(Calendar.DAY_OF_YEAR);}
    /** Yesterday is a calendar day before now, which is not always 24 hours earlier around a daylight saving change. */
    static String dayLabel(long at,long now){
        Calendar before=Calendar.getInstance();before.setTimeInMillis(now);before.add(Calendar.DAY_OF_YEAR,-1);
        String date=AppUi.date(at);return day(at)==day(now)?"Today · "+date:day(at)==day(before.getTimeInMillis())?"Yesterday · "+date:date;
    }

    static int[] bars(WindowInsets insets){
        if(Build.VERSION.SDK_INT>=30){Insets s=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.displayCutout()),k=insets.getInsets(WindowInsets.Type.ime());return new int[]{s.left,s.top,s.right,Math.max(s.bottom,k.bottom)};}
        return new int[]{insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom()};
    }

    static void copy(Context context,String text){
        ClipboardManager clipboard=(ClipboardManager)context.getSystemService(Context.CLIPBOARD_SERVICE);if(clipboard==null)return;
        clipboard.setPrimaryClip(ClipData.newPlainText("Task message",text));
        if(Build.VERSION.SDK_INT<33)Toast.makeText(context,"Copied",Toast.LENGTH_SHORT).show();
    }

    static LinearLayout bubble(AppUi ui,String text,boolean user,String label,long at,View badge){
        if(text==null||text.isEmpty())return null;
        LinearLayout item=ui.column();item.setGravity(user?Gravity.END:Gravity.START);
        LinearLayout box=ui.column();box.setPadding(ui.dp(14),ui.dp(10),ui.dp(14),ui.dp(11));box.setBackground(ui.bubble(user));
        TextView words=ui.body(text);words.setMaxWidth(Math.min(Math.round(ui.context.getResources().getDisplayMetrics().widthPixels*.84f),ui.dp(520))-ui.dp(28)-(user?0:ui.dp(36)));box.addView(words);
        box.setLongClickable(true);box.setOnLongClickListener(v->{copy(ui.context,text);return true;});
        item.addView(box,new LinearLayout.LayoutParams(-2,-2));
        String stamp=AppUi.stamp(at);TextView meta=ui.type(stamp.isEmpty()?label:label+" · "+stamp,12,16,500,0,ui.muted);meta.setPadding(ui.dp(6),0,ui.dp(6),0);LinearLayout.LayoutParams mp=new LinearLayout.LayoutParams(-2,-2);mp.topMargin=ui.dp(5);item.addView(meta,mp);
        if(badge!=null){LinearLayout.LayoutParams bp=new LinearLayout.LayoutParams(-2,-2);bp.topMargin=ui.dp(6);item.addView(badge,bp);}
        LinearLayout.LayoutParams op=new LinearLayout.LayoutParams(-1,-2);op.bottomMargin=ui.dp(14);
        if(user){item.setLayoutParams(op);return item;}
        LinearLayout outer=ui.row();outer.setGravity(Gravity.START|Gravity.TOP);outer.setLayoutParams(op);
        LinearLayout.LayoutParams ap=new LinearLayout.LayoutParams(ui.dp(28),ui.dp(28));ap.topMargin=ui.dp(4);outer.addView(ui.avatar(),ap);
        LinearLayout.LayoutParams cp=new LinearLayout.LayoutParams(-2,-2);cp.leftMargin=ui.dp(8);outer.addView(item,cp);
        return outer;
    }

    static View separator(AppUi ui,long at){
        LinearLayout row=ui.row();row.setPadding(0,ui.dp(4),0,ui.dp(16));
        row.addView(line(ui),new LinearLayout.LayoutParams(0,Math.max(1,ui.dp(1)),1));TextView name=ui.label(dayLabel(at,System.currentTimeMillis()));name.setPadding(ui.dp(12),0,ui.dp(12),0);row.addView(name);row.addView(line(ui),new LinearLayout.LayoutParams(0,Math.max(1,ui.dp(1)),1));
        return row;
    }
    private static View line(AppUi ui){View v=new View(ui.context);v.setBackgroundColor(ui.stroke);return v;}
}
