package com.personalassistant.companion;

import android.graphics.Color;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.util.*;

/** Chronological, timestamped user and assistant bubbles shared with locked entry. Updates diff by entry id, so a streaming revision edits its bubble in place. */
final class ChatTimeline {
    interface TaskOpener {void open(String id);}
    private static final int WINDOW=40;
    private final AppUi ui;final LinearLayout rows;private final HashMap<String,Bubble> shown=new HashMap<>();private View empty;private long revision=Long.MIN_VALUE;private boolean settled;
    ChatTimeline(AppUi ui){this.ui=ui;rows=ui.column();rows.setTag("voice_chat");VoiceChat.importReceipts(ui.context);}
    void render(TaskOpener task){
        long version=AppUi.number(ui.context,"voice_chat_updated_at");if(version==revision)return;revision=version;
        JSONArray entries=VoiceChat.history(ui.context);ArrayList<Bubble> order=new ArrayList<>(),fresh=new ArrayList<>();HashSet<String> live=new HashSet<>();
        for(int n=Math.max(0,entries.length()-WINDOW);n<entries.length();n++){
            JSONObject entry=entries.optJSONObject(n);if(entry==null||entry.optString("text").isEmpty())continue;
            boolean user=entry.optString("role").equals("user");String key=entry.optString("id","#"+n)+(user?"|user":"|assistant");Bubble bubble=shown.get(key);
            if(bubble==null){bubble=new Bubble(ui,user);shown.put(key,bubble);fresh.add(bubble);}
            bubble.set(entry.optString("text"),entry.optLong("time"),entry.optString("kind"),entry.optString("task_id"),task);live.add(key);order.add(bubble);
        }
        for(Iterator<Map.Entry<String,Bubble>> it=shown.entrySet().iterator();it.hasNext();){Map.Entry<String,Bubble> held=it.next();if(!live.contains(held.getKey())){rows.removeView(held.getValue().outer);it.remove();}}
        if(order.isEmpty()){if(empty==null){empty=ui.empty("chat","No messages yet","Your requests and answers will appear here.");empty.setPadding(ui.dp(24),ui.dp(4),ui.dp(24),ui.dp(12));rows.addView(empty);}}
        else if(empty!=null){rows.removeView(empty);empty=null;}
        for(int at=0;at<order.size();at++){View view=order.get(at).outer;if(rows.getChildAt(at)!=view){rows.removeView(view);rows.addView(view,at);}}
        if(settled)for(int i=0;i<fresh.size();i++)AppUi.enter(fresh.get(i).outer,Math.min(i,3)*60);
        settled=true;
    }
    static void bubble(LinearLayout parent,AppUi ui,String text,boolean user,long time,String kind,String taskId,TaskOpener open){
        if(text==null||text.isEmpty())return;Bubble bubble=new Bubble(ui,user);bubble.set(text,time,kind==null?"":kind,taskId==null?"":taskId,open);parent.addView(bubble.outer);
    }

    private static final class Bubble {
        final AppUi ui;final boolean user;final LinearLayout outer,column,extras;final TextView words,meta;AppUi.StatusChip state;Button link;String text="",kind="",task="";TaskOpener open;
        Bubble(AppUi ui,boolean user){
            this.ui=ui;this.user=user;
            outer=ui.row();outer.setGravity((user?Gravity.END:Gravity.START)|Gravity.TOP);LinearLayout.LayoutParams op=new LinearLayout.LayoutParams(-1,-2);op.bottomMargin=ui.dp(14);outer.setLayoutParams(op);
            column=ui.column();column.setGravity(user?Gravity.END:Gravity.START);
            LinearLayout face=ui.column();face.setBackground(ui.bubble(user));face.setPadding(ui.dp(14),ui.dp(10),ui.dp(14),ui.dp(11));
            words=ui.body("");words.setTextIsSelectable(true);face.addView(words);column.addView(face,new LinearLayout.LayoutParams(-2,-2));
            meta=ui.small("");meta.setPadding(ui.dp(6),ui.dp(3),ui.dp(6),0);column.addView(meta,new LinearLayout.LayoutParams(-2,-2));
            extras=ui.row();extras.setPadding(ui.dp(3),0,0,0);
            LinearLayout.LayoutParams cp=new LinearLayout.LayoutParams(-2,-2);
            if(user){cp.leftMargin=ui.dp(44);outer.addView(column,cp);}
            else{
                LinearLayout.LayoutParams ap=new LinearLayout.LayoutParams(ui.dp(28),ui.dp(28));ap.topMargin=ui.dp(4);outer.addView(ui.avatar(),ap);cp.leftMargin=ui.dp(8);cp.rightMargin=ui.dp(20);outer.addView(column,cp);
            }
        }
        void set(String text,long time,String kind,String task,TaskOpener open){
            if(!text.equals(this.text)){this.text=text;words.setText(text);}
            String who=user?"You":"Assistant",stamp=AppUi.stamp(time),line=stamp.isEmpty()?who:who+" · "+stamp;if(!line.contentEquals(meta.getText()))meta.setText(line);
            this.kind=kind;this.task=task;this.open=open;sync();
        }
        private void sync(){
            String label=kind.equals("acknowledgement")?"Queued":kind.equals("status")?"Status":null;
            if(label==null){if(state!=null){extras.removeView(state);state=null;}}
            else if(state==null){state=ui.statusChip(label,AppUi.toneOf(label));LinearLayout.LayoutParams sp=new LinearLayout.LayoutParams(-2,-2);sp.rightMargin=ui.dp(8);extras.addView(state,0,sp);}
            else if(!state.getText().toString().equals(label)){AppUi.update(state,label);state.tone(AppUi.toneOf(label));}
            boolean linked=!task.isEmpty()&&open!=null&&(kind.equals("acknowledgement")||kind.equals("task_answer"));
            if(!linked){if(link!=null){extras.removeView(link);link=null;}}
            else{if(link==null){link=linkChip();extras.addView(link,new LinearLayout.LayoutParams(-2,-2));}link.setTag("chat_task:"+task);}
            if(extras.getChildCount()==0)column.removeView(extras);else if(extras.getParent()==null)column.addView(extras,new LinearLayout.LayoutParams(-2,-2));
        }
        private Button linkChip(){
            Button chip=ui.linkButton("View task",14,()->{if(open!=null&&!task.isEmpty())open.open(task);});
            chip.setTextColor(ui.text);chip.setTextSize(13.5f);chip.setTypeface(AppUi.face(500));
            chip.setBackground(ui.chipFace(Color.TRANSPARENT,ui.strokeStrong,1.25f,.16f,18,0));chip.setPadding(ui.dp(14),0,ui.dp(10),0);chip.setCompoundDrawablePadding(ui.dp(4));
            return chip;
        }
    }
}
