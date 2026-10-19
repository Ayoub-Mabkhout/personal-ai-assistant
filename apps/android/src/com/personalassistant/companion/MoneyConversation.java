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
    final LinearLayout rows;final ScrollView scroll;final EditText input;final TextView status;final Button send,older;final ImageButton mic;
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
        LinearLayout bar=ui.row();bar.setPadding(ui.dp(12),ui.dp(8),ui.dp(16),ui.dp(8));bar.addView(ui.iconButton("back","Back",dialog::dismiss),new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));bar.addView(ui.heading(transaction==null?"Money specialist":"Correct this"),new LinearLayout.LayoutParams(0,-2,1));root.addView(bar);
        scroll=new ScrollView(activity);scroll.setFillViewport(true);rows=ui.column();rows.setPadding(ui.dp(20),ui.dp(8),ui.dp(20),ui.dp(16));scroll.addView(rows);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        if(transaction!=null)rows.addView(ui.detail("Explain what needs correcting. You can type or dictate; nothing is sent until you tap Send."));
        older=ui.quietButton("Earlier messages",()->fetch(true));older.setVisibility(View.GONE);root.addView(older);
        status=ui.detail("");status.setPadding(ui.dp(20),ui.dp(6),ui.dp(20),ui.dp(6));status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);root.addView(status);
        LinearLayout composer=ui.column();composer.setPadding(ui.dp(16),ui.dp(8),ui.dp(16),ui.dp(18));input=ui.field(transaction==null?"Ask about your spending":"What should I know?",Cloud.prefs(activity).getString(key+":draft",""),true);input.setMinLines(2);input.setMaxLines(5);input.setFilters(new InputFilter[]{new InputFilter.LengthFilter(4000)});composer.addView(input);
        LinearLayout actions=ui.row();mic=ui.iconButton("voice","Dictate message",this::dictate);actions.addView(mic,new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));send=ui.primaryButton("Send",this::send);actions.addView(send,MainParts.weighted(ui,1,10,0,0,0));composer.addView(actions,MainParts.params(ui,-1,-2,0,10,0,0));root.addView(composer);
        input.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int a,int b,int c){}public void onTextChanged(CharSequence s,int a,int b,int c){Cloud.prefs(activity).edit().putString(key+":draft",s.toString()).apply();}public void afterTextChanged(Editable value){}});
        dialog.setContentView(root);dialog.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE|WindowManager.LayoutParams.SOFT_INPUT_STATE_HIDDEN);
        root.setOnApplyWindowInsetsListener((v,insets)->{int[] bars=TaskViews.bars(insets);root.setPadding(bars[0],bars[1],bars[2],bars[3]);return insets;});
        dialog.setOnDismissListener(d->{closed=true;main.removeCallbacks(tick);open.remove(activity);if("dictate".equals(TaskVoice.mode(activity,voiceId))){Intent finish=TaskVoice.finish(activity,voiceId);if(finish!=null)activity.startService(finish);}});
        if(!Cloud.prefs(activity).getString(key+":pending","").isEmpty()){input.setEnabled(false);send.setText("Retry");status.setText("A saved message needs confirmation. Retry sends the same message.");}
    }
    final Runnable tick=new Runnable(){public void run(){if(closed||activity.isDestroyed()||!dialog.getWindow().getDecorView().hasWindowFocus())return;String words=input.isEnabled()?TaskVoice.take(activity,voiceId):"";if(!words.isEmpty())input.append((input.length()==0?"":" ")+words);String note=TaskVoice.takeNote(activity,voiceId);if(!note.isEmpty())status.setText(note);mic.setContentDescription("dictate".equals(TaskVoice.mode(activity,voiceId))?"Finish dictation":"Dictate message");if(transaction==null&&SystemClock.elapsedRealtime()>=nextFetch){nextFetch=SystemClock.elapsedRealtime()+5000;fetch(false);}main.postDelayed(this,1000);}};
    void dictate(){if(!input.isEnabled())return;if("dictate".equals(TaskVoice.mode(activity,voiceId))){Intent finish=TaskVoice.finish(activity,voiceId);if(finish!=null)activity.startService(finish);return;}if(TaskVoice.busy(activity,voiceId)){status.setText("End the other voice conversation first.");return;}activity.taskVoice("dictate:"+voiceId);status.setText("Dictating · tap the microphone again to finish.");}
    void safe(Runnable action){main.post(()->{if(!closed&&!activity.isDestroyed())action.run();});}
    void loadCache(){if(transaction!=null)return;try{JSONArray saved=new JSONArray(Cloud.prefs(activity).getString("money_chat_history","[]"));for(int i=0;i<saved.length();i++){JSONObject item=saved.getJSONObject(i);messages.put(item.getString("id"),item);}render();}catch(JSONException ignored){}}
    void fetch(boolean previous){if(loading||transaction!=null||previous&&cursor.isEmpty())return;loading=true;final String before=previous?cursor:"";network.execute(()->{try{JSONObject result=(JSONObject)Cloud.call(activity,"money/conversations"+(before.isEmpty()?"":"?before="+before),null,true);safe(()->{loading=false;JSONArray items=result.optJSONArray("items");for(int i=0;items!=null&&i<items.length();i++){JSONObject item=items.optJSONObject(i);if(item!=null)messages.put(item.optString("id"),item);}if(previous||cursor.isEmpty())cursor=result.optString("next_cursor","");older.setVisibility(cursor.isEmpty()?View.GONE:View.VISIBLE);render();});}catch(Exception error){safe(()->{loading=false;status.setText("Offline · saved messages shown. Reconnect to receive replies.");});}});}
    void render(){
        ArrayList<JSONObject> ordered=new ArrayList<>(messages.values());ordered.sort((a,b)->{int time=Double.compare(a.optDouble("created"),b.optDouble("created"));return time!=0?time:a.optString("id").compareTo(b.optString("id"));});JSONArray saved=new JSONArray();for(JSONObject item:ordered)saved.put(item);String signature=saved.toString();if(signature.equals(shown))return;shown=signature;Cloud.prefs(activity).edit().putString("money_chat_history",signature).apply();boolean end=scroll.getScrollY()+scroll.getHeight()>=rows.getHeight()-ui.dp(80);rows.removeAllViews();
        if(ordered.isEmpty())rows.addView(ui.detail("Ask about spending, categories or an auditor question. Replies stay in this conversation."));
        for(JSONObject item:ordered){bubble("You",item.optString("text"),item.optDouble("created"),true);if(!item.isNull("answer")&&!item.optString("answer").isEmpty())bubble("Money specialist",item.optString("answer"),item.optDouble("answered"),false);else bubble("Money specialist","Waiting for the laptop…",0,false);}
        if(end)scroll.post(()->scroll.fullScroll(View.FOCUS_DOWN));
    }
    void bubble(String who,String text,double time,boolean mine){LinearLayout card=ui.card();card.setBackground(ui.outline(mine?ui.accentSoft:ui.surface,22,0,0));card.addView(ui.small(who+(time>0?" · "+AppUi.stamp((long)(time*1000)):"")));TextView words=ui.detail(text);words.setTextColor(ui.text);words.setTextIsSelectable(true);card.addView(words,MainParts.params(ui,-1,-2,0,6,0,0));rows.addView(card,MainParts.params(ui,-1,-2,mine?24:0,0,mine?0:24,12));}
    void send(){if(sending)return;if("dictate".equals(TaskVoice.mode(activity,voiceId))){status.setText("Finish dictation with the microphone, then tap Send.");return;}JSONObject body;try{String pending=Cloud.prefs(activity).getString(key+":pending","");if(!pending.isEmpty())body=new JSONObject(pending);else{String text=input.getText().toString().trim();if(text.isEmpty())return;body=new JSONObject().put("id",UUID.randomUUID().toString());if(transaction==null)body.put("text",text);else body.put("transaction",transaction).put("choice","clarify").put("note",text);if(!Cloud.prefs(activity).edit().putString(key+":pending",body.toString()).commit()){status.setText("Could not save the message on this phone.");return;}}}catch(JSONException error){status.setText("The saved message needs recovery.");return;}
        sending=true;input.setEnabled(false);send.setEnabled(false);status.setText("Sending…");network.execute(()->{try{JSONObject result=(JSONObject)Cloud.call(activity,transaction==null?"money/conversations":"money/answers",body,true);Cloud.prefs(activity).edit().remove(key+":pending").remove(key+":draft").apply();safe(()->{sending=false;input.setText("");input.setEnabled(true);send.setEnabled(true);send.setText("Send");status.setText("Sent · waiting for the laptop.");if(transaction==null){messages.put(result.optString("id"),result);render();nextFetch=0;}else dialog.dismiss();});}catch(Exception error){safe(()->{sending=false;send.setEnabled(true);send.setText("Retry");status.setText("Not confirmed · Retry sends the same saved message.");});}});
    }
}
