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
        final AppUi[] palette=new AppUi[1];final LinearLayout[] bubbles=new LinearLayout[1];final int[] opens={0};runOnMainSync(()->{palette[0]=new AppUi(activity);bubbles[0]=palette[0].column();ChatTimeline.bubble(bubbles[0],palette[0],"Added milk.",false,System.currentTimeMillis(),"answer","standalone-grocery-receipt",id->opens[0]++);check(bubbles[0].findViewWithTag("chat_task:standalone-grocery-receipt")==null,"Immediate grocery answer linked to a nonexistent laptop task");ChatTimeline.bubble(bubbles[0],palette[0],"Queued command to the laptop.",false,System.currentTimeMillis(),"acknowledgement","queued-laptop-task",id->opens[0]++);View open=bubbles[0].findViewWithTag("chat_task:queued-laptop-task");check(open!=null,"Queued command lost its native task link");open.performClick();check(opens[0]==1,"Native task link did not open once");});result.putBoolean("programmed_answer_has_no_laptop_task_link",true);result.putBoolean("queued_acknowledgement_native_task_link",true);
        String task="task-ui-fixture";JSONObject cached=new JSONObject().put("id",task).put("kind","agent").put("original_request","Review the draft").put("original_summary","The draft is ready.").put("original_state","completed").put("original_updated",1700000001).put("state","completed").put("created",1700000000).put("can_followup",true).put("turns",new JSONArray().put(new JSONObject().put("id","followup-fixture").put("instruction","Make it shorter").put("summary","Shorter draft prepared.").put("state","completed").put("created",1700000002).put("updated",1700000003)));
        prefs.edit().putString("task_detail_agent_"+task,cached.toString()).commit();
        // Retain a handle to the real native dialog so widget identity can be verified.
        Class<?> detail=Class.forName("com.personalassistant.companion.NativeTaskScreens$Detail");Constructor<?> constructor=detail.getDeclaredConstructor(Activity.class,String.class,String.class);constructor.setAccessible(true);Object[] screen=new Object[1];runOnMainSync(()->{try{screen[0]=constructor.newInstance(activity,"agent",task);Field d=detail.getSuperclass().getDeclaredField("dialog");d.setAccessible(true);taskDialog=(Dialog)d.get(screen[0]);Method open=detail.getSuperclass().getDeclaredMethod("open");open.setAccessible(true);open.invoke(screen[0]);}catch(Exception error){throw new RuntimeException(error);}});idle();
        View root=taskDialog.getWindow().getDecorView();EditText input=(EditText)root.findViewWithTag("task_followup_input");View send=root.findViewWithTag("task_followup_send");check(input!=null&&send!=null,"Native continuation controls missing");String content=texts(root);check(content.contains("Review the draft")&&content.contains("The draft is ready.")&&content.contains("Make it shorter")&&content.contains("Shorter draft prepared."),"Task conversation omitted root or earlier turn");
        runOnMainSync(()->{input.setText("Keep the final paragraph");input.requestFocus();input.setSelection(5,9);});NativeTasks.changed(c);idle();check(root.findViewWithTag("task_followup_input")==input&&input.getText().toString().equals("Keep the final paragraph")&&input.getSelectionStart()==5&&input.getSelectionEnd()==9,"Task update replaced composer or selection");result.putBoolean("native_details_root_and_turns_with_stable_draft",true);
        runOnMainSync(send::performClick);idle();JSONArray saved=NativeTasks.pending(c);check(saved.length()==1&&saved.getJSONObject(0).getString("task_id").equals(task)&&saved.getJSONObject(0).getString("instruction").equals("Keep the final paragraph"),"Offline follow-up not durably saved once");String stable=saved.getJSONObject(0).getString("id");check(input.getText().toString().isEmpty(),"Draft not cleared after durable save");try{NativeTasks.flush(c);}catch(Exception expected){}check(NativeTasks.pending(c).length()==1&&NativeTasks.pending(c).getJSONObject(0).getString("id").equals(stable),"Failed retry dropped or replaced follow-up ID");result.putBoolean("offline_same_task_followup_stable_id_retry",true);
        runOnMainSync(()->input.setText("Another instruction"));check(prefs.getString("task_draft:"+task,"").equals("Another instruction"),"Continuation draft not persisted");runOnMainSync(taskDialog::dismiss);idle();result.putBoolean("continuation_draft_persisted",true);
        runOnMainSync(()->{NativeTaskScreens.history(activity);});idle();result.putBoolean("native_history_offline_opens_without_browser",true);history(result);dayLabels(result);
        testUpdate=Updates.apk(c);check(!testUpdate.exists(),"Clean update cache required for synthetic prompt check");try(FileOutputStream out=new FileOutputStream(testUpdate)){out.write(new byte[]{1,2,3});}prefs.edit().putString("update_release","{\"version_code\":999,\"version_name\":\"test release\"}").commit();idle();check(Updates.promptVisible(activity)&&prefs.getLong("update_prompted_version",0)==999,"Downloaded release did not prompt on app entry/state refresh");runOnMainSync(()->check(!Updates.prompt(activity),"Repeated callback prompted same release twice"));runOnMainSync(()->Updates.dismissPrompt(activity));testUpdate.delete();testUpdate=null;prefs.edit().remove("update_release").commit();result.putBoolean("downloaded_update_automatic_prompt_deduplicated",true);
        result.putString("stream","Native root and follow-up chat, stable composer, offline durable follow-up IDs, history and update prompts passed. Synthetic update never installed; no paid API or real server calls.");
    }catch(Throwable error){result.putString("stream",android.util.Log.getStackTraceString(error));outcome=1;}finally{if(testUpdate!=null)testUpdate.delete();if(taskDialog!=null)runOnMainSync(taskDialog::dismiss);if(activity!=null)runOnMainSync(activity::finish);for(int id:new int[]{210,211,212,216,218,219})c.getSystemService(JobScheduler.class).cancel(id);if(before!=null)restore();}finish(outcome,result);}
    private void restore(){SharedPreferences.Editor editor=prefs.edit().clear();for(Map.Entry<String,?> e:before.entrySet()){Object v=e.getValue();String k=e.getKey();if(v instanceof String)editor.putString(k,(String)v);else if(v instanceof Boolean)editor.putBoolean(k,(Boolean)v);else if(v instanceof Integer)editor.putInt(k,(Integer)v);else if(v instanceof Long)editor.putLong(k,(Long)v);else if(v instanceof Float)editor.putFloat(k,(Float)v);else if(v instanceof Set)editor.putStringSet(k,(Set<String>)v);}editor.commit();}
    private static JSONObject page(String next,String... ids)throws JSONException{JSONArray items=new JSONArray();for(String id:ids)items.put(new JSONObject().put("id",id));JSONObject page=new JSONObject().put("items",items);return next==null?page:page.put("next_cursor",next);}
    @SuppressWarnings("unchecked") private static List<String> ids(Object screen)throws Exception{List<String> ids=new ArrayList<>();Field f=screen.getClass().getDeclaredField("items");f.setAccessible(true);for(JSONObject item:(List<JSONObject>)f.get(screen))ids.add(item.getString("id"));return ids;}
    private static Object field(Object screen,String name)throws Exception{Field f=screen.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(screen);}
    /** Task history paging: Load more appends, a refresh puts page one first and keeps the pages already loaded. */
    private void history(Bundle result)throws Exception{
        Class<?> type=Class.forName("com.personalassistant.companion.NativeTaskScreens$History");Constructor<?> constructor=type.getDeclaredConstructor(Activity.class);constructor.setAccessible(true);
        Method merge=type.getDeclaredMethod("merge",JSONObject.class,int.class);merge.setAccessible(true);final Object[] screen=new Object[1];runOnMainSync(()->{try{screen[0]=constructor.newInstance(activity);}catch(Exception error){throw new AssertionError(error);}});
        merge.invoke(screen[0],page("c1","a","b"),0);check(ids(screen[0]).equals(Arrays.asList("a","b"))&&field(screen[0],"cursor").equals("c1")&&field(screen[0],"pages").equals(1),"First page not shown");
        merge.invoke(screen[0],page("c2","c","d","c"),1);check(ids(screen[0]).equals(Arrays.asList("a","b","c","d"))&&field(screen[0],"cursor").equals("c2")&&field(screen[0],"pages").equals(2),"Load more did not append once");
        merge.invoke(screen[0],page(null,"d","e"),1);check(ids(screen[0]).equals(Arrays.asList("a","b","c","d","e"))&&field(screen[0],"cursor").equals("")&&field(screen[0],"pages").equals(3),"Load more repeated a known task or kept a stale cursor");
        merge.invoke(screen[0],page("later","z","a"),2);check(ids(screen[0]).equals(Arrays.asList("z","a","b","c","d","e"))&&field(screen[0],"cursor").equals("")&&field(screen[0],"pages").equals(3),"Refresh dropped loaded pages or moved the cursor");
        merge.invoke(screen[0],page("c9","q"),0);check(ids(screen[0]).equals(Arrays.asList("q"))&&field(screen[0],"cursor").equals("c9")&&field(screen[0],"pages").equals(1),"A new search did not replace the list");
        merge.invoke(screen[0],page("c10","r","s"),2);check(ids(screen[0]).equals(Arrays.asList("r","s"))&&field(screen[0],"cursor").equals("c10"),"Refresh of a single page did not replace it");
        merge.invoke(screen[0],page(null,"m","m"),0);check(ids(screen[0]).equals(Arrays.asList("m")),"Duplicate ids within one page were kept");
        result.putBoolean("task_history_paging_merge_modes",true);
    }
    /** Yesterday is a calendar day, not 24 hours: around a daylight saving change the two differ for one hour. */
    private void dayLabels(Bundle result)throws Exception{
        TimeZone saved=TimeZone.getDefault();
        try{
            TimeZone.setDefault(TimeZone.getTimeZone("Europe/Berlin"));
            check(TaskViews.dayLabel(local(2026,Calendar.MARCH,29,12,0),local(2026,Calendar.MARCH,30,0,30)).startsWith("Yesterday"),"Yesterday lost after the spring change");
            check(TaskViews.dayLabel(local(2026,Calendar.OCTOBER,24,12,0),local(2026,Calendar.OCTOBER,25,23,30)).startsWith("Yesterday"),"Yesterday lost on the long autumn day");
            check(TaskViews.dayLabel(local(2026,Calendar.OCTOBER,25,8,0),local(2026,Calendar.OCTOBER,25,23,30)).startsWith("Today"),"Today lost on the long autumn day");
            check(!TaskViews.dayLabel(local(2026,Calendar.OCTOBER,23,12,0),local(2026,Calendar.OCTOBER,25,23,30)).startsWith("Yesterday"),"Two days ago read as yesterday");
        }finally{TimeZone.setDefault(saved);}
        result.putBoolean("task_day_labels_follow_calendar_days",true);
    }
    private static long local(int year,int month,int day,int hour,int minute){Calendar c=Calendar.getInstance();c.clear();c.set(year,month,day,hour,minute);return c.getTimeInMillis();}
    private void idle(){waitForIdleSync();try{Thread.sleep(350);}catch(InterruptedException error){Thread.currentThread().interrupt();}waitForIdleSync();}
    private String texts(View view){StringBuilder text=new StringBuilder();collect(view,text);return text.toString();}
    private void collect(View view,StringBuilder text){if(view instanceof TextView)text.append(((TextView)view).getText()).append('\n');if(view instanceof ViewGroup)for(int n=0;n<((ViewGroup)view).getChildCount();n++)collect(((ViewGroup)view).getChildAt(n),text);}
    private static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
}
