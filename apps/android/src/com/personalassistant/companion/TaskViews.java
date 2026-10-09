package com.personalassistant.companion;

import android.content.*;
import android.content.res.ColorStateList;
import android.graphics.*;
import android.graphics.drawable.*;
import android.os.Build;
import android.view.*;
import android.widget.*;
import java.text.SimpleDateFormat;
import java.util.*;

/** Conversation pieces of the task screens; a long press on a bubble copies its text. */
final class TaskViews {
    private TaskViews(){}

    /** Same stamp as the voice chat ("Oct 8, 21:14"); the year appears only for entries from an earlier year. */
    static String when(long at){if(at<=0)return "";return new SimpleDateFormat(year(at)==year(System.currentTimeMillis())?"MMM d, HH:mm":"MMM d, yyyy, HH:mm",Locale.getDefault()).format(new Date(at));}
    private static int year(long at){Calendar c=Calendar.getInstance();c.setTimeInMillis(at);return c.get(Calendar.YEAR);}
    static long day(long at){Calendar c=Calendar.getInstance();c.setTimeInMillis(at);return c.get(Calendar.YEAR)*1000L+c.get(Calendar.DAY_OF_YEAR);}
    private static String dayLabel(long at){
        long now=System.currentTimeMillis();String date=new SimpleDateFormat(year(at)==year(now)?"MMM d":"MMM d, yyyy",Locale.getDefault()).format(new Date(at));
        return day(at)==day(now)?"Today · "+date:day(at)==day(now-86400000L)?"Yesterday · "+date:date;
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

    /** Same bubble as the voice chat: right-aligned accent-soft for the user, left-aligned surface with the aurora avatar for the assistant. */
    static LinearLayout bubble(AppUi ui,String text,boolean user,String label,long at,View badge){
        if(text==null||text.isEmpty())return null;
        LinearLayout item=ui.column();item.setGravity(user?Gravity.END:Gravity.START);
        LinearLayout box=ui.column();box.setPadding(ui.dp(14),ui.dp(10),ui.dp(14),ui.dp(11));box.setBackground(ui.bubble(user));
        TextView words=ui.body(text);words.setMaxWidth(Math.min(Math.round(ui.context.getResources().getDisplayMetrics().widthPixels*.84f),ui.dp(520))-ui.dp(28)-(user?0:ui.dp(36)));box.addView(words);
        box.setLongClickable(true);box.setOnLongClickListener(v->{copy(ui.context,text);return true;});
        item.addView(box,new LinearLayout.LayoutParams(-2,-2));
        String stamp=when(at);TextView meta=ui.type(stamp.isEmpty()?label:label+" · "+stamp,12,16,500,0,ui.muted);meta.setPadding(ui.dp(6),0,ui.dp(6),0);LinearLayout.LayoutParams mp=new LinearLayout.LayoutParams(-2,-2);mp.topMargin=ui.dp(5);item.addView(meta,mp);
        if(badge!=null){LinearLayout.LayoutParams bp=new LinearLayout.LayoutParams(-2,-2);bp.topMargin=ui.dp(6);item.addView(badge,bp);}
        LinearLayout.LayoutParams op=new LinearLayout.LayoutParams(-1,-2);op.bottomMargin=ui.dp(14);
        if(user){item.setLayoutParams(op);return item;}
        LinearLayout outer=ui.row();outer.setGravity(Gravity.START|Gravity.TOP);outer.setLayoutParams(op);
        ImageView avatar=new ImageView(ui.context);avatar.setImageDrawable(ui.glyph("star",ui.onAccent,14));avatar.setScaleType(ImageView.ScaleType.CENTER);avatar.setBackground(ui.aurora(-1,130,false));avatar.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        LinearLayout.LayoutParams ap=new LinearLayout.LayoutParams(ui.dp(28),ui.dp(28));ap.topMargin=ui.dp(4);outer.addView(avatar,ap);
        LinearLayout.LayoutParams cp=new LinearLayout.LayoutParams(-2,-2);cp.leftMargin=ui.dp(8);outer.addView(item,cp);
        return outer;
    }

    static View separator(AppUi ui,long at){
        LinearLayout row=ui.row();row.setPadding(0,ui.dp(4),0,ui.dp(16));
        row.addView(line(ui),new LinearLayout.LayoutParams(0,Math.max(1,ui.dp(1)),1));TextView name=ui.label(dayLabel(at));name.setPadding(ui.dp(12),0,ui.dp(12),0);row.addView(name);row.addView(line(ui),new LinearLayout.LayoutParams(0,Math.max(1,ui.dp(1)),1));
        return row;
    }
    private static View line(AppUi ui){View v=new View(ui.context);v.setBackgroundColor(ui.stroke);return v;}

    /** A Button rather than an ImageButton: task_followup_send is cast to Button by callers and tests. */
    static final class SendFab extends Button {
        final AppUi ui;final AppUi.GlyphDrawable glyph;final float lift;
        SendFab(AppUi ui,String description,Runnable action){
            super(ui.context);this.ui=ui;glyph=new AppUi.GlyphDrawable("send",ui.onAccent,ui.dp(24));lift=ui.dpf(5);
            setStateListAnimator(null);setAllCaps(false);setText("");setPadding(0,0,0,0);setMinWidth(ui.dp(52));setMinimumWidth(ui.dp(52));setMinHeight(ui.dp(52));setMinimumHeight(ui.dp(52));
            setBackground(new RippleDrawable(ColorStateList.valueOf(0x38FFFFFF),ui.aurora(-1,130,false),ui.pillMask()));ui.lift(this,-1,5,false);setContentDescription(description);setOnClickListener(v->action.run());AppUi.press(this);
        }
        @Override public void setEnabled(boolean on){super.setEnabled(on);if(glyph==null)return;setAlpha(on?1f:.5f);setElevation(on?lift:0);}
        @Override protected void onDraw(Canvas c){
            super.onDraw(c);int s=glyph.getIntrinsicWidth(),x=(getWidth()-s)/2,y=(getHeight()-s)/2;glyph.setBounds(x,y,x+s,y+s);glyph.draw(c);
        }
    }
}
