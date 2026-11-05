package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.os.*;
import android.text.InputType;
import android.view.*;
import android.view.inputmethod.InputMethodManager;
import android.widget.*;
import org.json.*;

/** New task over the lock screen: type or dictate, then send. Shows no history or task details while locked. */
public final class QuickTaskActivity extends Activity {
    /** Dictation target shared with task details: words are transcribed and appended to this draft, nothing is sent. */
    private static final String VOICE="quick-task";
    private AppUi ui;private ScrollView scroll;private Composer composer;private EditText input;private TextView status;private ImageButton send,mic;private boolean sending;private LinearLayout attachments;
    private final android.os.Handler main=new android.os.Handler(android.os.Looper.getMainLooper());
    private final Runnable tick=new Runnable(){public void run(){if(isFinishing())return;take();main.postDelayed(this,500);}};
    @Override public void onCreate(Bundle state){
        AppUi.theme(this);super.onCreate(state);AppBack.install(this,this::back);ui=new AppUi(this);ui.window();
        if(Build.VERSION.SDK_INT>=27){setShowWhenLocked(true);setTurnScreenOn(true);}
        else getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED|WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_VISIBLE|WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        LinearLayout box=ui.column();box.setPadding(ui.dp(24),ui.dp(24),ui.dp(24),ui.dp(16));
        LinearLayout header=ui.row();header.addView(ui.display("New task"),new LinearLayout.LayoutParams(0,-2,1));header.addView(AssistantStatus.worker(this,ui,null));box.addView(header);ui.space(box,6);
        if(getSystemService(KeyguardManager.class).isDeviceLocked())box.addView(ui.badge("Phone locked"),new LinearLayout.LayoutParams(-2,-2));
        box.addView(ui.detail("Type or dictate what you need. It goes to your assistant like a spoken request."));ui.space(box,16);
        // The shared chat composer: attachments and a frameless multiline field inside one container, Add attachment on the left, Dictate and Send on the right.
        composer=new Composer(ui,"Find my latest electricity invoice…",Cloud.prefs(this).getString("quick_task_draft",""),0,()->TaskAttachments.choose(this,"new-task"),"Dictate",this::dictate,"Send task",this::send);
        input=composer.input;input.setTag("quick_task_input");input.setMinLines(3);input.setSelection(input.length());attachments=composer.files;mic=composer.mic;mic.setTag("quick_task_mic");send=composer.send;send.setTag("quick_task_send");
        box.addView(composer.view,new LinearLayout.LayoutParams(-1,-2));ui.space(box,14);
        status=ui.detail("");status.setGravity(Gravity.CENTER);box.addView(status,new LinearLayout.LayoutParams(-1,-2));
        box.addView(new View(this),new LinearLayout.LayoutParams(1,0,1));
        box.addView(ui.ghostButton("Close",this::back),new LinearLayout.LayoutParams(-1,-2));
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.setBackground(ui.pageBackground());scroll.addView(box);setContentView(scroll);this.scroll=scroll;
        // System bars and the keyboard pad the page; while typing, the whole composer (Send included) stays above the keyboard.
        scroll.setOnApplyWindowInsetsListener((v,insets)->{int[] bars=TaskViews.bars(insets);v.setPadding(bars[0],bars[1],bars[2],bars[3]);return insets;});
        View.OnLayoutChangeListener keep=(v,l,t,r,b,ol,ot,or,ob)->{if(input.hasFocus())scroll.post(this::revealComposer);};
        composer.view.addOnLayoutChangeListener(keep);scroll.addOnLayoutChangeListener(keep);
        input.requestFocus();
    }
    private void revealComposer(){
        if(scroll==null)return;int visible=scroll.getHeight()-scroll.getPaddingTop()-scroll.getPaddingBottom(),bottom=composer.view.getBottom()+ui.dp(12);
        if(visible>0&&bottom-scroll.getScrollY()>visible)scroll.scrollTo(0,bottom-visible);
    }
    @Override public void onStart(){super.onStart();main.removeCallbacks(tick);main.post(tick);}
    @Override public void onStop(){main.removeCallbacks(tick);super.onStop();}
    @Override public void onDestroy(){if(isFinishing())stopDictation();super.onDestroy();}
    /** Appends what was dictated so far and keeps the microphone label in step with the dictation state. */
    private void take(){
        TaskAttachments.renderDraft(this,ui,attachments,"new-task",()->{});
        if(sending){String transfer=Cloud.prefs(this).getString("task_attachment_transfer","");if(!transfer.isEmpty())status.setText(transfer);}
        String words=TaskVoice.take(this,VOICE);if(!words.isEmpty()){input.append((input.length()==0?"":" ")+words);input.setSelection(input.length());}
        String note=TaskVoice.takeNote(this,VOICE);if(!note.isEmpty())status.setText(note);
        boolean on="dictate".equals(TaskVoice.mode(this,VOICE));if(on!=mic.isActivated()){mic.setActivated(on);composer.dictating(on,"Dictate","Finish dictation");}
    }
    private void dictate(){
        if("dictate".equals(TaskVoice.mode(this,VOICE))){stopDictation();status.setText("Finishing dictation…");return;}
        if(Cloud.prefs(this).getString("token","").isEmpty()){status.setText("Pair Companion first, while unlocked.");return;}
        if(TaskVoice.busy(this,VOICE)){status.setText("End the other voice conversation first.");return;}
        if(checkSelfPermission("android.permission.RECORD_AUDIO")!=android.content.pm.PackageManager.PERMISSION_GRANTED){requestPermissions(new String[]{"android.permission.RECORD_AUDIO"},304);return;}
        try{startForegroundService(TaskVoice.intent(this,"dictate:"+VOICE));status.setText("Dictating · tap the microphone again to finish.");}
        catch(Exception error){status.setText("The microphone could not start. Try again.");}
    }
    private void stopDictation(){if("dictate".equals(TaskVoice.mode(this,VOICE))){Intent finish=TaskVoice.finish(this,VOICE);if(finish!=null)startService(finish);}}
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] grants){super.onRequestPermissionsResult(request,permissions,grants);if(request==304){if(grants.length>0&&grants[0]==android.content.pm.PackageManager.PERMISSION_GRANTED)dictate();else status.setText("Allow the microphone to dictate.");}}
    @Override public void onResume(){super.onResume();input.postDelayed(()->{input.requestFocus();InputMethodManager keyboard=getSystemService(InputMethodManager.class);if(keyboard!=null)keyboard.showSoftInput(input,InputMethodManager.SHOW_IMPLICIT);},150);}
    @Override public void onPause(){if(!sending)Cloud.prefs(this).edit().putString("quick_task_draft",input.getText().toString()).apply();super.onPause();}
    @Override public void onBackPressed(){back();}
    private void back(){
        if(isTaskRoot())startActivity(new Intent(this,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TOP|Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra("open_tab","home"));
        finish();
    }
    private void send(){
        if("dictate".equals(TaskVoice.mode(this,VOICE))){status.setText("Finish dictation with the microphone, then tap Send.");return;}
        String text=input.getText().toString().trim();if(text.isEmpty()){status.setText("Type or dictate a request first.");return;}if(sending)return;
        if(Cloud.prefs(this).getString("token","").isEmpty()){status.setText("Pair Companion first, while unlocked.");return;}
        sending=true;composer.sendable(false);status.setText("Saving task and attachments…");
        // A stable ID per draft makes a retry after a dropped connection replay safely instead of queueing twice.
        final String request;try{request=NativeTasks.enqueueNew(this,text);}catch(Exception error){sending=false;composer.sendable(true);status.setText("Could not save this task. Your draft is still here.");return;}
        input.setText("");attachments.setTag(null);TaskAttachments.renderDraft(this,ui,attachments,"new-task",()->{});
        new Thread(()->{String reply;boolean ok;
            try{NativeTasks.flush(this);JSONObject receipt=new JSONObject(Cloud.prefs(this).getString("task_new_receipt:"+request,"{}"));reply=receipt.optString("reply","Task received by the server.");ok=receipt.length()>0;}
            catch(Exception e){reply="Saved on this phone. Task and files will send when connected. "+(e.getMessage()==null?"":e.getMessage());ok=false;}
            final String shown=reply;final boolean sent=ok;
            runOnUiThread(()->{sending=false;composer.sendable(true);status.setText(shown);
                if(sent){NativeTasks.changed(this);input.postDelayed(this::finish,1800);}});
        }).start();
    }
}
