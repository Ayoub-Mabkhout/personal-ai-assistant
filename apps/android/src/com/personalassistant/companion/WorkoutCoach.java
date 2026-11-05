package com.personalassistant.companion;

import android.os.*;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.time.LocalDate;
import java.util.*;

/**
 * One durable Coach conversation in the task-chat style. The relay accepts questions while the coach is offline; a sent
 * message shows at once, partial answers stream into the same bubble, and an unconfirmed message is kept on the phone
 * with its ID so Retry cannot duplicate it.
 */
final class WorkoutCoach {
    static final String PENDING="workout_coach_pending",DRAFT="workout_coach_draft",FILES="coach-chat",VOICE="workout-coach";
    final WorkoutScreen screen;final MainActivity a;final AppUi ui;
    WorkoutCoach(WorkoutScreen s){screen=s;a=s.a;ui=s.ui;}
    void open(JSONObject context,WorkoutLive live){open(context,live,"");}
    void open(JSONObject context,WorkoutLive live,String prefill){open(context,live,prefill,new JSONArray());}
    void open(JSONObject context,WorkoutLive live,String prefill,JSONArray photos){new Chat(context,live,prefill,photos).show();}

    private final class Chat {
        final JSONObject context;final WorkoutLive live;final JSONArray photos;
        final WorkoutViews.Sheet s=new WorkoutViews.Sheet(ui,"",false);
        final AppUi.StatusChip state=ui.statusChip(WorkerReadiness.label("Coach",""),"neutral");
        final SpecialistChat chat;final SpecialistChat.Timeline timeline;final SpecialistThread thread=new SpecialistThread();
        final Handler main=new Handler(Looper.getMainLooper());final HashMap<String,JSONObject> items=new HashMap<>();
        String version="",shown="",readiness="";boolean busy,online,sending,closed,editing;int backoff,generation;

        Chat(JSONObject context,WorkoutLive live,String prefill,JSONArray photos){
            this.context=context;this.live=live;this.photos=photos;
            state.setTag("coach_state");s.bar.addView(state);
            String savedDraft=Cloud.prefs(a).getString(DRAFT,"");
            chat=new SpecialistChat(a,ui,"Ask your coach",prefill.isEmpty()?savedDraft:prefill,FILES,VOICE,true,8000,this::submit);
            chat.input.setTag("coach_input");chat.send.setTag("coach_send");
            s.root.addView(chat.view);
            timeline=new SpecialistChat.Timeline(a,ui,s.scroll,s.body);s.body.addView(timeline.rows);
            timeline.retry=id->retry();timeline.edit=id->edit();
            timeline.extras=new SpecialistChat.Timeline.Extras(){
                public String signature(SpecialistThread.Row row){
                    JSONObject q=items.get(row.id);if(q==null)return "";
                    if(row.user()){JSONArray files=q.optJSONArray("attachments");return files==null||files.length()==0?"":files.toString();}
                    JSONArray list=q.optJSONArray("proposals");if(!"answer".equals(row.kind)||list==null||list.length()==0)return "";
                    return list+"|"+q.opt("approved")+"|"+(live==null?"":String.valueOf(live.matchesSaved()));
                }
                public void fill(SpecialistThread.Row row,LinearLayout box){
                    JSONObject q=items.get(row.id);if(q==null)return;
                    if(row.user())TaskAttachments.show(a,ui,box,q.optJSONArray("attachments"));else proposals(box,q,live,()->poll(true));
                }
            };
            SpecialistChat.insets(s.root);
            s.dialog.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE|WindowManager.LayoutParams.SOFT_INPUT_STATE_HIDDEN);
            chat.input.addTextChangedListener(new android.text.TextWatcher(){
                public void beforeTextChanged(CharSequence value,int start,int count,int after){}
                public void onTextChanged(CharSequence value,int start,int before,int count){Cloud.prefs(a).edit().putString(DRAFT,value.toString()).apply();}
                public void afterTextChanged(android.text.Editable value){}
            });
            s.dialog.setOnDismissListener(d->{closed=true;generation++;main.removeCallbacksAndMessages(null);chat.finishDictation();});
            JSONObject pending=pending();
            if(pending!=null)thread.local(pending.optString("id"),pending.optString("text"),pending.optDouble("created"),SpecialistThread.UNSENT,"Not confirmed by your server yet.");
            render();
        }

        void show(){s.show();AssistantStatus.timeout(state,"Coach");poll(true);main.post(controls);}

        /** Dictation, attachment and voice-note upkeep while the sheet has focus; never stops while it is open. */
        final Runnable controls=new Runnable(){public void run(){
            if(closed||!s.dialog.isShowing())return;
            if(s.dialog.getWindow().getDecorView().hasWindowFocus()){
                chat.captureDictation();chat.refreshFiles();
                String note=TaskVoice.takeNote(a,chat.voice);if(!note.isEmpty())Toast.makeText(a,note,Toast.LENGTH_SHORT).show();
            }
            main.postDelayed(this,500);
        }};

        JSONObject pending(){try{String raw=Cloud.prefs(a).getString(PENDING,"");return raw.isEmpty()?null:new JSONObject(raw);}catch(JSONException e){return null;}}

        void render(){
            ArrayList<SpecialistThread.Row> rows=new ArrayList<>(thread.rows("Coach",online));
            String key=online+":"+rows+":"+(live==null?"":live.matchesSaved());
            for(SpecialistThread.Row row:rows)if(timeline.extras!=null)key+=timeline.extras.signature(row);
            if(key.equals(shown))return;shown=key;
            timeline.render(rows,online?"Ask about a swap, fatigue, pain or your plan.":"The coach is offline. You can still send a message. The reply will appear in this chat when the coach is back.");
        }

        /** Long-polls the conversation while the sheet is open; the version changes with every partial revision. */
        void poll(boolean now){
            if(now){generation++;busy=false;version="";}
            main.removeCallbacks(pollLoop);if(closed||busy)return;
            if(!now&&!s.dialog.getWindow().getDecorView().hasWindowFocus()){main.postDelayed(pollLoop,1000);return;}
            busy=true;final String since=version;final int epoch=generation;
            new Thread(()->{
                JSONObject got=null;Exception failure=null;
                try{got=(JSONObject)Cloud.call(a,"workout/trainer/conversation?limit=50"+(since.isEmpty()?"":"&since="+java.net.URLEncoder.encode(since,"UTF-8")+"&wait=10"),null,true);}
                catch(Exception error){failure=error;}
                JSONObject result=got;String problem=failure==null?"":AssistantStatus.failure(a,failure);
                main.post(()->{
                    if(closed||epoch!=generation)return;busy=false;int delay;
                    if(result==null){readiness=problem;AssistantStatus.show(state,"Coach",problem);online=false;backoff=Math.min(30000,backoff==0?2000:backoff*2);delay=backoff;}
                    else{
                        backoff=0;JSONObject st=result.optJSONObject("status");online=st!=null&&st.optBoolean("available");
                        readiness=st==null?WorkerReadiness.UNAVAILABLE:st.optString("state",online?WorkerReadiness.READY:WorkerReadiness.UNAVAILABLE);
                        AssistantStatus.show(state,"Coach",readiness);
                        merge(result.optJSONArray("items"));version=result.optString("version","");delay=version.isEmpty()?5000:0;
                    }
                    render();main.postDelayed(pollLoop,delay);
                });
            },"coach-conversation").start();
        }
        final Runnable pollLoop=()->poll(false);

        void merge(JSONArray list){
            ArrayList<SpecialistThread.Message> rows=new ArrayList<>();items.clear();
            for(int i=0;list!=null&&i<list.length();i++){
                JSONObject q=list.optJSONObject(i);if(q==null)continue;
                JSONObject ctx=q.optJSONObject("context");
                if(ctx!=null&&("next_session_brief".equals(ctx.optString("purpose"))||"sprint_brief".equals(ctx.optString("purpose"))))continue;
                items.put(q.optString("id"),q);
                String st=q.optString("state");
                rows.add(new SpecialistThread.Message(q.optString("id"),q.optString("question"),q.optDouble("created",0)).state(st)
                    .answer("completed".equals(st)||"failed".equals(st)?q.optString("answer",""):"",q.optDouble("answered_at",0))
                    .partial("running".equals(st)?q.optString("partial_answer",""):""));
            }
            thread.replace(rows);
            JSONObject pending=pending();
            if(pending!=null&&thread.listed(pending.optString("id"))&&!sending)Cloud.prefs(a).edit().remove(PENDING).apply();
        }

        void submit(){
            if(chat.dictating()){chat.finishDictation();return;}
            if(sending)return;
            JSONArray rows;try{rows=TaskAttachments.draft(a,FILES);}catch(Exception error){Toast.makeText(a,"Attachment needs recovery",Toast.LENGTH_SHORT).show();return;}
            String typed=chat.input.getText().toString().trim();
            JSONObject saved=pending();
            if(typed.isEmpty()&&rows.length()==0){if(saved!=null)retry();return;}
            if(saved!=null&&!editing&&!thread.listed(saved.optString("id"))){Toast.makeText(a,"Retry or edit the unsent message first.",Toast.LENGTH_SHORT).show();return;}
            JSONObject body;
            try{
                JSONArray files=TaskAttachments.ids(rows);String text=typed.isEmpty()?"Please review the attached files.":typed;
                String key=text+"\n"+files+"\n"+photos;
                String id=SpecialistThread.retryId(saved==null?"":saved.optString("key"),saved==null?"":saved.optString("id"),key,WorkoutStore.id());
                body=new JSONObject().put("id",id).put("key",key).put("text",text).put("attachments",files).put("attachment_rows",rows.toString())
                    .put("photos",new JSONArray(photos.toString())).put("photo_approval",photos.length()>0).put("context",new JSONObject(context.toString()))
                    .put("created",System.currentTimeMillis()/1000.0);
            }catch(Exception error){Toast.makeText(a,"Couldn't prepare this message.",Toast.LENGTH_SHORT).show();return;}
            if(!Cloud.prefs(a).edit().putString(PENDING,body.toString()).commit()){Toast.makeText(a,"Couldn't save this message on the phone.",Toast.LENGTH_SHORT).show();return;}
            chat.input.setText("");chat.clearFiles();Cloud.prefs(a).edit().remove(DRAFT).apply();
            while(photos.length()>0)photos.remove(photos.length()-1);
            deliver(body);
        }

        void retry(){JSONObject saved=pending();if(saved!=null&&!sending)deliver(saved);}

        /** Edit returns the unsent text and files to the composer; sending them again gets a new ID only if they change. */
        void edit(){
            JSONObject saved=pending();if(saved==null||sending)return;
            String current=chat.input.getText().toString().trim();
            chat.input.setText(current.isEmpty()?saved.optString("text"):current+" "+saved.optString("text"));chat.input.setSelection(chat.input.length());
            chat.restoreFiles(saved.optString("attachment_rows"));
            JSONArray savedPhotos=saved.optJSONArray("photos");for(int i=0;savedPhotos!=null&&i<savedPhotos.length()&&photos.length()==0;i++)photos.put(savedPhotos.opt(i));
            // Keep the ID and key so an unchanged resend stays idempotent, but take it off screen until it is sent.
            editing=true;thread.forget(saved.optString("id"));render();chat.input.requestFocus();
        }

        void deliver(JSONObject body){
            String id=body.optString("id"),text=body.optString("text");
            sending=true;editing=false;chat.enabled(false);thread.local(id,text,body.optDouble("created"),SpecialistThread.SENDING,"");render();s.scroll.post(()->timeline.end(false));
            new Thread(()->{
                int status=-1;
                try{
                    JSONArray files=body.optJSONArray("attachments");if(files!=null&&files.length()>0)TaskAttachments.upload(a,files);
                    String syncProblem=WorkoutStore.sync(a);if(!syncProblem.isEmpty())throw new java.io.IOException(syncProblem);
                    Cloud.call(a,"workout/trainer/questions",new JSONObject().put("id",id).put("text",text).put("attachments",files==null?new JSONArray():files)
                        .put("photos",body.optJSONArray("photos")).put("photo_approval",body.optBoolean("photo_approval")).put("context",body.optJSONObject("context")),true);
                    status=200;
                }catch(Cloud.HttpError error){status=error.status;}
                catch(Exception error){status=0;}
                int code=status;
                main.post(()->{
                    sending=false;if(closed&&code!=200)return;
                    if(code==200){Cloud.prefs(a).edit().remove(PENDING).apply();if(closed)return;chat.enabled(true);thread.local(id,text,0,SpecialistThread.ACCEPTED,"");render();poll(true);return;}
                    chat.enabled(true);thread.local(id,text,0,SpecialistThread.UNSENT,SpecialistThread.problem(code));render();
                });
            },"coach-send").start();
        }
    }

    /** Shows what each proposal would change next to what's there now; Apply takes them all, once. */
    private void proposals(LinearLayout c,JSONObject q,WorkoutLive live,Runnable poll){JSONArray list=q.optJSONArray("proposals");if(list==null||list.length()==0)return;boolean done=q.optInt("approved",0)!=0||q.optBoolean("approved");c.addView(ui.type("Proposed changes",12.5f,17,700,0,ui.accent),MainParts.params(ui,-1,-2,0,10,0,2));for(int i=0;i<list.length();i++){JSONObject p=list.optJSONObject(i);JSONObject now=WorkoutStore.data(a,p.optString("kind"),p.optString("id"));if("exercise".equals(p.optString("kind"))&&p.optJSONObject("data")!=null)c.addView(new WorkoutArt.Tile(ui,p.optJSONObject("data")),MainParts.params(ui,ui.dp(64),ui.dp(64),0,4,0,6));c.addView(ui.type("Before: "+describe(p.optString("kind"),now),12.5f,17,400,0,ui.muted));c.addView(ui.type(p.optBoolean("deleted")?"After: deleted."+("workout".equals(p.optString("kind"))?" Sprint progress and your next workout recalculate.":""):"After: "+describe(p.optString("kind"),p.optJSONObject("data")),12.5f,17,500,0,p.optBoolean("deleted")?ui.danger:ui.text),WorkoutViews.gap(ui,4));}
        if(done){c.addView(ui.type("Applied",13,18,600,0,ui.success));return;}Button apply=ui.quietButton("Apply changes",null);apply.setTag("coach_apply");apply.setOnClickListener(v->{if(live!=null&&!live.matchesSaved()){Toast.makeText(a,"Your workout changed since your coach saw it. Ask again before applying changes.",Toast.LENGTH_LONG).show();return;}apply.setEnabled(false);new Thread(()->{String problem=null;try{Cloud.call(a,"workout/trainer/"+q.optString("id")+"/approve",new JSONObject(),true);WorkoutStore.sync(a);}catch(Cloud.HttpError e){problem=e.status==409?"That changed since your coach answered. Ask again.":"Your server refused the change.";}catch(Exception e){problem="No connection. Nothing changed.";}String m=problem;a.runOnUiThread(()->{apply.setEnabled(true);if(m!=null){Toast.makeText(a,m,Toast.LENGTH_LONG).show();return;}if(live!=null)for(int i=0;i<list.length();i++){JSONObject p=list.optJSONObject(i);if(!"workout".equals(p.optString("kind"))||!p.optString("id").equals(live.d.optString("workout_id")))continue;if(p.optBoolean("deleted"))live.discard();else live.adopt(p.optJSONObject("data"));}screen.render();poll.run();});}).start();});c.addView(apply);}
    private String describe(String kind,JSONObject d){if(d==null)return "new "+kind;if("sprint".equals(kind)){JSONArray cycle=d.optJSONArray("cycle");return d.optString("name")+" · "+d.optString("phase")+" · "+d.optInt("target_sessions")+" workouts until "+d.optString("end")+(cycle==null?"":" · cycle of "+cycle.length());}if("template".equals(kind)){StringBuilder b=new StringBuilder(d.optString("name"));JSONArray ex=d.optJSONArray("exercises");for(int i=0;ex!=null&&i<ex.length();i++){JSONObject p=ex.optJSONObject(i);b.append(i==0?": ":", ").append(WorkoutStore.exerciseName(a,p.optString("exercise_id"))).append(' ').append(p.optInt("sets",1)).append('×').append(p.optInt("min_reps"));}return b.toString();}if(!"workout".equals(kind))return d.optString("name",kind);LinkedHashMap<String,StringBuilder> rows=new LinkedHashMap<>();JSONArray sets=d.optJSONArray("sets");for(int i=0;sets!=null&&i<sets.length();i++){JSONObject x=sets.optJSONObject(i);String n=WorkoutStore.exerciseName(a,x.optString("exercise_id"));if(!rows.containsKey(n))rows.put(n,new StringBuilder());StringBuilder b=rows.get(n);if(b.length()>0)b.append(", ");if(!x.isNull("distance_m")&&x.has("distance_m"))b.append(WorkoutUnits.distance(a,x.optDouble("distance_m"))).append(" in ").append(WorkoutViews.clock(x.optLong("seconds")));else{if(!x.isNull("weight_kg")&&x.has("weight_kg"))b.append(WorkoutUnits.load(a,x.optDouble("weight_kg"))).append(" × ");b.append(x.optInt("reps"));}if(!x.optBoolean("completed",true))b.append(" (open)");}StringBuilder out=new StringBuilder(d.optString("name"));LocalDate day=WorkoutStore.day(d);if(!day.equals(LocalDate.MIN))out.append(", ").append(day);for(Map.Entry<String,StringBuilder> e:rows.entrySet())out.append("\n").append(e.getKey()).append(": ").append(e.getValue());return out.toString();}
}
