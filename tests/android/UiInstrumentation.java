package com.personalassistant.companion;

import android.app.*;
import android.app.job.JobScheduler;
import android.content.*;
import android.content.pm.PackageManager;
import android.os.*;
import android.view.*;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.*;
import java.io.*;
import java.util.*;
import org.json.*;

/** Real Activity widgets/lifecycle; synthetic private prefs, no cloud/paid API. */
public final class UiInstrumentation extends Instrumentation {
    private MainActivity activity;private SharedPreferences prefs;private Map<String,?> before;private String theme;private boolean screensOnly,reducedMotion;private byte[] chatBefore;
    @Override public void onCreate(Bundle args){super.onCreate(args);theme=args.getString("theme","light");screensOnly=Boolean.parseBoolean(args.getString("screens_only","false"));reducedMotion=Boolean.parseBoolean(args.getString("reduced_motion","false"));start();}
    @Override public void onStart(){Bundle result=new Bundle();int outcome=0;Context target=getTargetContext();try{
        check("ranchu".equals(Build.HARDWARE)||"goldfish".equals(Build.HARDWARE),"Disposable emulator required");prefs=Cloud.prefs(target);check(prefs.getString("token","").isEmpty(),"Unpaired emulator required");before=prefs.getAll();File chatFile=new File(target.getFilesDir(),"voice-chat.json");if(chatFile.isFile())chatBefore=java.nio.file.Files.readAllBytes(chatFile.toPath());chatFile.delete();target.stopService(new Intent(target,VoiceService.class));
        prefs.edit().clear().putString("ui_theme",theme).putString("origin","").putBoolean("wake_enabled",false).putBoolean("voice_live",false).putLong("update_checked",System.currentTimeMillis()).putBoolean("notification_permission_requested",true).putBoolean("voice_chat_imported",true).commit();if(theme.equals("sun"))prefs.edit().remove("ui_theme").commit();
        activity=(MainActivity)startActivitySync(new Intent(target,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));idle();
        if(screensOnly){prefs.edit().putString("token","offline-ui-fixture").putString("snapshot","{\"items\":[{\"id\":\"one\",\"name\":\"Bananas\",\"quantity\":\"6\",\"complete\":0,\"version\":1},{\"id\":\"two\",\"name\":\"Sparkling water\",\"quantity\":\"2 bottles\",\"complete\":0,\"version\":1},{\"id\":\"three\",\"name\":\"Bread\",\"quantity\":\"1 loaf\",\"complete\":0,\"version\":1}],\"recipes\":[]}").apply();idle();snapshots(target);result.putBoolean("synthetic_screenshots_only",true);result.putString("theme",theme);result.putString("stream","Native visual capture with synthetic UI data; no functional suite or cloud calls.");}
        else{click("nav_settings");
        EditText server=(EditText)view("server_address"),code=(EditText)view("pairing_code");runOnMainSync(()->{server.setText("https://draft.invalid");code.setText("TEST-PAIR-CODE");server.requestFocus();server.setSelection(8,13);});
        prefs.edit().putString("voice_status","Synthetic asynchronous state").putString("snapshot","{\"items\":[],\"recipes\":[]}").apply();target.sendBroadcast(new Intent("com.personalassistant.companion.VOICE_STATE").setPackage(target.getPackageName()));target.sendBroadcast(new Intent("com.personalassistant.companion.GROCERY_STATE").setPackage(target.getPackageName()));idle();
        check(server==view("server_address")&&code==view("pairing_code"),"Async state reconstructed pairing inputs");check(server.getText().toString().equals("https://draft.invalid")&&code.getText().toString().equals("TEST-PAIR-CODE"),"Async pairing draft lost");check(server.hasFocus()&&server.getSelectionStart()==8&&server.getSelectionEnd()==13,"Async pairing focus/selection lost");
        runOnMainSync(()->server.setText("bad address"));click("pair");check(code.getText().toString().equals("TEST-PAIR-CODE")&&((Button)view("pair")).isEnabled(),"Rejected address lost code or stuck button");result.putBoolean("pairing_async_input_focus_selection_preserved",true);result.putBoolean("invalid_pairing_address_no_network",true);
        prefs.edit().putString("token","offline-ui-fixture").putString("origin","").putString("snapshot","{\"items\":[{\"id\":\"cached\",\"name\":\"Milk\",\"quantity\":\"\",\"complete\":0,\"version\":1}],\"recipes\":[]}").putString("outbox","[{\"id\":\"complete-fixture\",\"operation\":\"complete\",\"target\":\"cached\",\"version\":1,\"complete\":true},{\"id\":\"add-fixture\",\"operation\":\"add\",\"items\":[{\"name\":\"Bread\",\"quantity\":\"\"}]}]").apply();idle();click("nav_shopping");
        EditText input=(EditText)view("shopping_item");runOnMainSync(()->{input.setText("Sparkling water");input.requestFocus();input.setSelection(4);});target.sendBroadcast(new Intent("com.personalassistant.companion.GROCERY_STATE").setPackage(target.getPackageName()));idle();check(input.getText().toString().equals("Sparkling water")&&input.hasFocus()&&input.getSelectionStart()==4,"Grocery update lost typing/focus");String shopping=texts();check(shopping.contains("Bread")&&!shopping.contains("Milk"),"UI did not project pending changes");click("shopping_add");idle();check(input.getText().toString().isEmpty(),"Add draft not cleared after durable save");check(Cloud.queue(target).length()==3&&Cloud.pendingList(target).getJSONArray("items").length()==3,"Offline add not saved once");result.putBoolean("shopping_async_draft_preserved",true);result.putBoolean("shopping_cached_pending_projection_and_offline_add",true);
        JSONObject cached=Cloud.cached(target);cached.put("recipes",new JSONArray().put(new JSONObject().put("id","pasta-fixture").put("title","Quick pasta").put("ingredients",new JSONArray().put(new JSONObject().put("name","Pasta").put("quantity","500 g")).put(new JSONObject().put("name","Tomatoes").put("quantity","2")).put(new JSONObject().put("name","Oil").put("quantity","1 tbsp")))));prefs.edit().putString("snapshot",cached.toString()).apply();idle();choose("Recipes");choose("Quick pasta");choose("1 tbsp Oil");choose("Add selected to list");check(Cloud.queue(target).length()==4,"Recipe selected items not saved once");JSONArray ingredients=Cloud.queue(target).getJSONObject(3).getJSONArray("items");check(ingredients.length()==2&&ingredients.getJSONObject(0).getString("name").equals("Pasta")&&ingredients.getJSONObject(1).getString("name").equals("Tomatoes"),"Recipe added unselected/combined ingredients");choose("Close");result.putBoolean("native_recipe_selected_ingredients_saved_once",true);
        click("nav_voice");prefs.edit().putFloat("voice_level",.65f).putLong("voice_metrics_elapsed",SystemClock.elapsedRealtime()).putBoolean("voice_mic_active",true).putString("voice_user_text","Test user words").putString("voice_reply","Test response").apply();idle();AppUi.Meter meter=(AppUi.Meter)view("voice_level");check(Math.abs(meter.amplitude-.65f)<.001&&meter.active,"Microphone level did not bind");VoiceChat.user(target,"ui-chat-fixture","Test user words",1000);VoiceChat.assistant(target,"ui-chat-fixture","Test response",1001,"acknowledgement","");idle();check(texts().contains("Test user words")&&texts().contains("Test response")&&texts().contains("Queued"),"Chat user/ack bubbles missing");VoiceChat.assistant(target,"ui-chat-fixture","Revised response",1002,"answer","");idle();JSONArray chat=VoiceChat.history(target);check(chat.length()==2&&chat.getJSONObject(1).getString("text").equals("Revised response")&&chat.getJSONObject(1).getLong("time")==1001,"Streaming chat duplicated bubble or moved first timestamp");check(texts().contains("Revised response")&&!texts().contains("Test response"),"Chat revision did not update bubble");result.putBoolean("timestamped_chat_stable_upsert_role_and_order",true);prefs.edit().putFloat("voice_level",.2f).putLong("voice_metrics_elapsed",SystemClock.elapsedRealtime()).apply();idle();check(Math.abs(meter.amplitude-.2f)<.001,"Second meter level did not settle");if(reducedMotion){check(!android.animation.ValueAnimator.areAnimatorsEnabled(),"Reduced motion scale not disabled");check(meter.transition==null||!meter.transition.isRunning(),"Meter animates with reduced motion");for(View parent=meter;parent!=null;parent=parent.getParent() instanceof View?(View)parent.getParent():null)check(Math.abs(parent.getAlpha()-1)<.001,"Page left faded with reduced motion");result.putBoolean("reduced_motion_no_meter_or_page_animation",true);}prefs.edit().putFloat("voice_level",0f).putLong("voice_metrics_elapsed",SystemClock.elapsedRealtime()).apply();idle();check(meter.active&&meter.amplitude==0,"Quiet active input not zero baseline");prefs.edit().putBoolean("voice_mic_active",false).putFloat("voice_level",0f).apply();idle();check(!meter.active,"Mic level remained active after stop");result.putBoolean("meter_and_separate_transcript_reply_binding",true);result.putBoolean("two_level_meter_settled_and_quiet_baseline",true);
        snapshots(target);result.putBoolean("screenshots_use_synthetic_ui_data",true);
        click("nav_settings");click("wake_sensitivity");choose("Sensitive -");check(prefs.getString("wake_sensitivity","").equals("sensitive"),"Sensitive choice not persisted");click("wake_sensitivity");choose("Balanced -");check(prefs.getString("wake_sensitivity","").equals("balanced"),"Balanced choice not persisted");result.putBoolean("sensitivity_control_persisted",true);
        prefs.edit().putString("update_release","{\"version_code\":999,\"version_name\":\"fixture\"}").putString("update_status","Fixture update ready").apply();idle();check(view("install_update").getVisibility()==View.VISIBLE,"Downloaded update install hidden");prefs.edit().remove("update_release").apply();idle();check(view("install_update").getVisibility()==View.GONE,"Stale update install displayed");result.putBoolean("update_ready_visibility",true);
        check(target.checkSelfPermission("android.permission.RECORD_AUDIO")==PackageManager.PERMISSION_GRANTED,"Grant microphone on emulator before lifecycle QA");click("nav_voice");click("background_listening");awaitMic(true,15000);check(prefs.getBoolean("wake_enabled",false),"Background toggle did not enable wake");click("background_listening");awaitMic(false,5000);check(!prefs.getBoolean("wake_enabled",true),"Background toggle did not disable wake");
        int pending=VoiceOutbox.pending(target);click("test_wake");awaitMic(true,15000);check(prefs.getBoolean("voice_listening_test",false),"Local wake test not enabled");click("background_listening");check(prefs.getBoolean("ui_test_background_desired",false)&&prefs.getBoolean("voice_listening_test",false),"Test toggle changed action mode prematurely");click("background_listening");click("test_wake");awaitMic(false,5000);check(!prefs.getBoolean("voice_listening_test",true)&&!prefs.getBoolean("wake_enabled",true),"Finished test did not restore background off");check(VoiceOutbox.pending(target)==pending,"Wake UI test created a command");result.putBoolean("background_on_off_and_local_test_state",true);result.putBoolean("local_test_ui_no_voice_outbox",true);
        switches(result);recipes(target,result);undo(target,result);widget(target,result);shared(target,result);appearance(target,result);
        result.putString("theme",theme);result.putString("stream","Actual UI inputs, focus, cache, offline changes, microphone state and local-test controls passed; no cloud requests.");}
    }catch(Throwable error){try{android.graphics.Bitmap failure=getUiAutomation().takeScreenshot();File directory=new File(target.getExternalFilesDir(null),"ui-qa");directory.mkdirs();try(OutputStream output=new FileOutputStream(new File(directory,"failure.png"))){failure.compress(android.graphics.Bitmap.CompressFormat.PNG,100,output);}failure.recycle();AccessibilityNodeInfo window=getUiAutomation().getRootInActiveWindow();result.putString("active_window",window==null?"none":window.toString());}catch(Exception ignored){}result.putString("stream",android.util.Log.getStackTraceString(error));outcome=1;}finally{
        target.stopService(new Intent(target,VoiceService.class));if(activity!=null)runOnMainSync(()->activity.finish());JobScheduler jobs=target.getSystemService(JobScheduler.class);for(int id:new int[]{210,211,212,216,218,219})jobs.cancel(id);if(before!=null)restore();try{File chatFile=new File(target.getFilesDir(),"voice-chat.json");if(chatBefore==null)chatFile.delete();else java.nio.file.Files.write(chatFile.toPath(),chatBefore);}catch(Exception ignored){}
    }finish(outcome,result);}
    private void restore(){SharedPreferences.Editor edit=prefs.edit().clear();for(Map.Entry<String,?> entry:before.entrySet()){Object value=entry.getValue();String key=entry.getKey();if(value instanceof String)edit.putString(key,(String)value);else if(value instanceof Boolean)edit.putBoolean(key,(Boolean)value);else if(value instanceof Integer)edit.putInt(key,(Integer)value);else if(value instanceof Long)edit.putLong(key,(Long)value);else if(value instanceof Float)edit.putFloat(key,(Float)value);else if(value instanceof Set)edit.putStringSet(key,(Set<String>)value);}edit.commit();}
    private View view(String tag){View found=activity.getWindow().getDecorView().findViewWithTag(tag);check(found!=null,"Missing UI tag: "+tag);return found;}
    private void click(String tag){runOnMainSync(()->view(tag).performClick());idle();}
    private void idle(){waitForIdleSync();try{Thread.sleep(350);}catch(InterruptedException interrupted){Thread.currentThread().interrupt();}waitForIdleSync();}
    private void awaitMic(boolean value,long milliseconds)throws Exception{long end=SystemClock.elapsedRealtime()+milliseconds;while(SystemClock.elapsedRealtime()<end){if(prefs.getBoolean("voice_mic_active",false)==value){idle();return;}String status=prefs.getString("voice_status","");if(value&&(status.startsWith("Voice stopped:")||status.startsWith("Microphone could not start:")))throw new AssertionError(status);Thread.sleep(50);}throw new AssertionError("Microphone did not reach "+value+": "+prefs.getString("voice_status",""));}
    private void choose(String text){runOnMainSync(()->((android.view.inputmethod.InputMethodManager)activity.getSystemService(Context.INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(activity.getWindow().getDecorView().getWindowToken(),0));idle();AccessibilityNodeInfo root=null;List<AccessibilityNodeInfo> nodes=java.util.Collections.emptyList();long deadline=SystemClock.elapsedRealtime()+4000;while(SystemClock.elapsedRealtime()<deadline){root=getUiAutomation().getRootInActiveWindow();if(root!=null){nodes=root.findAccessibilityNodeInfosByText(text);if(!nodes.isEmpty())break;}try{Thread.sleep(100);}catch(InterruptedException interrupted){Thread.currentThread().interrupt();break;}}check(root!=null,"Choice dialog absent");check(!nodes.isEmpty(),"Missing choice option: "+text);android.graphics.Rect bounds=new android.graphics.Rect();nodes.get(0).getBoundsInScreen(bounds);check(!bounds.isEmpty(),"Choice option has no visible bounds");long at=SystemClock.uptimeMillis();sendPointerSync(MotionEvent.obtain(at,at,MotionEvent.ACTION_DOWN,bounds.centerX(),bounds.centerY(),0));sendPointerSync(MotionEvent.obtain(at,at+30,MotionEvent.ACTION_UP,bounds.centerX(),bounds.centerY(),0));idle();}
    private void snapshots(Context target)throws Exception {
        VoiceChat.user(target,"ui-visual-chat-fixture","Add bananas and sparkling water.",System.currentTimeMillis()-60000);VoiceChat.assistant(target,"ui-visual-chat-fixture","Added both items.",System.currentTimeMillis()-59000,"answer","");
        VoiceHistory.record(target,new JSONObject().put("task_id","ui-history-fixture").put("text","Add bananas and sparkling water.").put("reply","Added both items.").put("status","completed"));
        prefs.edit().putString("origin","https://assistant.example").putBoolean("wake_enabled",true).putString("voice_status","Listening locally for Hey Chat · experimental").putString("voice_user_text","Add bananas and sparkling water to my shopping list.").putString("voice_reply","Added both items.").putBoolean("voice_mic_active",true).putLong("voice_metrics_elapsed",SystemClock.elapsedRealtime()).putFloat("voice_level",.5f).apply();
        ((android.view.inputmethod.InputMethodManager)target.getSystemService(Context.INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(activity.getWindow().getDecorView().getWindowToken(),0);
        File folder=new File(target.getExternalFilesDir(null),"ui-qa");check(folder.isDirectory()||folder.mkdirs(),"Screenshot directory unavailable");
        for(String page:new String[]{"voice","shopping","activity","settings"}){prefs.edit().putLong("voice_metrics_elapsed",SystemClock.elapsedRealtime()).apply();click("nav_"+page);android.graphics.Bitmap bitmap=getUiAutomation().takeScreenshot();check(bitmap!=null,"Screenshot unavailable");try(OutputStream output=new FileOutputStream(new File(folder,theme+"-"+page+".png"))){check(bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,output),"Screenshot encoding failed");}bitmap.recycle();}
        if(Build.VERSION.SDK_INT>=30){int appearance=activity.getWindow().getInsetsController().getSystemBarsAppearance();check(((appearance&WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS)!=0)==(theme.equals("light")||(theme.equals("sun")&&!DaylightTheme.dark(System.currentTimeMillis()))),"Wrong light/dark status icon appearance");}
        new File(target.getFilesDir(),"voice-receipts/ui-history-fixture.json").delete();prefs.edit().putString("origin","").putBoolean("wake_enabled",false).putBoolean("voice_mic_active",false).putFloat("voice_level",0f).putString("voice_status","Microphone off").apply();idle();
    }
    private static JSONObject item(String id,String name)throws JSONException{return new JSONObject().put("id",id).put("name",name).put("quantity","").put("complete",0).put("version",1);}
    private boolean visible(String text){AccessibilityNodeInfo root=getUiAutomation().getRootInActiveWindow();return root!=null&&!root.findAccessibilityNodeInfosByText(text).isEmpty();}
    /** Looked up and tapped in one main-thread task, before the sync that the commit starts can post its own redraw. */
    private View described(String description){ArrayList<View> found=new ArrayList<>();activity.getWindow().getDecorView().findViewsWithText(found,description,View.FIND_VIEWS_WITH_CONTENT_DESCRIPTION);return found.isEmpty()?null:found.get(0);}
    private static void pause(long milliseconds){try{Thread.sleep(milliseconds);}catch(InterruptedException interrupted){Thread.currentThread().interrupt();}}
    private static boolean committed(Context target,int at,String id)throws JSONException{JSONArray queue=Cloud.queue(target);JSONObject change=queue.length()>at?queue.getJSONObject(at):null;return change!=null&&change.getString("operation").equals("complete")&&change.getString("target").equals(id)&&change.getInt("version")==1;}
    /** A ticked row waits MainShopping.UNDO_MS before it reaches the outbox: Undo drops it, ticking another row or leaving the screen commits it at once. */
    private void undo(Context target,Bundle result)throws Exception{
        JSONObject cached=Cloud.cached(target);cached.put("items",new JSONArray().put(item("undo-eggs","Eggs")).put(item("undo-rice","Rice")).put(item("undo-oats","Oats")));prefs.edit().putString("snapshot",cached.toString()).putString("outbox","[]").apply();idle();click("nav_shopping");
        check(visible("Eggs, tap to mark as bought")&&visible("Rice, tap to mark as bought"),"Open items not offered for ticking");
        choose("Eggs, tap to mark as bought");check(Cloud.queue(target).length()==0&&visible("Eggs, marked as bought, tap to undo"),"A tick reached the outbox inside the undo window or lost its state");
        choose("Eggs, marked as bought, tap to undo");pause(MainShopping.UNDO_MS+500);idle();check(Cloud.queue(target).length()==0&&visible("Eggs, tap to mark as bought"),"Undo did not keep the item");
        choose("Eggs, tap to mark as bought");pause(MainShopping.UNDO_MS+500);idle();check(committed(target,0,"undo-eggs"),"A tick was not committed after the undo window");
        choose("Rice, tap to mark as bought");final boolean[] second=new boolean[1];
        runOnMainSync(()->{View oats=described("Oats, tap to mark as bought");if(oats!=null)oats.performClick();second[0]=described("Oats, marked as bought, tap to undo")!=null;});
        check(second[0],"A second tick inside the undo window lost its state");check(committed(target,1,"undo-rice")&&Cloud.queue(target).length()==2,"Ticking another row did not commit the first");
        runOnMainSync(()->callActivityOnPause(activity));check(committed(target,2,"undo-oats")&&Cloud.queue(target).length()==3,"Leaving the screen did not commit the tick");runOnMainSync(()->callActivityOnResume(activity));idle();
        result.putBoolean("shopping_tick_undo_window_and_commit_rules",true);
    }
    /** The widget is inflated by the launcher, so an inflate error shows only as "Problem loading widget"; Add must land on Shopping with the field focused. */
    private void widget(Context target,Bundle result)throws Exception{
        JSONObject cached=Cloud.cached(target);cached.put("items",new JSONArray().put(item("widget-eggs","Eggs")).put(item("widget-rice","Rice")).put(item("widget-oats","Oats")));prefs.edit().putString("snapshot",cached.toString()).putString("outbox","[]").apply();idle();
        for(boolean night:new boolean[]{false,true}){
            android.content.res.Configuration configuration=new android.content.res.Configuration(target.getResources().getConfiguration());configuration.uiMode=(configuration.uiMode&~android.content.res.Configuration.UI_MODE_NIGHT_MASK)|(night?android.content.res.Configuration.UI_MODE_NIGHT_YES:android.content.res.Configuration.UI_MODE_NIGHT_NO);
            final Context themed=target.createConfigurationContext(configuration);final View[] inflated=new View[2];final String mode=night?"night":"day";
            runOnMainSync(()->{FrameLayout parent=new FrameLayout(themed);inflated[0]=ShoppingWidget.build(themed,6).apply(themed,parent);inflated[1]=new RemoteViews(themed.getPackageName(),R.layout.widget_preview).apply(themed,parent);});
            check(inflated[0].findViewById(R.id.add)!=null&&inflated[0].findViewById(R.id.refresh)!=null&&inflated[1]!=null,"Widget did not inflate in "+mode+" mode");
            check(((ViewGroup)inflated[0].findViewById(R.id.rows)).getChildCount()==3,"Widget rows do not match the list in "+mode+" mode");
            runOnMainSync(()->inflated[0]=ShoppingWidget.build(themed,2).apply(themed,new FrameLayout(themed)));check(((ViewGroup)inflated[0].findViewById(R.id.rows)).getChildCount()==2&&((TextView)inflated[0].findViewById(R.id.status)).getText().toString().contains("1 more item"),"Widget did not cap its rows to the height");
        }
        click("nav_voice");ShoppingWidget.add(target).send();idle();pause(600);
        check(view("shopping_item").isShown()&&view("shopping_item").hasFocus(),"Widget Add did not open Shopping with the add field focused");check(!activity.getIntent().hasExtra(ShoppingWidget.EXTRA_TAB)&&!activity.getIntent().hasExtra(ShoppingWidget.EXTRA_FOCUS_ADD),"Widget extras were not consumed");
        result.putBoolean("widget_layouts_inflate_day_and_night_and_add_focuses_the_field",true);
    }
    /** Runs the trigger and returns the MainActivity instance that was created in response. */
    private MainActivity recreated(Context target,Runnable trigger)throws Exception{
        final MainActivity[] created=new MainActivity[1];
        Application.ActivityLifecycleCallbacks watcher=new Application.ActivityLifecycleCallbacks(){
            @Override public void onActivityCreated(Activity a,Bundle state){if(a instanceof MainActivity)created[0]=(MainActivity)a;}
            @Override public void onActivityStarted(Activity a){}@Override public void onActivityResumed(Activity a){}@Override public void onActivityPaused(Activity a){}@Override public void onActivityStopped(Activity a){}@Override public void onActivitySaveInstanceState(Activity a,Bundle state){}@Override public void onActivityDestroyed(Activity a){}
        };
        Application application=(Application)target.getApplicationContext();application.registerActivityLifecycleCallbacks(watcher);
        try{trigger.run();long end=SystemClock.elapsedRealtime()+10000;while(created[0]==null&&SystemClock.elapsedRealtime()<end)pause(100);}finally{application.unregisterActivityLifecycleCallbacks(watcher);}
        check(created[0]!=null,"The screen was not recreated");idle();return created[0];
    }
    /** A shared recipe is handled once: recreating the screen must neither import it again nor jump back to Shopping. */
    private void shared(Context target,Bundle result)throws Exception{
        click("nav_shopping");
        target.startActivity(new Intent(target,MainActivity.class).setAction(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT,"Shared recipe fixture").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_SINGLE_TOP|Intent.FLAG_ACTIVITY_CLEAR_TOP));idle();pause(500);
        check(activity.getIntent().getAction()==null&&!activity.getIntent().hasExtra(Intent.EXTRA_TEXT),"The share intent was not consumed");
        click("nav_voice");activity=recreated(target,()->runOnMainSync(()->activity.recreate()));
        check(view("talk").isShown()&&!view("shopping_item").isShown(),"Recreating the screen replayed the share");
        result.putBoolean("shared_text_handled_once_across_recreate",true);
    }
    /** Every Appearance choice is stored and recreates the screen; the unset default is Sunrise and sunset. */
    private void appearance(Context target,Bundle result)throws Exception{
        String[][] steps={{"Sunrise & sunset","sun"},{"System","system"},{"Light","light"},{"Dark","dark"}};
        prefs.edit().putString("ui_theme","dark").commit();
        for(String[] step:steps){
            activity=recreated(target,()->{click("nav_settings");click("appearance");choose(step[0]);});
            check(prefs.getString("ui_theme","").equals(step[1]),"Appearance choice not stored: "+step[1]);
        }
        prefs.edit().remove("ui_theme").commit();check(AppUi.dark(target)==DaylightTheme.dark(System.currentTimeMillis()),"The default theme does not follow the sun");
        result.putBoolean("appearance_choices_stored_and_default_follows_the_sun",true);
    }
    /** A row marked to hide its descendants from accessibility services would also hide the switch inside it. */
    private void switches(Bundle result){
        check(view("background_listening").isImportantForAccessibility()&&view("transcription_preview").isImportantForAccessibility(),"A switch is hidden from accessibility services");
        result.putBoolean("switches_reachable_by_accessibility_services",true);
    }
    /** One sheet walks list, recipe and import: the Back button and the Back key step out, and an empty choice is refused with a reason. */
    private void recipes(Context target,Bundle result)throws Exception{
        click("nav_shopping");int queued=Cloud.queue(target).length();
        choose("Recipes");choose("Quick pasta");check(visible("Add selected to list")&&!visible("Import text"),"Recipe page not shown");
        choose("Back");check(visible("Import text"),"Back did not return to the recipe list");
        choose("Quick pasta");sendKeyDownUpSync(KeyEvent.KEYCODE_BACK);idle();check(visible("Import text"),"The Back key did not return to the recipe list");
        choose("Quick pasta");choose("500 g Pasta");choose("2 Tomatoes");choose("1 tbsp Oil");choose("Add selected to list");check(visible("Select at least one ingredient.")&&Cloud.queue(target).length()==queued,"An empty selection was not refused");
        choose("Back");choose("Import text");choose("Preview import");check(visible("Paste a recipe first."),"An empty import was not refused");
        sendKeyDownUpSync(KeyEvent.KEYCODE_BACK);idle();check(visible("Import text"),"Back did not leave the import page");
        sendKeyDownUpSync(KeyEvent.KEYCODE_BACK);idle();check(!visible("Import text"),"Back at the list did not close the sheet");
        result.putBoolean("recipe_sheet_back_navigation_and_validation",true);
    }
    private String texts(){StringBuilder result=new StringBuilder();collect(activity.getWindow().getDecorView(),result);return result.toString();}
    private void collect(View view,StringBuilder result){if(!view.isShown())return;if(view instanceof TextView)result.append(((TextView)view).getText()).append('\n');if(view instanceof ViewGroup){ViewGroup group=(ViewGroup)view;for(int index=0;index<group.getChildCount();index++)collect(group.getChildAt(index),result);}}
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
