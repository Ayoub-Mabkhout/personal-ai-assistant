package com.personalassistant.companion;

import android.app.*;
import android.os.Build;
import android.text.TextUtils;
import android.view.*;
import android.widget.*;

/** Hey Chat battery use sheet: the listener's measured cost, the three measured states and a reset. */
final class BatteryScreen {
    static void open(MainActivity a,Runnable closed){new BatteryScreen(a,closed).dialog.show();}

    final MainActivity a;final AppUi ui;final Dialog dialog;final LinearLayout root,body;

    BatteryScreen(MainActivity a,Runnable closed){
        this.a=a;ui=new AppUi(a);dialog=ui.sheet();root=ui.column();root.setBackground(ui.pageBackground());
        LinearLayout bar=ui.row();bar.setPadding(ui.dp(17),ui.dp(6),ui.dp(17),ui.dp(6));bar.addView(ui.iconButton("back","Back from Battery use",dialog::dismiss),new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));
        TextView heading=ui.type("Battery use",20,26,700,-.01f,ui.text);heading.setSingleLine(true);heading.setEllipsize(TextUtils.TruncateAt.END);if(Build.VERSION.SDK_INT>=28)heading.setAccessibilityHeading(true);bar.addView(heading,MainParts.weighted(ui,1,10,0,10,0));root.addView(bar);
        ScrollView scroll=new ScrollView(a);scroll.setFillViewport(true);body=ui.column();body.setPadding(ui.dp(20),ui.dp(4),ui.dp(20),ui.dp(24));scroll.addView(body);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        root.setOnApplyWindowInsetsListener((v,insets)->{int[] bars=TaskViews.bars(insets);root.setPadding(bars[0],bars[1],bars[2],0);body.setPadding(ui.dp(20),ui.dp(4),ui.dp(20),ui.dp(24)+bars[3]);return insets;});
        dialog.setContentView(root);dialog.setOnShowListener(d->dialog.getWindow().setLayout(-1,-1));
        dialog.setOnDismissListener(d->{if(!a.isFinishing()&&!a.isDestroyed()){a.show();if(closed!=null)closed.run();}});
        Window window=dialog.getWindow();if(window!=null&&Build.VERSION.SDK_INT>=29)window.setNavigationBarContrastEnforced(false);
        render();
    }

    private void render(){
        body.removeAllViews();BatteryUsage.Report r=BatterySampler.report(a);
        body.addView(ui.detail("What Hey Chat background listening costs on this phone, measured from Android's battery gauge during normal use."),MainParts.params(ui,-1,-2,4,0,4,14));
        if(!r.ready()){LinearLayout empty=ui.empty("battery","Measuring battery use",r.detail());empty.setTag("battery_empty");LinearLayout card=ui.card();card.addView(empty);body.addView(card);}
        else{LinearLayout card=ui.card();card.setTag("battery_result");LinearLayout head=ui.row();head.addView(MainParts.icon(ui,"battery",ui.warning),new LinearLayout.LayoutParams(ui.dp(15),ui.dp(15)));head.addView(ui.label("Hey Chat listener"),MainParts.weighted(ui,1,8,0,8,0));head.addView(ui.statusChip(r.confidence(),r.tone()));card.addView(head);
            TextView title=ui.heading(r.headline());title.setTag("battery_headline");card.addView(title,MainParts.params(ui,-1,-2,0,10,0,0));card.addView(ui.detail(r.detail()),MainParts.params(ui,-1,-2,0,6,0,0));body.addView(card);}
        ui.label(body,"Measured so far");LinearLayout rows=ui.rowsCard();
        row(rows,"Listening, screen off",r.row(r.idle));row(rows,"Listener off, screen off",r.row(r.baseline));row(rows,"Listening, screen on",r.row(r.active));
        ui.hairline(rows,16,2,14);rows.addView(ui.type("Each state needs "+BatteryUsage.hours(BatteryUsage.MIN_MS)+" unplugged. Charging, voice commands, restarts and listener-off periods with phone use are left out ("+r.skipped+" gaps so far). Readings stay on this phone.",13,18,400,0,ui.muted),MainParts.params(ui,-1,-2,16,8,14,12));body.addView(rows);
        Button reset=ui.quietButton("Reset measurements",this::reset);reset.setTag("battery_reset");body.addView(reset,MainParts.params(ui,-1,-2,0,14,0,0));
    }
    private void row(LinearLayout card,String title,String value){
        LinearLayout row=ui.column();row.setPadding(ui.dp(16),ui.dp(10),ui.dp(14),ui.dp(10));row.addView(ui.type(title,15,21,500,0,ui.text));row.addView(ui.type(value,13,18,400,0,ui.muted),MainParts.params(ui,-1,-2,0,2,0,0));row.setFocusable(true);row.setContentDescription(title+", "+value);card.addView(row);
    }
    private void reset(){
        new AlertDialog.Builder(a).setTitle("Reset battery measurements?").setMessage("Measuring starts again from now. Earlier readings on this phone are deleted.").setPositiveButton("Reset",(d,w)->{BatterySampler.reset(a);render();}).setNegativeButton("Cancel",null).show();
    }
}
