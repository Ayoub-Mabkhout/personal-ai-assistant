package com.personalassistant.companion;

import android.app.*;
import android.os.*;
import android.text.*;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.util.*;
import java.util.concurrent.*;

/**
 * One durable Money conversation, or a clarification of one transaction, in the task-chat style. A sent message shows
 * at once; the saved request (and its ID) stays on the phone until the server confirms it, so Retry never duplicates.
 */
final class MoneyConversation {
    private static final Map<Activity,MoneyConversation> open=new WeakHashMap<>();
    private static final ExecutorService network=Executors.newSingleThreadExecutor();
    private static final String NAME="Money specialist";
    final MainActivity activity;final AppUi ui;final String transaction,key,voiceId;final Dialog dialog;
    final ScrollView scroll;final LinearLayout body;final EditText input;final TextView status;final Button older;final SpecialistChat chat;final AppUi.StatusChip specialist;
    final SpecialistChat.Timeline timeline;final SpecialistThread thread=new SpecialistThread();
    final Handler main=new Handler(Looper.getMainLooper());final LinkedHashMap<String,JSONObject> messages=new LinkedHashMap<>();
    boolean closed,loading,sending,editing,online;String cursor="",shown="",readiness="";long nextFetch;
    static void chat(MainActivity activity){show(activity,null);}
    static void clarify(MainActivity activity,String transaction){show(activity,transaction);}
    static void close(Activity activity){MoneyConversation screen=open.remove(activity);if(screen!=null)screen.dialog.dismiss();}
    private static void show(MainActivity activity,String transaction){
        close(activity);MoneyConversation screen=new MoneyConversation(activity,transaction);open.put(activity,screen);
        screen.dialog.show();screen.dialog.getWindow().setLayout(-1,-1);screen.loadCache();
        if(transaction==null)AssistantStatus.timeout(screen.specialist,NAME);
        screen.main.post(screen.tick);
    }

    MoneyConversation(MainActivity activity,String transaction){
        this.activity=activity;this.transaction=transaction;ui=new AppUi(activity);key=transaction==null?"money_chat":"money_review:"+transaction;
        voiceId=transaction==null?"money-specialist":"money-review-"+UUID.nameUUIDFromBytes(transaction.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        dialog=ui.sheet();
        LinearLayout root=ui.column();root.setBackground(ui.pageBackground());
        LinearLayout bar=ui.row();bar.setPadding(ui.dp(12),ui.dp(8),ui.dp(16),ui.dp(8));
        bar.addView(ui.iconButton("back","Back",dialog::dismiss),new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));
        bar.addView(ui.heading(transaction==null?"Money":"Not quite"),new LinearLayout.LayoutParams(0,-2,1));
        specialist=ui.statusChip(WorkerReadiness.label(NAME,""),"neutral");specialist.setTag("money_state");
        if(transaction==null)bar.addView(specialist);
        root.addView(bar);
        scroll=new ScrollView(activity);scroll.setFillViewport(true);body=ui.column();body.setPadding(ui.dp(20),ui.dp(8),ui.dp(20),ui.dp(16));scroll.addView(body);
        root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        older=ui.quietButton("Earlier messages",()->fetch(true));older.setVisibility(View.GONE);body.addView(older);
        if(transaction!=null)body.addView(ui.detail("Explain what needs correcting. You can type or dictate; nothing is sent until you tap Send."));
        timeline=new SpecialistChat.Timeline(activity,ui,scroll,body);body.addView(timeline.rows);
        timeline.retry=id->retry();timeline.edit=id->edit();
        timeline.extras=new SpecialistChat.Timeline.Extras(){
            public String signature(SpecialistThread.Row row){JSONObject item=messages.get(row.id);JSONArray files=item==null||!row.user()?null:item.optJSONArray("attachments");return files==null||files.length()==0?"":files.toString();}
            public void fill(SpecialistThread.Row row,LinearLayout box){JSONObject item=messages.get(row.id);if(item!=null)TaskAttachments.show(activity,ui,box,item.optJSONArray("attachments"));}
        };
        status=ui.detail("");status.setTag("money_status");status.setPadding(ui.dp(20),ui.dp(6),ui.dp(20),ui.dp(6));status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);status.setVisibility(View.GONE);root.addView(status);
        chat=new SpecialistChat(activity,ui,transaction==null?"Ask about your spending":"What should I know?",
            Cloud.prefs(activity).getString(key+":draft",""),key,voiceId,transaction==null,4000,this::send);
        input=chat.input;input.setTag("money_input");chat.send.setTag("money_send");root.addView(chat.view);
        input.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int a,int b,int c){}public void onTextChanged(CharSequence s,int a,int b,int c){Cloud.prefs(activity).edit().putString(key+":draft",s.toString()).apply();}public void afterTextChanged(Editable value){}});
        dialog.setContentView(root);
        dialog.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE|WindowManager.LayoutParams.SOFT_INPUT_STATE_HIDDEN);
        SpecialistChat.insets(root);
        dialog.setOnDismissListener(d->{closed=true;main.removeCallbacksAndMessages(null);open.remove(activity);chat.finishDictation();});
        JSONObject pending=pending();
        if(pending!=null)thread.local(pending.optString("id"),text(pending),pending.optDouble("created_at",0),SpecialistThread.UNSENT,"Not confirmed by your server yet.");
        render();
    }

    void note(String text){status.setVisibility(text.isEmpty()?View.GONE:View.VISIBLE);AppUi.update(status,text);}

    /** Runs every second while the sheet is open; it skips work without window focus but never stops rescheduling. */
    final Runnable tick=new Runnable(){public void run(){
        if(closed||activity.isDestroyed())return;
        main.postDelayed(this,1000);
        if(!dialog.getWindow().getDecorView().hasWindowFocus())return;
        chat.captureDictation();if(transaction==null)chat.refreshFiles();
        String voice=TaskVoice.takeNote(activity,voiceId);if(!voice.isEmpty())note(voice);
        if(transaction==null&&SystemClock.elapsedRealtime()>=nextFetch){nextFetch=SystemClock.elapsedRealtime()+(thread.waiting()?1000:5000);fetch(false);}
    }};
    void safe(Runnable action){main.post(()->{if(!closed&&!activity.isDestroyed())action.run();});}

    JSONObject pending(){try{String raw=Cloud.prefs(activity).getString(key+":pending","");return raw.isEmpty()?null:new JSONObject(raw);}catch(JSONException e){return null;}}
    static String text(JSONObject body){return body.has("note")?body.optString("note"):body.optString("text");}

    void loadCache(){
        if(transaction!=null)return;
        try{JSONArray saved=new JSONArray(Cloud.prefs(activity).getString("money_chat_history","[]"));for(int i=0;i<saved.length();i++){JSONObject item=saved.getJSONObject(i);put(item);}render();}catch(JSONException ignored){}
    }

    void put(JSONObject item){
        String id=item.optString("id");if(id.isEmpty())return;messages.put(id,item);
        String answer=item.isNull("answer")?"":item.optString("answer",""),partial=item.optString("partial_answer","");
        thread.put(new SpecialistThread.Message(id,item.optString("text"),item.optDouble("created",0)).state(!answer.isEmpty()?"completed":!partial.isEmpty()?"running":"queued").answer(answer,item.optDouble("answered",0)).partial(partial));
        JSONObject pending=pending();
        if(pending!=null&&!sending&&id.equals(pending.optString("id")))Cloud.prefs(activity).edit().remove(key+":pending").remove(key+":pending_files").apply();
    }

    void fetch(boolean previous){
        if(loading||transaction!=null||previous&&cursor.isEmpty())return;loading=true;final String before=previous?cursor:"";
        network.execute(()->{
            try{
                JSONObject result=(JSONObject)Cloud.call(activity,"money/conversations"+(before.isEmpty()?"":"?before="+before),null,true);
                safe(()->{
                    loading=false;JSONArray items=result.optJSONArray("items");for(int i=0;items!=null&&i<items.length();i++){JSONObject item=items.optJSONObject(i);if(item!=null)put(item);}
                    JSONObject ready=result.optJSONObject("specialist");readiness=ready==null?WorkerReadiness.UNAVAILABLE:ready.optString("state",WorkerReadiness.UNAVAILABLE);
                    online=WorkerReadiness.online(readiness);AssistantStatus.show(specialist,NAME,readiness);
                    if(previous||cursor.isEmpty())cursor=result.optString("next_cursor","");older.setVisibility(cursor.isEmpty()?View.GONE:View.VISIBLE);
                    if(status.getText().toString().startsWith("Offline"))note("");
                    render();
                });
            }catch(Exception error){
                String problem=AssistantStatus.failure(activity,error);
                safe(()->{loading=false;readiness=problem;online=false;AssistantStatus.show(specialist,NAME,problem);note("Offline · saved messages shown. Reconnect to receive replies.");render();});
            }
        });
    }

    void render(){
        List<SpecialistThread.Row> rows=thread.rows(NAME,online);
        StringBuilder signature=new StringBuilder(String.valueOf(online));for(SpecialistThread.Row row:rows)signature.append(row).append(timeline.extras.signature(row));
        if(signature.toString().equals(shown))return;shown=signature.toString();
        if(transaction==null){
            JSONArray saved=new JSONArray();ArrayList<JSONObject> ordered=new ArrayList<>(messages.values());
            ordered.sort((a,b)->{int time=Double.compare(a.optDouble("created"),b.optDouble("created"));return time!=0?time:a.optString("id").compareTo(b.optString("id"));});
            for(JSONObject item:ordered)saved.put(item);
            Cloud.prefs(activity).edit().putString("money_chat_history",saved.toString()).apply();
        }
        timeline.render(rows,transaction!=null?"":"Ask about spending, categories or an auditor question. Replies stay in this conversation.");
    }

    void send(){
        if(sending)return;
        if(chat.dictating()){note("Finish dictation with the microphone, then tap Send.");return;}
        JSONObject saved=pending();String typed=input.getText().toString().trim();JSONObject request;
        try{
            JSONArray rows=transaction==null?TaskAttachments.draft(activity,key):new JSONArray();
            if(typed.isEmpty()&&rows.length()==0){if(saved!=null)retry();return;}
            if(saved!=null&&!editing&&!thread.listed(saved.optString("id"))){note("Retry or edit the unsent message first.");return;}
            JSONArray files=TaskAttachments.ids(rows);String text=typed.isEmpty()?"Please review the attached files.":typed;
            String identity=text+"\n"+files;
            String previous=saved==null?"":text(saved)+"\n"+(saved.optJSONArray("attachments")==null?new JSONArray():saved.optJSONArray("attachments"));
            request=new JSONObject().put("id",SpecialistThread.retryId(previous,saved==null?"":saved.optString("id"),identity,UUID.randomUUID().toString()));
            if(transaction==null)request.put("text",text).put("attachments",files);else request.put("transaction",transaction).put("choice","clarify").put("note",text);
            if(!Cloud.prefs(activity).edit().putString(key+":pending",request.toString()).putString(key+":pending_files",rows.toString()).commit()){note("Could not save the message on this phone.");return;}
        }catch(Exception error){note("The saved message needs recovery.");return;}
        input.setText("");chat.clearFiles();Cloud.prefs(activity).edit().remove(key+":draft").apply();
        deliver(request);
    }

    void retry(){JSONObject saved=pending();if(saved!=null&&!sending)deliver(saved);}

    void edit(){
        JSONObject saved=pending();if(saved==null||sending)return;
        String current=input.getText().toString().trim(),words=text(saved);
        input.setText(current.isEmpty()?words:current+" "+words);input.setSelection(input.length());
        if(transaction==null)chat.restoreFiles(Cloud.prefs(activity).getString(key+":pending_files",""));
        editing=true;thread.forget(saved.optString("id"));render();input.requestFocus();
    }

    /** The request body is sent exactly as saved, so the server's ID check makes a repeat harmless. */
    void deliver(JSONObject request){
        String id=request.optString("id"),words=text(request);
        sending=true;editing=false;chat.enabled(false);note("");
        thread.local(id,words,System.currentTimeMillis()/1000.0,SpecialistThread.SENDING,"");render();scroll.post(()->timeline.end(false));
        network.execute(()->{
            int code;JSONObject result=null;
            try{
                JSONArray files=request.optJSONArray("attachments");if(files!=null&&files.length()>0)TaskAttachments.upload(activity,files);
                result=(JSONObject)Cloud.call(activity,transaction==null?"money/conversations":"money/answers",request,true);code=200;
                Cloud.prefs(activity).edit().remove(key+":pending").remove(key+":pending_files").apply();
            }catch(Cloud.HttpError error){code=error.status;}
            catch(Exception error){code=0;}
            int status=code;JSONObject confirmed=result;
            safe(()->{
                sending=false;chat.enabled(true);
                if(status!=200){thread.local(id,words,0,SpecialistThread.UNSENT,SpecialistThread.problem(status));render();return;}
                if(transaction!=null){dialog.dismiss();Toast.makeText(activity,"Sent to the money specialist.",Toast.LENGTH_SHORT).show();return;}
                if(confirmed!=null&&id.equals(confirmed.optString("id")))put(confirmed);else thread.local(id,words,0,SpecialistThread.ACCEPTED,"");
                render();nextFetch=0;
            });
        });
    }
}
