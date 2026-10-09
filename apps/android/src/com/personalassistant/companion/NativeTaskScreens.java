package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.os.*;
import android.text.*;
import android.view.*;
import android.view.inputmethod.*;
import android.widget.*;
import org.json.*;
import java.util.*;
import java.util.concurrent.*;

/** Authenticated native task history and durable same-session continuation, shown as full-screen sheets. */
final class NativeTaskScreens {
    private static final ExecutorService network=Executors.newSingleThreadExecutor();
    private static final Map<Activity,List<Screen>> openScreens=new WeakHashMap<>();
    static void close(Activity activity){List<Screen> list=openScreens.remove(activity);if(list!=null)for(Screen screen:new ArrayList<>(list))screen.dialog.dismiss();}
    static void history(Activity a){List<Screen> list=openScreens.get(a);if(list!=null)for(Screen screen:list)if(screen instanceof History)return;new History(a).open();}
    static void detail(Activity a,String kind,String id){if(id!=null&&id.matches("[A-Za-z0-9_-]{1,160}"))new Detail(a,kind.equals("command")?"command":"agent",id).open();}
    static long timestamp(Object value){try{if(value instanceof Number)return ((Number)value).longValue()*1000;String raw=String.valueOf(value);return java.time.Instant.parse(raw).toEpochMilli();}catch(Exception ignored){return 0;}}
    static String state(String raw){if(raw.equals("leased")||raw.equals("running")||raw.equals("in_progress"))return "In progress";if(raw.equals("completed")||raw.equals("complete"))return "Completed";if(raw.equals("needs_input"))return "Needs your input";if(raw.equals("failed"))return "Failed";if(raw.equals("cancelled"))return "Cancelled";if(raw.equals("queued")||raw.equals("pending"))return "Queued";return raw.isEmpty()?"Received":raw.replace('_',' ');}
    private static String next(JSONObject page){return page.isNull("next_cursor")?"":page.optString("next_cursor","");}

    private abstract static class Screen {
        final Activity a;final AppUi ui;final Dialog dialog;final LinearLayout root,bar,body;final ScrollView scroll;final TextView status;final ImageButton refresh;final Handler main=new Handler(Looper.getMainLooper());boolean closed,registered;int inset;
        final BroadcastReceiver changes=new BroadcastReceiver(){@Override public void onReceive(Context c,Intent i){changed();}};
        Screen(Activity a,String title){
            this.a=a;ui=new AppUi(a);dialog=ui.sheet();root=ui.column();root.setBackground(ui.pageBackground());
            bar=ui.row();bar.setPadding(ui.dp(17),ui.dp(6),ui.dp(17),ui.dp(6));bar.addView(ui.iconButton("back","Back from "+title,dialog::dismiss),new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));
            TextView heading=ui.type(title,20,26,700,-.01f,ui.text);heading.setSingleLine(true);if(Build.VERSION.SDK_INT>=28)heading.setAccessibilityHeading(true);heading.setEllipsize(TextUtils.TruncateAt.END);LinearLayout.LayoutParams hp=new LinearLayout.LayoutParams(0,-2,1);hp.leftMargin=hp.rightMargin=ui.dp(10);bar.addView(heading,hp);
            refresh=ui.iconButton("refresh","Refresh",this::reload);bar.addView(refresh,new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));root.addView(bar);
            status=ui.type("",12.5f,18,500,0,ui.muted);status.setTag("native_task_status");status.setVisibility(View.GONE);status.setPadding(ui.dp(24),ui.dp(2),ui.dp(24),ui.dp(8));status.setCompoundDrawablePadding(ui.dp(6));status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);root.addView(status);
            scroll=new ScrollView(a);scroll.setFillViewport(true);body=ui.column();body.setPadding(ui.dp(20),ui.dp(4),ui.dp(20),ui.dp(24));scroll.addView(body);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
            root.setOnApplyWindowInsetsListener((v,insets)->{int[] bars=TaskViews.bars(insets);root.setPadding(bars[0],bars[1],bars[2],0);inset=bars[3];insets();return insets;});
            dialog.setContentView(root);
            dialog.setOnDismissListener(d->{closed=true;List<Screen> list=openScreens.get(a);if(list!=null){list.remove(this);if(list.isEmpty())openScreens.remove(a);}if(registered){a.unregisterReceiver(changes);registered=false;}});
            Window window=dialog.getWindow();window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE|WindowManager.LayoutParams.SOFT_INPUT_STATE_HIDDEN);if(Build.VERSION.SDK_INT>=29)window.setNavigationBarContrastEnforced(false);
        }
        void insets(){body.setPadding(ui.dp(20),ui.dp(4),ui.dp(20),ui.dp(24)+inset);}
        // AppUi.lift stops ancestors clipping their children; the root clips again once attached so the scrolled list cannot paint over the header.
        void open(){List<Screen> list=openScreens.get(a);if(list==null){list=new ArrayList<>();openScreens.put(a,list);}list.add(this);dialog.show();dialog.getWindow().setLayout(-1,-1);root.post(()->{root.setClipChildren(true);root.setClipToPadding(true);});if(Build.VERSION.SDK_INT>=33)a.registerReceiver(changes,new IntentFilter(NativeTasks.ACTION),Context.RECEIVER_NOT_EXPORTED);else a.registerReceiver(changes,new IntentFilter(NativeTasks.ACTION));registered=true;load();}
        void safe(Runnable r){main.post(()->{if(!closed&&!a.isDestroyed())r.run();});}
        void spin(){if(AppUi.motion())refresh.animate().rotationBy(360).setDuration(600).setInterpolator(AppUi.SLIDE).start();}
        void note(String text,String icon,boolean warn){int color=warn?ui.warning:ui.muted;status.setVisibility(text.isEmpty()?View.GONE:View.VISIBLE);AppUi.update(status,text);status.setTextColor(color);status.setCompoundDrawablesRelativeWithIntrinsicBounds(icon==null||text.isEmpty()?null:ui.glyph(icon,color,14),null,null,null);}
        void line(TextView view,String text){view.setVisibility(text.isEmpty()?View.GONE:View.VISIBLE);AppUi.update(view,text);}
        AppUi.StatusChip stateChip(String raw){AppUi.StatusChip chip=ui.statusChip(state(raw),"neutral");restyle(chip,raw);return chip;}
        void restyle(AppUi.StatusChip chip,String raw){String tone=AppUi.toneOf(raw);chip.tone(tone);if(tone.equals("neutral"))chip.setCompoundDrawablesWithIntrinsicBounds(ui.glyph("info",ui.muted,14),null,null,null);}
        abstract void load();
        abstract void reload();
        abstract void changed();
    }

    private static final class History extends Screen {
        final EditText search;final LinearLayout rows;final Button more;final List<JSONObject> items=new ArrayList<>();final Runnable lookup=()->fetch(false);String query="",cursor="",shown;int generation,pages;boolean busy,local;
        History(Activity a){
            super(a,"Task history");
            search=ui.field("Search requests and answers","",true);search.setTag("task_search");search.setImeOptions(EditorInfo.IME_ACTION_SEARCH);search.setPadding(ui.dp(18),ui.dp(14),ui.dp(18),ui.dp(14));search.setCompoundDrawablePadding(ui.dp(10));search.setCompoundDrawablesRelativeWithIntrinsicBounds(ui.glyph("search",ui.muted,20),null,null,null);
            LinearLayout find=ui.row();find.setPadding(ui.dp(20),ui.dp(2),ui.dp(20),ui.dp(12));find.addView(search,new LinearLayout.LayoutParams(-1,-2));root.addView(find,1);
            rows=ui.column();rows.setTag("task_history_rows");body.addView(rows);more=ui.quietButton("Load more",()->fetch(true));more.setTag("task_load_more");more.setVisibility(View.GONE);body.addView(more);
            search.setOnEditorActionListener((v,action,event)->{if(action!=EditorInfo.IME_ACTION_SEARCH)return false;main.removeCallbacks(lookup);fetch(false);((InputMethodManager)a.getSystemService(Context.INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(v.getWindowToken(),0);return true;});
            search.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int x,int count,int after){}public void onTextChanged(CharSequence s,int x,int before,int count){query=s.toString();generation++;main.removeCallbacks(lookup);main.postDelayed(lookup,400);}public void afterTextChanged(Editable e){}});
        }
        /** Mode 0 replaces the list, 1 appends the next page, 2 refreshes page one and keeps pages already loaded with Load more. */
        void merge(JSONObject value,int mode){
            List<JSONObject> page=new ArrayList<>();Set<String> ids=new HashSet<>();JSONArray array=value.optJSONArray("items");for(int n=0;array!=null&&n<array.length();n++){JSONObject item=array.optJSONObject(n);if(item!=null&&ids.add(item.optString("id")))page.add(item);}
            if(mode==0||(mode==2&&pages<=1)){items.clear();items.addAll(page);cursor=next(value);pages=1;return;}
            if(mode==1){Set<String> known=new HashSet<>();for(JSONObject item:items)known.add(item.optString("id"));for(JSONObject item:page)if(known.add(item.optString("id")))items.add(item);cursor=next(value);pages++;return;}
            List<JSONObject> tail=new ArrayList<>();for(JSONObject item:items)if(!ids.contains(item.optString("id")))tail.add(item);items.clear();items.addAll(page);items.addAll(tail);
        }
        @Override void changed(){if(!query.isEmpty()||busy)return;merge(NativeTasks.cachedHistory(a),2);render();}
        @Override void load(){merge(NativeTasks.cachedHistory(a),0);render();fetch(false);}
        @Override void reload(){main.removeCallbacks(lookup);fetch(false);}
        void fetch(boolean append){
            final int request=++generation;final String wanted=query,after=append?cursor:"";busy=true;more.setEnabled(false);spin();note("Loading task history...","refresh",false);
            network.execute(()->{try{NativeTasks.flush(a);JSONObject value=NativeTasks.history(a,wanted,after);safe(()->{if(request!=generation)return;busy=false;local=false;merge(value,append?1:0);render();note("Task history is up to date.","check",false);});}catch(Exception error){safe(()->{if(request!=generation)return;busy=false;if(!append)offline();render();note(query.isEmpty()?"Offline · showing tasks saved on this phone. Tap refresh to retry.":"Offline · showing matching tasks saved on this phone. Tap refresh to retry.","cloud-off",true);});}});
        }
        /** Without a connection a search only covers the first page saved on this phone; clearing it restores that page. */
        void offline(){
            if(query.isEmpty()&&!local)return;
            JSONArray page=NativeTasks.cachedHistory(a).optJSONArray("items"),match=new JSONArray();String needle=query.toLowerCase(Locale.ROOT);
            for(int n=0;page!=null&&n<page.length();n++){JSONObject item=page.optJSONObject(n);if(item!=null&&(item.optString("request")+" "+item.optString("summary")).toLowerCase(Locale.ROOT).contains(needle))match.put(item);}
            try{merge(new JSONObject().put("items",match),0);local=!query.isEmpty();}catch(JSONException ignored){}
        }
        void render(){
            more.setEnabled(!busy);more.setVisibility(cursor.isEmpty()||items.isEmpty()?View.GONE:View.VISIBLE);
            String signature=query+"|"+cursor+"|"+items;if(signature.equals(shown))return;boolean first=shown==null;shown=signature;rows.removeAllViews();
            if(items.isEmpty()){rows.addView(query.isEmpty()?ui.empty("history","No tasks yet","Laptop requests and their answers will appear here.","Refresh",this::reload):ui.empty("search","No matching tasks","Try another word from the request or answer.","Clear search",()->search.setText("")));return;}
            for(JSONObject item:items)rows.addView(card(item));
            if(first)AppUi.stagger(rows);
        }
        View card(JSONObject item){
            String id=item.optString("id"),kind=item.optString("kind","agent"),raw=item.optString("state"),request=item.optString("request"),summary=item.optString("summary");long at=timestamp(item.opt("updated"));
            LinearLayout row=ui.card();row.setTag("task_row:"+id);row.setClickable(true);row.setForeground(ui.pressable(null,24));row.setOnClickListener(v->detail(a,kind,id));
            LinearLayout top=ui.row();top.addView(stateChip(raw));top.addView(new View(a),new LinearLayout.LayoutParams(0,1,1));if(at>0)top.addView(ui.small(TaskViews.when(at)));row.addView(top);ui.space(row,12);
            TextView title=ui.heading(request.isEmpty()?"Task":request);title.setMaxLines(3);title.setEllipsize(TextUtils.TruncateAt.END);row.addView(title);
            if(!summary.isEmpty()){ui.space(row,6);TextView answer=ui.detail(summary);answer.setMaxLines(3);answer.setEllipsize(TextUtils.TruncateAt.END);row.addView(answer);}
            ui.space(row,14);Button open=ui.quietButton("Open task",()->detail(a,kind,id));open.setTag("task_open:"+id);row.addView(open,new LinearLayout.LayoutParams(-1,-2));return row;
        }
    }

    private static final class Detail extends Screen {
        final String kind,id;final boolean agent;final LinearLayout meta,messages,pendingMessages,composer;final AppUi.StatusChip chip;final TextView provenance,saved;final EditText instruction;final TaskViews.SendFab send;final Set<String> queued=new HashSet<>();
        String rendered;boolean busy,loaded,canContinue=true,waiting,primed,follow,jump,placeholder;int total=-1;long lastDay;
        Detail(Activity a,String kind,String id){
            super(a,"Task details");this.kind=kind;this.id=id;agent=kind.equals("agent");
            bar.addView(ui.iconButton("history","All tasks",()->{dialog.dismiss();history(a);}),bar.indexOfChild(refresh),new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));
            chip=ui.statusChip(state(""),"info");chip.setTag("task_state");provenance=ui.small("");provenance.setSingleLine(true);provenance.setEllipsize(TextUtils.TruncateAt.END);
            meta=ui.row();meta.setPadding(ui.dp(20),0,ui.dp(20),ui.dp(10));meta.addView(chip);LinearLayout.LayoutParams pp=new LinearLayout.LayoutParams(0,-2,1);pp.leftMargin=ui.dp(10);meta.addView(provenance,pp);meta.setVisibility(View.GONE);root.addView(meta,1);
            messages=ui.column();messages.setTag("task_messages");body.addView(messages);pendingMessages=ui.column();pendingMessages.setTag("task_pending_messages");body.addView(pendingMessages);
            composer=ui.column();composer.setTag("task_followup_card");composer.setBackground(ui.sheetFace());ui.lift(composer,28,10,true);
            composer.addView(ui.type("Continue this task",13,18,700,0,ui.text));ui.space(composer,8);
            instruction=ui.field("Add your instruction",Cloud.prefs(a).getString("task_draft:"+id,""),true);instruction.setSingleLine(false);instruction.setMaxLines(5);instruction.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_MULTI_LINE|InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);instruction.setImeOptions(EditorInfo.IME_FLAG_NO_EXTRACT_UI);instruction.setTag("task_followup_input");
            send=new TaskViews.SendFab(ui,"Send follow-up",this::submit);send.setTag("task_followup_send");
            LinearLayout compose=ui.row();compose.setGravity(Gravity.BOTTOM);compose.addView(instruction,new LinearLayout.LayoutParams(0,-2,1));LinearLayout.LayoutParams fp=new LinearLayout.LayoutParams(ui.dp(52),ui.dp(52));fp.leftMargin=ui.dp(10);compose.addView(send,fp);composer.addView(compose);
            saved=ui.type("",12.5f,18,500,0,ui.muted);saved.setTag("task_followup_status");saved.setVisibility(View.GONE);saved.setPadding(ui.dp(8),ui.dp(8),ui.dp(8),0);composer.addView(saved);
            composer.setVisibility(agent?View.VISIBLE:View.GONE);root.addView(composer,new LinearLayout.LayoutParams(-1,-2));insets();refreshSend();
            instruction.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int start,int count,int after){}public void onTextChanged(CharSequence s,int start,int before,int count){Cloud.prefs(a).edit().putString("task_draft:"+id,s.toString()).apply();refreshSend();}public void afterTextChanged(Editable e){}});
            body.addOnLayoutChangeListener((v,l,t,r,b,ol,ot,or,ob)->{if(follow){boolean snap=jump;jump=false;end(snap);}});
            scroll.addOnLayoutChangeListener((v,l,t,r,b,ol,ot,or,ob)->{int was=ob-ot;if(was>0&&b-t<was&&body.getHeight()-scroll.getScrollY()-was<=ui.dp(40))scroll.post(()->end(true));});
        }
        @Override void insets(){body.setPadding(ui.dp(20),ui.dp(4),ui.dp(20),agent?ui.dp(16):ui.dp(24)+inset);composer.setPadding(ui.dp(16),ui.dp(14),ui.dp(16),ui.dp(14)+inset);}
        void refreshSend(){send.setEnabled(canContinue&&!instruction.getText().toString().trim().isEmpty());}
        void end(boolean snap){follow=false;int to=Math.max(0,body.getHeight()-(scroll.getHeight()-scroll.getPaddingTop()-scroll.getPaddingBottom()));if(snap||!AppUi.motion())scroll.scrollTo(0,to);else scroll.smoothScrollTo(0,to);}
        void settle(){int now=messages.getChildCount()+pendingMessages.getChildCount();if(now>total){follow=true;jump=total<0;}total=now;}
        @Override void changed(){pending();if(busy)return;busy=true;network.execute(()->{try{JSONObject value=NativeTasks.detail(a,kind,id);safe(()->{busy=false;note("",null,false);render(value);pending();});}catch(Exception error){safe(()->{busy=false;pending();});}});}
        @Override void reload(){load();}
        @Override void load(){
            JSONObject cached=NativeTasks.cachedDetail(a,kind,id);if(cached.length()>0)render(cached);pending();if(busy)return;busy=true;spin();note("Loading task...","refresh",false);
            network.execute(()->{try{NativeTasks.flush(a);JSONObject value=NativeTasks.detail(a,kind,id);safe(()->{busy=false;note("",null,false);render(value);pending();});}catch(Exception error){safe(()->{busy=false;note("Offline · showing the saved task. Follow-ups stay on this phone until connected.","cloud-off",true);if(!loaded&&messages.getChildCount()==0){placeholder=true;messages.addView(ui.empty("cloud-off","Task not saved on this phone","Reconnect, then refresh to load its answers.","Refresh",this::load));}pending();});}});
        }
        void submit(){
            String text=instruction.getText().toString().trim();if(text.isEmpty())return;
            try{NativeTasks.enqueueFollowup(a,id,text);instruction.setText("");Cloud.prefs(a).edit().remove("task_draft:"+id).apply();waiting=true;line(saved,"");pending();network.execute(()->{try{NativeTasks.flush(a);safe(this::load);}catch(Exception error){safe(this::pending);}});}
            catch(Exception error){line(saved,"Could not save the instruction. Your text is still here.");}
        }
        void pending(){
            try{
                JSONArray queue=NativeTasks.pending(a);int count=0;long day=lastDay;pendingMessages.removeAllViews();
                for(int n=0;n<queue.length();n++){
                    JSONObject entry=queue.getJSONObject(n);if(!id.equals(entry.optString("task_id")))continue;count++;long at=timestamp(entry.opt("created"));boolean review="needs_review".equals(entry.optString("state"));
                    if(at>0&&TaskViews.day(at)!=day){day=TaskViews.day(at);pendingMessages.addView(TaskViews.separator(ui,at));}
                    AppUi.StatusChip badge=ui.statusChip(review?"Needs review · kept on this phone":"Saved on this phone · sending when connected",review?"danger":"warning");if(!review)badge.setCompoundDrawablesWithIntrinsicBounds(ui.glyph("phone-saved",ui.warning,14),null,null,null);badge.setSingleLine(false);badge.setMaxLines(2);
                    View item=TaskViews.bubble(ui,entry.optString("instruction"),true,"You",at,badge);if(item==null)continue;pendingMessages.addView(item);if(queued.add(entry.optString("id"))&&primed)AppUi.enter(item,0);
                }
                primed=true;
                if(count>0){waiting=true;line(saved,"");}else if(waiting){waiting=false;line(saved,"Follow-up received by the server.");main.postDelayed(()->{if(saved.getText().toString().equals("Follow-up received by the server."))line(saved,"");},5000);}
                settle();
            }catch(Exception ignored){}
        }
        void render(JSONObject value){
            loaded=true;String raw=value.optString("conversation_state",value.optString("state"));AppUi.update(chip,state(raw));restyle(chip,raw);
            long created=timestamp(value.opt("created"));AppUi.update(provenance,created>0?"Requested "+TaskViews.when(created):"");meta.setVisibility(View.VISIBLE);
            String signature=value.toString();
            if(!signature.equals(rendered)||placeholder){
                int before=placeholder?0:messages.getChildCount();rendered=signature;placeholder=false;messages.removeAllViews();lastDay=0;
                exchange(value.optString("original_request",value.optString("request","")),created,value.optString("original_summary",value.optString("summary","")),value.optString("original_state",value.optString("state")),timestamp(value.opt("original_updated")));
                JSONArray turns=value.optJSONArray("turns");for(int n=0;turns!=null&&n<turns.length();n++){JSONObject turn=turns.optJSONObject(n);if(turn!=null)exchange(turn.optString("instruction"),timestamp(turn.opt("created")),turn.optString("summary"),turn.optString("state"),timestamp(turn.opt("updated")));}
                for(int n=before;before>0&&n<messages.getChildCount();n++)AppUi.enter(messages.getChildAt(n),(n-before)*60);
            }
            canContinue=agent&&value.optBoolean("can_followup",true);if(instruction.isEnabled()!=canContinue){instruction.setEnabled(canContinue);instruction.setAlpha(canContinue?1f:.55f);}refreshSend();
            if(agent&&!canContinue)line(saved,"This task cannot be continued.");else if(saved.getText().toString().equals("This task cannot be continued."))line(saved,"");
            settle();
        }
        void exchange(String request,long asked,String answer,String raw,long answered){
            message(request,true,"You",asked,null);
            if(!answer.isEmpty())message(answer,false,"Assistant",answered,raw.equals("completed")||raw.equals("complete")?null:stateChip(raw));
            else{LinearLayout row=ui.row();row.setPadding(ui.dp(4),0,0,ui.dp(14));row.addView(stateChip(raw));messages.addView(row);}
        }
        void message(String text,boolean user,String label,long at,View badge){
            if(text==null||text.isEmpty())return;
            if(at>0&&TaskViews.day(at)!=lastDay){lastDay=TaskViews.day(at);messages.addView(TaskViews.separator(ui,at));}
            messages.addView(TaskViews.bubble(ui,text,user,label,at,badge));
        }
    }
}
