package com.personalassistant.companion;

import android.view.*;
import android.widget.*;
import org.json.*;
import java.text.DateFormat;
import java.util.*;

/** Chronological, timestamped user and assistant bubbles shared with locked entry. */
final class ChatTimeline {
    interface TaskOpener {void open(String id);}
    private final AppUi ui;final LinearLayout rows;private long revision=Long.MIN_VALUE;
    ChatTimeline(AppUi ui){this.ui=ui;rows=ui.column();rows.setTag("voice_chat");VoiceChat.importReceipts(ui.activity);}
    void render(TaskOpener task){long version=AppUi.number(ui.activity,"voice_chat_updated_at");if(version==revision)return;revision=version;JSONArray entries=VoiceChat.history(ui.activity);rows.removeAllViews();if(entries.length()==0){LinearLayout empty=ui.column();empty.setPadding(0,ui.dp(12),0,ui.dp(12));empty.addView(ui.detail("Your requests and answers will appear here."));rows.addView(empty);return;}for(int n=Math.max(0,entries.length()-40);n<entries.length();n++){JSONObject entry=entries.optJSONObject(n);if(entry!=null)bubble(rows,ui,entry.optString("text"),entry.optString("role").equals("user"),entry.optLong("time"),entry.optString("kind"),entry.optString("task_id"),task);}}
    static void bubble(LinearLayout parent,AppUi ui,String text,boolean user,long time,String kind,String taskId,TaskOpener open){if(text==null||text.isEmpty())return;LinearLayout outer=ui.column();outer.setGravity(user?Gravity.END:Gravity.START);LinearLayout.LayoutParams op=new LinearLayout.LayoutParams(-1,-2);op.bottomMargin=ui.dp(13);outer.setLayoutParams(op);LinearLayout bubble=ui.column();bubble.setPadding(ui.dp(14),ui.dp(12),ui.dp(14),ui.dp(11));bubble.setBackground(ui.shape(user?AppUi.mix(ui.soft,ui.cool,.14f):ui.surface,16,user?0:ui.stroke));LinearLayout.LayoutParams bp=new LinearLayout.LayoutParams(-1,-2);if(user)bp.leftMargin=ui.dp(28);else bp.rightMargin=ui.dp(28);TextView words=ui.text(text,15,false);words.setTextIsSelectable(true);bubble.addView(words);ui.space(bubble,7);String label=user?"You":kind.equals("acknowledgement")?"Queued":kind.equals("status")?"Status":"Assistant";String stamp=time>0?new java.text.SimpleDateFormat("MMM d, HH:mm",Locale.getDefault()).format(new Date(time)):"";TextView metadata=ui.detail(label+(stamp.isEmpty()?"":"  ·  "+stamp));metadata.setTextSize(11);metadata.setTextColor(user?ui.accent:ui.warm);bubble.addView(metadata);if(!taskId.isEmpty()&&open!=null){ui.space(bubble,5);Button details=ui.quietButton("View task",()->open.open(taskId));details.setTag("chat_task:"+taskId);bubble.addView(details,new LinearLayout.LayoutParams(-1,ui.dp(40)));}outer.addView(bubble,bp);parent.addView(outer);}
}
