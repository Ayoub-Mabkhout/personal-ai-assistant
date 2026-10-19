package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.os.*;
import android.text.InputType;
import android.view.*;
import android.view.inputmethod.InputMethodManager;
import android.widget.*;
import org.json.JSONObject;
import java.util.UUID;

/** New task over the lock screen: type or speak, then send. Shows no history or task details while locked. */
public final class QuickTaskActivity extends Activity {
    private AppUi ui;private EditText input;private TextView status;private Button send;private boolean sending;
    @Override public void onCreate(Bundle state){
        AppUi.theme(this);super.onCreate(state);AppBack.install(this,this::back);ui=new AppUi(this);ui.window();
        if(Build.VERSION.SDK_INT>=27){setShowWhenLocked(true);setTurnScreenOn(true);}
        else getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED|WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_VISIBLE|WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        boolean locked=getSystemService(KeyguardManager.class).isDeviceLocked();
        LinearLayout box=ui.column();box.setPadding(ui.dp(24),ui.dp(24),ui.dp(24),ui.dp(16));
        LinearLayout header=ui.row();header.addView(ui.display("New task"),new LinearLayout.LayoutParams(0,-2,1));if(locked)header.addView(ui.badge("Phone locked"));box.addView(header);ui.space(box,6);
        box.addView(ui.detail("Say or type what you need. It goes to your assistant like a spoken request."));ui.space(box,16);
        input=new EditText(this);input.setHint("Find my latest electricity invoice…");input.setTextColor(ui.text);input.setHintTextColor(ui.muted);input.setTextSize(18);input.setTypeface(AppUi.face(500));
        input.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_MULTI_LINE|InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);input.setMinLines(3);input.setGravity(Gravity.TOP|Gravity.START);
        input.setPadding(ui.dp(16),ui.dp(14),ui.dp(16),ui.dp(14));input.setBackground(ui.outline(ui.surface,20,ui.stroke,1));input.setText(Cloud.prefs(this).getString("quick_task_draft",""));input.setSelection(input.length());
        box.addView(input,new LinearLayout.LayoutParams(-1,-2));ui.space(box,14);
        LinearLayout actions=ui.row();
        Button speak=ui.ghostButton("Speak",()->{startActivity(new Intent(this,VoiceEntryActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));finish();});
        actions.addView(speak,new LinearLayout.LayoutParams(0,ui.dp(56),1));
        send=new Button(this);send.setAllCaps(false);send.setText("Send");send.setTextSize(16);send.setTypeface(AppUi.face(700));send.setTextColor(0xff2a1a5e);
        send.setBackground(ui.pressable(ui.outline(0xffefe9f8,18,0,0),18));send.setOnClickListener(v->send());
        LinearLayout.LayoutParams sp=new LinearLayout.LayoutParams(0,ui.dp(56),1);sp.setMarginStart(ui.dp(10));actions.addView(send,sp);box.addView(actions);ui.space(box,14);
        status=ui.detail("");status.setGravity(Gravity.CENTER);box.addView(status,new LinearLayout.LayoutParams(-1,-2));
        box.addView(new View(this),new LinearLayout.LayoutParams(1,0,1));
        box.addView(ui.ghostButton("Close",this::back),new LinearLayout.LayoutParams(-1,-2));
        ScrollView scroll=new ScrollView(this);scroll.setFitsSystemWindows(true);scroll.setFillViewport(true);scroll.setBackground(ui.pageBackground());scroll.addView(box);setContentView(scroll);
        input.requestFocus();
    }
    @Override public void onResume(){super.onResume();input.postDelayed(()->{input.requestFocus();InputMethodManager keyboard=getSystemService(InputMethodManager.class);if(keyboard!=null)keyboard.showSoftInput(input,InputMethodManager.SHOW_IMPLICIT);},150);}
    @Override public void onPause(){if(!sending)Cloud.prefs(this).edit().putString("quick_task_draft",input.getText().toString()).apply();super.onPause();}
    @Override public void onBackPressed(){back();}
    private void back(){
        if(isTaskRoot())startActivity(new Intent(this,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra("open_tab","home"));
        finish();
    }
    private void send(){
        String text=input.getText().toString().trim();if(text.isEmpty()){status.setText("Type or say a request first.");return;}if(sending)return;
        if(Cloud.prefs(this).getString("token","").isEmpty()){status.setText("Pair Companion first, while unlocked.");return;}
        sending=true;send.setEnabled(false);status.setText("Sending…");
        // A stable ID per draft makes a retry after a dropped connection replay safely instead of queueing twice.
        String id=Cloud.prefs(this).getString("quick_task_id","");if(id.isEmpty()){id="typed-"+UUID.randomUUID().toString().replace("-","").substring(0,24);Cloud.prefs(this).edit().putString("quick_task_id",id).commit();}
        final String request=id;
        new Thread(()->{String reply;boolean ok;
            try{JSONObject body=new JSONObject().put("id",request).put("text",text).put("created_at",java.time.Instant.now().toString()).put("timezone",java.util.TimeZone.getDefault().getID()).put("native_timers",true);
                JSONObject result=(JSONObject)Cloud.call(this,"voice/text",body,true);reply=result.optString("reply","Sent to your assistant.");ok=true;}
            catch(Exception e){reply="Not sent: "+(e.getMessage()==null?"no connection":e.getMessage())+". Your text is kept; try again.";ok=false;}
            final String shown=reply;final boolean sent=ok;
            runOnUiThread(()->{sending=false;send.setEnabled(true);status.setText(shown);
                if(sent){Cloud.prefs(this).edit().remove("quick_task_draft").remove("quick_task_id").apply();input.setText("");NativeTasks.changed(this);input.postDelayed(this::finish,1800);}});
        }).start();
    }
}
