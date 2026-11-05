package com.personalassistant.companion;

import android.app.*;
import android.os.*;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.time.LocalDate;
import java.util.*;

/** One durable conversation. The relay accepts questions while the coach is offline. */
final class WorkoutCoach {
    final WorkoutScreen screen;final MainActivity a;final AppUi ui;
    WorkoutCoach(WorkoutScreen s){screen=s;a=s.a;ui=s.ui;}
    void open(JSONObject context,WorkoutLive live){open(context,live,"");}
    void open(JSONObject context,WorkoutLive live,String prefill){open(context,live,prefill,new JSONArray());}
    void open(JSONObject context,WorkoutLive live,String prefill,JSONArray photos){
        WorkoutViews.Sheet s=new WorkoutViews.Sheet(ui,"",false);
        AppUi.StatusChip state=ui.statusChip("Coach · Checking…","neutral");
        state.setTag("coach_state");
        s.bar.addView(state);
        LinearLayout items=ui.column();
        s.body.addView(items);
        String draft="coach-chat";
        String savedDraft=Cloud.prefs(a).getString("workout_coach_draft","");
        SpecialistChat chat=new SpecialistChat(a,ui,"Ask your coach",prefill.isEmpty()?savedDraft:prefill,
            draft,"workout-coach",true,8000,null);
        EditText input=chat.input;
        input.setTag("coach_input");
        Button send=chat.send;
        s.root.addView(chat.view);
        s.dialog.getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        input.addTextChangedListener(new android.text.TextWatcher(){
            public void beforeTextChanged(CharSequence value,int start,int count,int after){}
            public void onTextChanged(CharSequence value,int start,int before,int count){
                Cloud.prefs(a).edit().putString("workout_coach_draft",value.toString()).apply();
            }
            public void afterTextChanged(android.text.Editable value){}
        });
        Handler main=new Handler(Looper.getMainLooper());
        final String[] seen={""};
        Runnable[] poll=new Runnable[1];
        Runnable controls=new Runnable(){
            public void run(){
                if(!s.dialog.isShowing())return;
                if(s.dialog.getWindow().getDecorView().hasWindowFocus()){
                    chat.captureDictation();
                    chat.refreshFiles();
                    String note=TaskVoice.takeNote(a,chat.voice);
                    if(!note.isEmpty())Toast.makeText(a,note,Toast.LENGTH_SHORT).show();
                }
                main.postDelayed(this,500);
            }
        };
        s.dialog.setOnDismissListener(d->{main.removeCallbacks(controls);chat.finishDictation();});
        class ConversationPoll implements Runnable {
            String version="";boolean busy,online;int backoff;JSONArray latest=new JSONArray();final LinkedHashMap<String,JSONObject> local=new LinkedHashMap<>();
            void local(String id,String text,String phase){try{local.put(id,new JSONObject().put("id",id).put("question",text).put("state",phase).put("created",System.currentTimeMillis()/1000.0));}catch(JSONException ignored){}display();}
            void display(){
                JSONArray merged=new JSONArray();Set<String> ids=new HashSet<>();
                for(int i=0;latest!=null&&i<latest.length();i++){JSONObject row=latest.optJSONObject(i);if(row!=null){ids.add(row.optString("id"));merged.put(row);}}
                for(Map.Entry<String,JSONObject> row:local.entrySet())if(!ids.contains(row.getKey()))merged.put(row.getValue());
                String key=online+":"+merged;if(key.equals(seen[0]))return;
                boolean tail=seen[0].isEmpty()||s.scroll.getScrollY()+s.scroll.getHeight()>=s.body.getHeight()-ui.dp(80);
                seen[0]=key;paint(items,merged,live,poll[0],online);if(tail)s.scroll.post(()->s.scroll.fullScroll(View.FOCUS_DOWN));
            }
            public void run(){
                main.removeCallbacks(this);if(!s.dialog.isShowing()||busy)return;
                if(!s.dialog.getWindow().getDecorView().hasWindowFocus()){main.postDelayed(this,1000);return;}busy=true;String since=version;
                new Thread(()->{JSONObject r=null;try{r=(JSONObject)Cloud.call(a,"workout/trainer/conversation?limit=50"+(since.isEmpty()?"":"&since="+java.net.URLEncoder.encode(since,"UTF-8")+"&wait=10"),null,true);}catch(Exception ignored){}JSONObject got=r;
                    a.runOnUiThread(()->{busy=false;if(!s.dialog.isShowing())return;int delay=5000;
                        if(got==null){AssistantStatus.show(state,"Coach","unavailable");online=false;display();backoff=Math.min(30000,backoff==0?2000:backoff*2);delay=backoff;}
                        else{backoff=0;JSONObject st=got.optJSONObject("status");boolean on=st!=null&&st.optBoolean("available");AssistantStatus.show(state,"Coach",st==null?"unavailable":st.optString("state",on?"ready":"unavailable"));online=on;latest=got.optJSONArray("items");for(int i=0;latest!=null&&i<latest.length();i++){JSONObject row=latest.optJSONObject(i);if(row!=null)local.remove(row.optString("id"));}display();version=got.optString("version","");if(!version.isEmpty())delay=0;}
                        main.postDelayed(this,delay);
                    });
                },"coach-conversation").start();
            }
        }
        ConversationPoll conversation=new ConversationPoll();poll[0]=conversation;
        send.setOnClickListener(v->{if(chat.dictating()){chat.finishDictation();return;}
            JSONArray files;
            try{files=TaskAttachments.ids(TaskAttachments.draft(a,draft));}catch(Exception error){Toast.makeText(a,"Attachment needs recovery",Toast.LENGTH_SHORT).show();return;}
            String typed=input.getText().toString().trim();
            if(typed.isEmpty()&&files.length()==0)return;
            String text=typed.isEmpty()?"Please review the attached files.":typed;
            send.setEnabled(false);chat.enabled(false);String payloadKey=text+"\n"+context.toString()+"\n"+photos.toString()+"\n"+files;String previousKey=Cloud.prefs(a).getString("workout_coach_pending_key","");String id=payloadKey.equals(previousKey)?Cloud.prefs(a).getString("workout_coach_pending_id",WorkoutStore.id()):WorkoutStore.id();Cloud.prefs(a).edit().putString("workout_coach_pending_key",payloadKey).putString("workout_coach_pending_id",id).apply();conversation.local(id,text,"sending");new Thread(()->{String problem=null;boolean queued=false;try{TaskAttachments.upload(a,files);String syncProblem=WorkoutStore.sync(a);if(!syncProblem.isEmpty())throw new java.io.IOException(syncProblem);JSONObject response=(JSONObject)Cloud.call(a,"workout/trainer/questions",new JSONObject().put("id",id).put("text",text).put("attachments",files).put("photos",photos).put("photo_approval",photos.length()>0).put("context",context),true);queued="queued".equals(response.optString("state"));}catch(Cloud.HttpError e){problem=e.status==409?"Couldn’t queue this message. Your draft is still here.":"Your server refused the question.";}catch(Exception e){problem="No connection. Your draft is still here. Tap Send when connected.";}String m=problem;boolean saved=queued;a.runOnUiThread(()->{send.setEnabled(true);chat.enabled(true);if(m!=null){conversation.local(id,text,"unconfirmed");Toast.makeText(a,m,Toast.LENGTH_LONG).show();return;}conversation.local(id,text,"queued");if(saved)Toast.makeText(a,"Message queued. Check this Coach chat for the reply.",Toast.LENGTH_LONG).show();input.setText("");chat.clearFiles();while(photos.length()>0)photos.remove(photos.length()-1);Cloud.prefs(a).edit().remove("workout_coach_pending_key").remove("workout_coach_pending_id").apply();main.removeCallbacks(poll[0]);poll[0].run();});}).start();});
        s.show();poll[0].run();main.post(controls);}
    private void paint(LinearLayout items,JSONArray list,WorkoutLive live,Runnable poll,boolean online){items.removeAllViews();if(list==null||list.length()==0){items.addView(ui.detail(online?"Ask about a swap, fatigue, pain or your plan.":"The coach is offline. You can still send a message. The reply will appear in this chat when the coach is back."));return;}for(int i=0;i<list.length();i++){JSONObject q=list.optJSONObject(i);if(q==null)continue;JSONObject ctx=q.optJSONObject("context");if(ctx!=null&&("next_session_brief".equals(ctx.optString("purpose"))||"sprint_brief".equals(ctx.optString("purpose"))))continue;SpecialistChat.bubble(a,ui,items,"You",q.optString("question"),q.optDouble("created"),true,q.optJSONArray("attachments"));String st=q.optString("state"),partial=q.optString("partial_answer","");if("completed".equals(st)||"running".equals(st)&&!partial.isEmpty()){LinearLayout c=SpecialistChat.bubble(a,ui,items,"completed".equals(st)?"Coach":"Coach · Answering…","completed".equals(st)?q.optString("answer"):partial,q.optDouble("answered_at"),false,null);if("completed".equals(st))proposals(c,q,live,poll);}else items.addView(ui.type("sending".equals(st)?"Sending…":"unconfirmed".equals(st)?"Not confirmed. Your draft is saved; tap Send to retry.":"failed".equals(st)?"Your coach couldn't answer. Try again.":"queued".equals(st)?(online?"Queued. The reply will appear here.":"Queued. The reply will appear here when the coach is back online."):"Your coach is thinking…",13,18,500,0,"failed".equals(st)?ui.warning:ui.muted),WorkoutViews.gap(ui,8));}}
    /** Shows what each proposal would change next to what's there now; Apply takes them all, once. */
    private void proposals(LinearLayout c,JSONObject q,WorkoutLive live,Runnable poll){JSONArray list=q.optJSONArray("proposals");if(list==null||list.length()==0)return;boolean done=q.optInt("approved",0)!=0||q.optBoolean("approved");c.addView(ui.type("Proposed changes",12.5f,17,700,0,ui.accent),MainParts.params(ui,-1,-2,0,10,0,2));for(int i=0;i<list.length();i++){JSONObject p=list.optJSONObject(i);JSONObject now=WorkoutStore.data(a,p.optString("kind"),p.optString("id"));if("exercise".equals(p.optString("kind"))&&p.optJSONObject("data")!=null)c.addView(new WorkoutArt.Tile(ui,p.optJSONObject("data")),MainParts.params(ui,ui.dp(64),ui.dp(64),0,4,0,6));c.addView(ui.type("Before: "+describe(p.optString("kind"),now),12.5f,17,400,0,ui.muted));c.addView(ui.type(p.optBoolean("deleted")?"After: deleted."+("workout".equals(p.optString("kind"))?" Sprint progress and your next workout recalculate.":""):"After: "+describe(p.optString("kind"),p.optJSONObject("data")),12.5f,17,500,0,p.optBoolean("deleted")?ui.danger:ui.text),WorkoutViews.gap(ui,4));}
        if(done){c.addView(ui.type("Applied",13,18,600,0,ui.success));return;}Button apply=ui.quietButton("Apply changes",null);apply.setTag("coach_apply");apply.setOnClickListener(v->{if(live!=null&&!live.matchesSaved()){Toast.makeText(a,"Your workout changed since your coach saw it. Ask again before applying changes.",Toast.LENGTH_LONG).show();return;}apply.setEnabled(false);new Thread(()->{String problem=null;try{Cloud.call(a,"workout/trainer/"+q.optString("id")+"/approve",new JSONObject(),true);WorkoutStore.sync(a);}catch(Cloud.HttpError e){problem=e.status==409?"That changed since your coach answered. Ask again.":"Your server refused the change.";}catch(Exception e){problem="No connection. Nothing changed.";}String m=problem;a.runOnUiThread(()->{apply.setEnabled(true);if(m!=null){Toast.makeText(a,m,Toast.LENGTH_LONG).show();return;}if(live!=null)for(int i=0;i<list.length();i++){JSONObject p=list.optJSONObject(i);if(!"workout".equals(p.optString("kind"))||!p.optString("id").equals(live.d.optString("workout_id")))continue;if(p.optBoolean("deleted"))live.discard();else live.adopt(p.optJSONObject("data"));}screen.render();poll.run();});}).start();});c.addView(apply);}
    private String describe(String kind,JSONObject d){if(d==null)return "new "+kind;if("sprint".equals(kind)){JSONArray cycle=d.optJSONArray("cycle");return d.optString("name")+" · "+d.optString("phase")+" · "+d.optInt("target_sessions")+" workouts until "+d.optString("end")+(cycle==null?"":" · cycle of "+cycle.length());}if("template".equals(kind)){StringBuilder b=new StringBuilder(d.optString("name"));JSONArray ex=d.optJSONArray("exercises");for(int i=0;ex!=null&&i<ex.length();i++){JSONObject p=ex.optJSONObject(i);b.append(i==0?": ":", ").append(WorkoutStore.exerciseName(a,p.optString("exercise_id"))).append(' ').append(p.optInt("sets",1)).append('×').append(p.optInt("min_reps"));}return b.toString();}if(!"workout".equals(kind))return d.optString("name",kind);LinkedHashMap<String,StringBuilder> rows=new LinkedHashMap<>();JSONArray sets=d.optJSONArray("sets");for(int i=0;sets!=null&&i<sets.length();i++){JSONObject x=sets.optJSONObject(i);String n=WorkoutStore.exerciseName(a,x.optString("exercise_id"));if(!rows.containsKey(n))rows.put(n,new StringBuilder());StringBuilder b=rows.get(n);if(b.length()>0)b.append(", ");if(!x.isNull("distance_m")&&x.has("distance_m"))b.append(WorkoutUnits.distance(a,x.optDouble("distance_m"))).append(" in ").append(WorkoutViews.clock(x.optLong("seconds")));else{if(!x.isNull("weight_kg")&&x.has("weight_kg"))b.append(WorkoutUnits.load(a,x.optDouble("weight_kg"))).append(" × ");b.append(x.optInt("reps"));}if(!x.optBoolean("completed",true))b.append(" (open)");}StringBuilder out=new StringBuilder(d.optString("name"));LocalDate day=WorkoutStore.day(d);if(!day.equals(LocalDate.MIN))out.append(", ").append(day);for(Map.Entry<String,StringBuilder> e:rows.entrySet())out.append("\n").append(e.getKey()).append(": ").append(e.getValue());return out.toString();}
}
