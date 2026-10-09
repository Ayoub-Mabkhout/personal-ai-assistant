package com.personalassistant.companion;

import android.app.AlertDialog;
import android.text.TextUtils;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.io.File;
import java.util.*;

/** Activity tab: task-history hero, saved-voice banner and the dated receipt timeline. */
final class MainReceipts {
    private final MainActivity a;private final AppUi ui;private final LinearLayout rows,retryBox;private final TextView historyStatus,pendingText;final AppUi.Pill retry;private String key="";

    MainReceipts(MainActivity a,AppUi ui,LinearLayout page){
        this.a=a;this.ui=ui;
        page.addView(ui.header("Activity","Recent requests and answers."));ui.space(page,18);page.addView(hero(),MainParts.params(ui,-1,-2,0,0,0,16));
        retryBox=ui.column();retryBox.setPadding(ui.dp(14),ui.dp(12),ui.dp(10),ui.dp(6));retryBox.setBackground(ui.outline(ui.warningSoft,20,AppUi.alpha(ui.warning,.28f),1));
        LinearLayout top=ui.row();top.addView(MainParts.icon(ui,"phone-saved",ui.warning),new LinearLayout.LayoutParams(ui.dp(22),ui.dp(22)));pendingText=ui.type("",15,20,700,0,ui.warning);top.addView(pendingText,MainParts.weighted(ui,1,12,0,0,0));retryBox.addView(top);
        retry=ui.chip("Send saved voice commands","refresh",()->{VoiceOutbox.retry(a,null);Toast.makeText(a,"Checking saved commands",Toast.LENGTH_SHORT).show();});retry.setTag("retry_voice");retryBox.addView(retry,MainParts.params(ui,-2,-2,28,4,0,0));
        retryBox.setVisibility(View.GONE);page.addView(retryBox,MainParts.params(ui,-1,-2,0,0,0,12));
        historyStatus=ui.type("",12,16,400,0,ui.warning);historyStatus.setVisibility(View.GONE);page.addView(historyStatus,MainParts.params(ui,-1,-2,4,0,4,8));
        ui.label(page,"Voice receipts");rows=ui.column();page.addView(rows);
    }

    private View hero(){
        LinearLayout box=ui.row();box.setPadding(ui.dp(16),ui.dp(16),ui.dp(14),ui.dp(16));box.setBackground(ui.pressable(new MainParts.HeroFace(ui,28),28));ui.lift(box,28,3,false);
        box.setTag("activity_history");box.setClickable(true);box.setFocusable(true);box.setContentDescription("All task history");box.setOnClickListener(v->a.taskHistory());AppUi.press(box);
        FrameLayout tile=new FrameLayout(a);tile.setBackground(ui.outline(ui.accentSoft,18,AppUi.alpha(ui.accent,.22f),1));tile.addView(MainParts.icon(ui,"history",ui.accent),new FrameLayout.LayoutParams(ui.dp(28),ui.dp(28),Gravity.CENTER));box.addView(tile,new LinearLayout.LayoutParams(ui.dp(52),ui.dp(52)));
        LinearLayout words=ui.column();words.addView(ui.type("All task history",18,24,700,-.011f,ui.text));words.addView(ui.type("Full answers and follow-ups, here in Companion.",13.5f,18,400,0,ui.muted),MainParts.params(ui,-2,-2,0,2,0,0));box.addView(words,MainParts.weighted(ui,1,14,0,10,0));
        FrameLayout go=new FrameLayout(a);go.setBackground(ui.outline(ui.surface,19,ui.stroke,1));go.addView(MainParts.icon(ui,"arrow",ui.accent),new FrameLayout.LayoutParams(ui.dp(20),ui.dp(20),Gravity.CENTER));box.addView(go,new LinearLayout.LayoutParams(ui.dp(38),ui.dp(38)));
        return box;
    }

    void render(){
        int pending=VoiceOutbox.pending(a);String error=Cloud.prefs(a).getString("voice_history_error","");
        retryBox.setVisibility(pending>0?View.VISIBLE:View.GONE);if(pending>0)AppUi.update(pendingText,pending+" voice command"+(pending==1?"":"s")+" waiting to send");
        historyStatus.setVisibility(error.isEmpty()?View.GONE:View.VISIBLE);if(!error.isEmpty())AppUi.update(historyStatus,"Recent history could not be saved on this phone.");
        File directory=new File(a.getFilesDir(),"voice-receipts");String next=pending+":"+directory.lastModified()+error+AppUi.number(a,"voice_chat_updated_at");if(next.equals(key))return;key=next;
        rows.removeAllViews();File[] files=directory.listFiles((d,name)->name.endsWith(".json"));
        if(files==null||files.length==0){rows.addView(ui.empty("activity","Nothing here yet","Your acknowledged voice requests will appear here."));return;}
        Arrays.sort(files,(x,y)->Long.compare(y.lastModified(),x.lastModified()));int shown=Math.min(files.length,12);
        for(int i=0;i<shown;i++)try{rows.addView(receipt(files[i],i==0,i==shown-1));}catch(Exception ignored){}
    }

    private static String[] status(String state){
        switch(state){
            case "completed":case "complete":case "answer":return new String[]{"Completed","success"};
            case "ended":case "conversation_started":return new String[]{"Done","success"};
            case "queued":case "pending":case "received":return new String[]{"Queued","info"};
            case "running":case "leased":case "in_progress":return new String[]{"In progress","info"};
            case "needs_input":return new String[]{"Needs your input","warning"};
            case "failed":case "error":return new String[]{"Failed","danger"};
            case "cancelled":return new String[]{"Cancelled","neutral"};
            case "transcribed":return new String[]{"Transcribed","neutral"};
            case "no_speech":case "no_command":return new String[]{"No command","neutral"};
            default:return new String[]{state.isEmpty()?"Received":state.replace('_',' '),"neutral"};
        }
    }

    private View receipt(File file,boolean first,boolean last)throws Exception{
        JSONObject receipt=new JSONObject(VoiceOutbox.read(file));String text=receipt.optString("text","Voice request"),state=receipt.optString("status"),reply=receipt.optString("reply",state.isEmpty()?"Acknowledged":state),task=receipt.optString("task_id");
        String[] chip=status(state);int[] tone=ui.toneColors(chip[1]);
        LinearLayout row=ui.row();row.setGravity(Gravity.TOP);row.addView(new MainParts.Rail(ui,tone[0],first,last),new LinearLayout.LayoutParams(ui.dp(26),-1));
        LinearLayout card=ui.card();card.setPadding(ui.dp(16),ui.dp(12),ui.dp(12),ui.dp(task.isEmpty()?14:4));
        LinearLayout top=ui.row();top.addView(ui.type(AppUi.stamp(file.lastModified()),12,16,500,0,ui.muted),MainParts.weighted(ui,1,0,0,8,0));top.addView(ui.statusChip(chip[0],chip[1]));card.addView(top);
        TextView request=ui.type(text,15,20,700,-.003f,ui.text);request.setMaxLines(3);request.setEllipsize(TextUtils.TruncateAt.END);card.addView(request,MainParts.params(ui,-2,-2,0,8,4,0));
        LinearLayout lower=ui.row();TextView answer=ui.type(reply,13,18,400,0,ui.muted);answer.setMaxLines(3);answer.setEllipsize(TextUtils.TruncateAt.END);lower.addView(answer,MainParts.weighted(ui,1,0,2,4,2));
        if(!task.isEmpty()){Button open=ui.linkButton("Open task",10,()->a.openTask(task));open.setTag("receipt_task:"+task);lower.addView(open);}
        card.addView(lower,MainParts.params(ui,-1,-2,0,1,0,0));
        card.setClickable(true);card.setFocusable(true);
        card.setOnClickListener(v->{if(!task.isEmpty()&&(state.equals("queued")||state.equals("running")))a.openTask(task);else new AlertDialog.Builder(a).setTitle("Voice request").setMessage(text+"\n\n"+reply).setPositiveButton("Close",null).show();});
        row.addView(card,MainParts.weighted(ui,1,0,0,0,10));return row;
    }
}
