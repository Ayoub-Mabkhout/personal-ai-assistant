package com.personalassistant.companion;

import android.view.*;
import android.widget.*;
import org.json.*;
import java.text.DateFormat;
import java.util.*;

/** Chronological, timestamped user and assistant bubbles shared with locked entry. */
final class ChatTimeline {
    interface TaskOpener {void open(String id);}
    private final AppUi ui;final LinearLayout rows;private long revision=Long.MIN_VALUE;private boolean rendered;private final Set<String> visible=new HashSet<>();
    ChatTimeline(AppUi ui){this.ui=ui;rows=ui.column();rows.setTag("voice_chat");VoiceChat.importReceipts(ui.activity);}
    void render(TaskOpener task){long version=AppUi.number(ui.activity,"voice_chat_updated_at");if(version==revision)return;revision=version;JSONArray entries=VoiceChat.history(ui.activity);rows.removeAllViews();Set<String> current=new HashSet<>();if(entries.length()==0){LinearLayout empty=ui.column();empty.setPadding(0,ui.dp(12),0,ui.dp(12));empty.addView(ui.detail("Your requests and answers will appear here."));rows.addView(empty);}for(int n=Math.max(0,entries.length()-40);n<entries.length();n++){JSONObject entry=entries.optJSONObject(n);if(entry==null)continue;String key=entry.optString("role")+":"+entry.optString("id");int before=rows.getChildCount();bubble(rows,ui,entry.optString("text"),entry.optString("role").equals("user"),entry.optLong("time"),entry.optString("kind"),entry.optString("task_id"),task);current.add(key);if(rows.getChildCount()>before){View view=rows.getChildAt(before);view.setTag("chat_entry:"+key);if(rendered&&!visible.contains(key))AppUi.enter(view,0);}}visible.clear();visible.addAll(current);rendered=true;}
    static void bubble(LinearLayout parent,AppUi ui,String text,boolean user,long time,String kind,String taskId,TaskOpener open){
        if(text==null||text.isEmpty())return;LinearLayout outer=ui.column();outer.setGravity(user?Gravity.END:Gravity.START);LinearLayout.LayoutParams op=new LinearLayout.LayoutParams(-1,-2);op.bottomMargin=ui.dp(16);outer.setLayoutParams(op);
        LinearLayout bubble=ui.column();bubble.setPadding(ui.dp(16),ui.dp(12),ui.dp(16),ui.dp(12));bubble.setBackground(ui.bubble(user));TextView words=ui.body(text);words.setTextIsSelectable(true);bubble.addView(words);outer.addView(bubble,inset(ui,user));ui.space(outer,8);
        String stamp=time>0?new java.text.SimpleDateFormat("MMM d, HH:mm",Locale.getDefault()).format(new Date(time)):"";LinearLayout metadata=ui.row();metadata.setGravity(user?Gravity.END:Gravity.START|Gravity.CENTER_VERTICAL);
        if(user)metadata.addView(ui.small("You"+(stamp.isEmpty()?"":"  ·  "+stamp)));else{String label=kind.equals("acknowledgement")?"Queued":kind.equals("task_answer")?"Result":kind.equals("status")?"Status":"Assistant";String tone=kind.equals("acknowledgement")?"info":kind.equals("task_answer")?"accent":"neutral";AppUi.StatusChip state=ui.statusChip(label,tone);state.setTag("chat_state");metadata.addView(state);if(!stamp.isEmpty()){TextView at=ui.small(stamp);LinearLayout.LayoutParams date=new LinearLayout.LayoutParams(0,-2,1);date.leftMargin=ui.dp(8);metadata.addView(at,date);}}outer.addView(metadata,inset(ui,user));
        if(!taskId.isEmpty()&&open!=null&&(kind.equals("acknowledgement")||kind.equals("task_answer"))){ui.space(outer,4);Button details=ui.chip("View task","history",()->open.open(taskId));details.setTag("chat_task:"+taskId);outer.addView(details,new LinearLayout.LayoutParams(-2,ui.dp(48)));}parent.addView(outer);
    }
    private static LinearLayout.LayoutParams inset(AppUi ui,boolean user){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);if(user)p.leftMargin=ui.dp(28);else p.rightMargin=ui.dp(28);return p;}
}
