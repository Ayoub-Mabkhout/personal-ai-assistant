package com.personalassistant.companion;

import android.app.*;
import android.app.job.JobScheduler;
import android.content.*;
import android.os.*;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.lang.reflect.*;
import java.util.*;

/** Native task screens on a disposable unpaired emulator. No cloud or voice calls. */
public final class TaskUiInstrumentation extends Instrumentation {
    private MainActivity activity;private Dialog taskDialog;private File testUpdate;private SharedPreferences prefs;private Map<String,?> before;
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle result=new Bundle();int outcome=0;Context c=getTargetContext();try{
        check("ranchu".equals(Build.HARDWARE)||"goldfish".equals(Build.HARDWARE),"Disposable emulator required");prefs=Cloud.prefs(c);check(prefs.getString("token","").isEmpty(),"Unpaired emulator required");before=prefs.getAll();
        prefs.edit().clear().putString("ui_theme","dark").putString("origin","").putString("token","offline-ui-fixture").putLong("update_checked",System.currentTimeMillis()).putBoolean("notification_permission_requested",true).commit();
        activity=(MainActivity)startActivitySync(new Intent(c,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));idle();
        String task="task-ui-fixture";JSONObject cached=new JSONObject().put("id",task).put("kind","agent").put("original_request","Review the draft").put("original_summary","The draft is ready.").put("original_state","completed").put("original_updated",1700000001).put("state","completed").put("created",1700000000).put("can_followup",true).put("turns",new JSONArray().put(new JSONObject().put("id","followup-fixture").put("instruction","Make it shorter").put("summary","Shorter draft prepared.").put("state","completed").put("created",1700000002).put("updated",1700000003)));
        prefs.edit().putString("task_detail_agent_"+task,cached.toString()).commit();
        // Retain a handle to the real native dialog so widget identity can be verified.
        Class<?> detail=Class.forName("com.personalassistant.companion.NativeTaskScreens$Detail");Constructor<?> constructor=detail.getDeclaredConstructor(Activity.class,String.class,String.class);constructor.setAccessible(true);Object[] screen=new Object[1];runOnMainSync(()->{try{screen[0]=constructor.newInstance(activity,"agent",task);Field d=detail.getSuperclass().getDeclaredField("dialog");d.setAccessible(true);taskDialog=(Dialog)d.get(screen[0]);Method open=detail.getSuperclass().getDeclaredMethod("open");open.setAccessible(true);open.invoke(screen[0]);}catch(Exception error){throw new RuntimeException(error);}});idle();
        View root=taskDialog.getWindow().getDecorView();EditText input=(EditText)root.findViewWithTag("task_followup_input");Button send=(Button)root.findViewWithTag("task_followup_send");check(input!=null&&send!=null,"Native continuation controls missing");String content=texts(root);check(content.contains("Review the draft")&&content.contains("The draft is ready.")&&content.contains("Make it shorter")&&content.contains("Shorter draft prepared."),"Task conversation omitted root or earlier turn");
        runOnMainSync(()->{input.setText("Keep the final paragraph");input.requestFocus();input.setSelection(5,9);});NativeTasks.changed(c);idle();check(root.findViewWithTag("task_followup_input")==input&&input.getText().toString().equals("Keep the final paragraph")&&input.getSelectionStart()==5&&input.getSelectionEnd()==9,"Task update replaced composer or selection");result.putBoolean("native_details_root_and_turns_with_stable_draft",true);
        runOnMainSync(send::performClick);idle();JSONArray saved=NativeTasks.pending(c);check(saved.length()==1&&saved.getJSONObject(0).getString("task_id").equals(task)&&saved.getJSONObject(0).getString("instruction").equals("Keep the final paragraph"),"Offline follow-up not durably saved once");String stable=saved.getJSONObject(0).getString("id");check(input.getText().toString().isEmpty(),"Draft not cleared after durable save");try{NativeTasks.flush(c);}catch(Exception expected){}check(NativeTasks.pending(c).length()==1&&NativeTasks.pending(c).getJSONObject(0).getString("id").equals(stable),"Failed retry dropped or replaced follow-up ID");result.putBoolean("offline_same_task_followup_stable_id_retry",true);
        runOnMainSync(()->input.setText("Another instruction"));check(prefs.getString("task_draft:"+task,"").equals("Another instruction"),"Continuation draft not persisted");runOnMainSync(taskDialog::dismiss);idle();result.putBoolean("continuation_draft_persisted",true);
        runOnMainSync(()->{NativeTaskScreens.history(activity);});idle();result.putBoolean("native_history_offline_opens_without_browser",true);
        testUpdate=Updates.apk(c);check(!testUpdate.exists(),"Clean update cache required for synthetic prompt check");try(FileOutputStream out=new FileOutputStream(testUpdate)){out.write(new byte[]{1,2,3});}prefs.edit().putString("update_release","{\"version_code\":999,\"version_name\":\"test release\"}").commit();idle();check(Updates.promptVisible(activity)&&prefs.getLong("update_prompted_version",0)==999,"Downloaded release did not prompt on app entry/state refresh");runOnMainSync(()->check(!Updates.prompt(activity),"Repeated callback prompted same release twice"));runOnMainSync(()->Updates.dismissPrompt(activity));testUpdate.delete();testUpdate=null;prefs.edit().remove("update_release").commit();result.putBoolean("downloaded_update_automatic_prompt_deduplicated",true);
        result.putString("stream","Native root and follow-up chat, stable composer, offline durable follow-up IDs, history and update prompts passed. Synthetic update never installed; no paid API or real server calls.");
    }catch(Throwable error){result.putString("stream",android.util.Log.getStackTraceString(error));outcome=1;}finally{if(testUpdate!=null)testUpdate.delete();if(taskDialog!=null)runOnMainSync(taskDialog::dismiss);if(activity!=null)runOnMainSync(activity::finish);for(int id:new int[]{210,211,212,216,218,219})c.getSystemService(JobScheduler.class).cancel(id);if(before!=null)restore();}finish(outcome,result);}
    private void restore(){SharedPreferences.Editor editor=prefs.edit().clear();for(Map.Entry<String,?> e:before.entrySet()){Object v=e.getValue();String k=e.getKey();if(v instanceof String)editor.putString(k,(String)v);else if(v instanceof Boolean)editor.putBoolean(k,(Boolean)v);else if(v instanceof Integer)editor.putInt(k,(Integer)v);else if(v instanceof Long)editor.putLong(k,(Long)v);else if(v instanceof Float)editor.putFloat(k,(Float)v);else if(v instanceof Set)editor.putStringSet(k,(Set<String>)v);}editor.commit();}
    private void idle(){waitForIdleSync();try{Thread.sleep(350);}catch(InterruptedException error){Thread.currentThread().interrupt();}waitForIdleSync();}
    private String texts(View view){StringBuilder text=new StringBuilder();collect(view,text);return text.toString();}
    private void collect(View view,StringBuilder text){if(view instanceof TextView)text.append(((TextView)view).getText()).append('\n');if(view instanceof ViewGroup)for(int n=0;n<((ViewGroup)view).getChildCount();n++)collect(((ViewGroup)view).getChildAt(n),text);}
    private static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
}
