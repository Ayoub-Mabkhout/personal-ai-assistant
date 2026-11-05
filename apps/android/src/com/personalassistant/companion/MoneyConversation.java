package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.os.*;
import android.text.*;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.util.*;
import java.util.concurrent.*;

/** One durable Money conversation, with replies and editable text/voice clarification. */
final class MoneyConversation {
    private static final Map<Activity,MoneyConversation> open=new WeakHashMap<>();
    private static final ExecutorService network=Executors.newSingleThreadExecutor();
    final MainActivity activity;final AppUi ui;final String transaction,key,voiceId;final Dialog dialog;
    final LinearLayout rows;final ScrollView scroll;final EditText input;final TextView status;final Button send,older;final SpecialistChat chat;final AppUi.StatusChip specialist;
    final Handler main=new Handler(Looper.getMainLooper());final LinkedHashMap<String,JSONObject> messages=new LinkedHashMap<>();
    boolean closed,loading,sending;String cursor="",shown="";long nextFetch;
    static void chat(MainActivity activity){show(activity,null);}
    static void clarify(MainActivity activity,String transaction){show(activity,transaction);}
    static void close(Activity activity){MoneyConversation screen=open.remove(activity);if(screen!=null)screen.dialog.dismiss();}
    private static void show(MainActivity activity,String transaction){close(activity);MoneyConversation screen=new MoneyConversation(activity,transaction);open.put(activity,screen);screen.dialog.show();screen.dialog.getWindow().setLayout(-1,-1);screen.loadCache();screen.main.post(screen.tick);}
    MoneyConversation(MainActivity activity,String transaction){
        this.activity=activity;this.transaction=transaction;ui=new AppUi(activity);key=transaction==null?"money_chat":"money_review:"+transaction;voiceId=transaction==null?"money-specialist":"money-review-"+UUID.nameUUIDFromBytes(transaction.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        dialog=new Dialog(activity){@Override public void onWindowFocusChanged(boolean focus){super.onWindowFocusChanged(focus);main.removeCallbacks(tick);if(focus&&!closed)main.post(tick);}};
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);LinearLayout root=ui.column();root.setBackground(ui.pageBackground());root.setFitsSystemWindows(true);
        LinearLayout bar=ui.row();bar.setPadding(ui.dp(12),ui.dp(8),ui.dp(16),ui.dp(8));bar.addView(ui.iconButton("back","Back",dialog::dismiss),new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));bar.addView(ui.heading(transaction==null?"Money":"Not quite"),new LinearLayout.LayoutParams(0,-2,1));specialist=ui.statusChip("Money specialist · Checking…","neutral");if(transaction==null)bar.addView(specialist);root.addView(bar);
        scroll=new ScrollView(activity);scroll.setFillViewport(true);rows=ui.column();rows.setPadding(ui.dp(20),ui.dp(8),ui.dp(20),ui.dp(16));scroll.addView(rows);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        if(transaction!=null)rows.addView(ui.detail("Explain what needs correcting. You can type or dictate; nothing is sent until you tap Send."));
        older=ui.quietButton("Earlier messages",()->fetch(true));older.setVisibility(View.GONE);root.addView(older);
        status=ui.detail("");status.setPadding(ui.dp(20),ui.dp(6),ui.dp(20),ui.dp(6));status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);root.addView(status);
        chat=new SpecialistChat(activity,ui,transaction==null?"Ask about your spending":"What should I know?",
            Cloud.prefs(activity).getString(key+":draft",""),key,voiceId,transaction==null,4000,this::send);
        input=chat.input;send=chat.send;root.addView(chat.view);
        input.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int a,int b,int c){}public void onTextChanged(CharSequence s,int a,int b,int c){Cloud.prefs(activity).edit().putString(key+":draft",s.toString()).apply();}public void afterTextChanged(Editable value){}});
        dialog.setContentView(root);dialog.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE|WindowManager.LayoutParams.SOFT_INPUT_STATE_HIDDEN);
        root.setOnApplyWindowInsetsListener((v,insets)->{int[] bars=TaskViews.bars(insets);root.setPadding(bars[0],bars[1],bars[2],bars[3]);return insets;});
        dialog.setOnDismissListener(d->{closed=true;main.removeCallbacks(tick);open.remove(activity);chat.finishDictation();});
        if(!Cloud.prefs(activity).getString(key+":pending","").isEmpty()){chat.enabled(false);send.setText("Retry");status.setText("A saved message needs confirmation. Retry sends the same message.");}
    }
    final Runnable tick=new Runnable(){public void run(){if(closed||activity.isDestroyed()||!dialog.getWindow().getDecorView().hasWindowFocus())return;chat.captureDictation();if(transaction==null)chat.refreshFiles();String note=TaskVoice.takeNote(activity,voiceId);if(!note.isEmpty())status.setText(note);if(transaction==null&&SystemClock.elapsedRealtime()>=nextFetch){boolean pending=false;for(JSONObject item:messages.values())if(item.isNull("answer")||item.optString("answer").isEmpty()){pending=true;break;}nextFetch=SystemClock.elapsedRealtime()+(pending?1000:5000);fetch(false);}main.postDelayed(this,1000);}};
    void safe(Runnable action){main.post(()->{if(!closed&&!activity.isDestroyed())action.run();});}
    void loadCache(){if(transaction!=null)return;try{JSONArray saved=new JSONArray(Cloud.prefs(activity).getString("money_chat_history","[]"));for(int i=0;i<saved.length();i++){JSONObject item=saved.getJSONObject(i);messages.put(item.getString("id"),item);}render();}catch(JSONException ignored){}}
    void fetch(boolean previous){if(loading||transaction!=null||previous&&cursor.isEmpty())return;loading=true;final String before=previous?cursor:"";network.execute(()->{try{JSONObject result=(JSONObject)Cloud.call(activity,"money/conversations"+(before.isEmpty()?"":"?before="+before),null,true);safe(()->{loading=false;JSONArray items=result.optJSONArray("items");for(int i=0;items!=null&&i<items.length();i++){JSONObject item=items.optJSONObject(i);if(item!=null)messages.put(item.optString("id"),item);}JSONObject readiness=result.optJSONObject("specialist");if(readiness!=null)AssistantStatus.show(specialist,"Money specialist",readiness.optString("state"));if(previous||cursor.isEmpty())cursor=result.optString("next_cursor","");older.setVisibility(cursor.isEmpty()?View.GONE:View.VISIBLE);render();});}catch(Exception error){safe(()->{loading=false;AssistantStatus.show(specialist,"Money specialist","unavailable");status.setText("Offline · saved messages shown. Reconnect to receive replies.");});}});}
    void render(){
        ArrayList<JSONObject> ordered=new ArrayList<>(messages.values());ordered.sort((a,b)->{int time=Double.compare(a.optDouble("created"),b.optDouble("created"));return time!=0?time:a.optString("id").compareTo(b.optString("id"));});JSONArray saved=new JSONArray();for(JSONObject item:ordered)saved.put(item);String signature=saved.toString();if(signature.equals(shown))return;shown=signature;Cloud.prefs(activity).edit().putString("money_chat_history",signature).apply();boolean end=scroll.getScrollY()+scroll.getHeight()>=rows.getHeight()-ui.dp(80);rows.removeAllViews();
        if(ordered.isEmpty())rows.addView(ui.detail("Ask about spending, categories or an auditor question. Replies stay in this conversation."));
        for(JSONObject item:ordered){SpecialistChat.bubble(activity,ui,rows,"You",item.optString("text"),item.optDouble("created"),true,item.optJSONArray("attachments"));if(!item.isNull("answer")&&!item.optString("answer").isEmpty())bubble("Money specialist",item.optString("answer"),item.optDouble("answered"),false);else if(!item.optString("partial_answer","").isEmpty())bubble("Money specialist · Answering…",item.optString("partial_answer"),0,false);else bubble("Money specialist","Queued for the money specialist…",0,false);}
        if(end)scroll.post(()->scroll.fullScroll(View.FOCUS_DOWN));
    }
    void bubble(String who,String text,double time,boolean mine){
        SpecialistChat.bubble(activity,ui,rows,who,text,time,mine,null);
    }
    void send(){if(sending)return;if(chat.dictating()){status.setText("Finish dictation with the microphone, then tap Send.");return;}JSONObject body;try{String pending=Cloud.prefs(activity).getString(key+":pending","");if(!pending.isEmpty())body=new JSONObject(pending);else{String text=input.getText().toString().trim();JSONArray files=transaction==null?TaskAttachments.ids(TaskAttachments.draft(activity,key)):new JSONArray();if(text.isEmpty()&&files.length()==0)return;if(text.isEmpty())text="Please review the attached files.";body=new JSONObject().put("id",UUID.randomUUID().toString());if(transaction==null)body.put("text",text).put("attachments",files);else body.put("transaction",transaction).put("choice","clarify").put("note",text);if(!Cloud.prefs(activity).edit().putString(key+":pending",body.toString()).commit()){status.setText("Could not save the message on this phone.");return;}}}catch(Exception error){status.setText("The saved message needs recovery.");return;}
        sending=true;chat.enabled(false);send.setEnabled(false);status.setText("Sending…");network.execute(()->{try{JSONArray files=body.optJSONArray("attachments");if(files!=null)TaskAttachments.upload(activity,files);JSONObject result=(JSONObject)Cloud.call(activity,transaction==null?"money/conversations":"money/answers",body,true);Cloud.prefs(activity).edit().remove(key+":pending").remove(key+":draft").remove("attachment_draft:"+key).apply();safe(()->{sending=false;input.setText("");chat.clearFiles();chat.enabled(true);send.setEnabled(true);send.setText("Send");status.setText("Sent · queued for the money specialist.");if(transaction==null){messages.put(result.optString("id"),result);render();nextFetch=0;}else dialog.dismiss();});}catch(Exception error){safe(()->{sending=false;send.setEnabled(true);send.setText("Retry");status.setText("Not confirmed · Retry sends the same saved message.");});}});
    }
}
