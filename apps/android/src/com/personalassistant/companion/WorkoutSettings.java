package com.personalassistant.companion;

import android.content.Intent;
import android.net.Uri;
import android.widget.LinearLayout;
import android.widget.Switch;
import android.widget.Toast;
import org.json.JSONObject;

/** The paired owner's Iron League controls, backed by the same settings as the web app. */
final class WorkoutSettings {
    private static final String PROFILE="workout/friends/me", REMINDERS="workout/friends/reminders";
    private final WorkoutScreen screen;
    private final MainActivity a;
    private final AppUi ui;

    WorkoutSettings(WorkoutScreen screen){this.screen=screen;a=screen.a;ui=screen.ui;}

    void open(){
        WorkoutViews.Sheet sheet=new WorkoutViews.Sheet(ui,"Iron League settings");
        sheet.body.addView(WorkoutViews.row(ui,"Athlete profile","Body stats, units, goals and coach briefs",screen::profile),WorkoutViews.gap(ui,12));
        LinearLayout network=ui.column();
        sheet.body.addView(network);
        sheet.show();
        load(sheet,network);
    }

    private void load(WorkoutViews.Sheet sheet,LinearLayout network){
        network.removeAllViews();
        network.addView(ui.detail("Loading your league settings…"));
        new Thread(()->{
            try{
                JSONObject profile=(JSONObject)Cloud.call(a,PROFILE,null,true);
                JSONObject reminders=(JSONObject)Cloud.call(a,REMINDERS,null,true);
                a.runOnUiThread(()->show(sheet,network,profile,reminders));
            }catch(Exception error){
                a.runOnUiThread(()->{
                    if(!sheet.dialog.isShowing())return;
                    network.removeAllViews();
                    network.addView(ui.detail("Couldn't load league settings."),WorkoutViews.gap(ui,8));
                    network.addView(ui.quietButton("Retry",()->load(sheet,network)));
                });
            }
        }).start();
    }

    private void show(WorkoutViews.Sheet sheet,LinearLayout network,JSONObject profile,JSONObject reminders){
        if(!sheet.dialog.isShowing())return;
        network.removeAllViews();
        LinearLayout sharing=group(network,"Friends and privacy");
        toggle(sharing,PROFILE,profile,"share_progress","Share my progress","Friends can open your sprint and ranks and see any check-ins you choose to share.");
        toggle(sharing,PROFILE,profile,"share_schedule","Share my schedule","Show your planned, completed and missed sessions when progress sharing is on.");
        toggle(sharing,PROFILE,profile,"rank_alerts","Competitive notifications","Get a notification when a friend ranks up.");
        LinearLayout plans=group(network,"Scheduling and reminders");
        toggle(plans,REMINDERS,reminders,"scheduled_sprints","Scheduled sprints","Use dated sessions with start times, or stick to a repeating cycle.");
        toggle(plans,REMINDERS,reminders,"enabled","Workout reminders","Send a reminder to subscribed devices 30 minutes before a scheduled workout.");
        toggle(plans,REMINDERS,reminders,"roast","Diss mode","Opt in to vulgar coach messages and reminders.");
        network.addView(ui.quietButton("Open Iron League on the web",()->{
            String origin=Cloud.prefs(a).getString("origin","");
            a.startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(origin+"/train/")));
        }),WorkoutViews.gap(ui,10));
    }

    private LinearLayout group(LinearLayout parent,String title){
        LinearLayout card=WorkoutViews.card(ui);
        card.addView(ui.label(title),WorkoutViews.gap(ui,8));
        parent.addView(card,WorkoutViews.gap(ui,12));
        return card;
    }

    private void toggle(LinearLayout group,String path,JSONObject current,String key,String title,String description){
        LinearLayout row=ui.row(),labels=ui.column();
        labels.addView(ui.type(title,15,20,650,0,ui.text));
        labels.addView(ui.detail(description));
        row.addView(labels,MainParts.weighted(ui,1,0,0,10,0));
        Switch control=ui.switchControl(current.optBoolean(key),title);
        row.addView(control,new LinearLayout.LayoutParams(ui.dp(56),ui.dp(48)));
        group.addView(row,WorkoutViews.gap(ui,10));
        control.setOnCheckedChangeListener((button,checked)->{
            if(!control.isEnabled())return;
            control.setEnabled(false);
            new Thread(()->{
                try{
                    JSONObject response=(JSONObject)Cloud.call(a,path,new JSONObject().put(key,checked),true);
                    a.runOnUiThread(()->setChecked(control,response.optBoolean(key)));
                }catch(Exception error){
                    a.runOnUiThread(()->{
                        setChecked(control,!checked);
                        Toast.makeText(a,"Couldn't save "+title.toLowerCase(java.util.Locale.ROOT)+".",Toast.LENGTH_SHORT).show();
                    });
                }
            }).start();
        });
    }

    private static void setChecked(Switch control,boolean value){
        // Avoid triggering another remote save if the server reverted the switch.
        if(control.isChecked()!=value){control.setEnabled(false);control.setChecked(value);}
        control.setEnabled(true);
    }
}
