package com.personalassistant.companion;

import android.widget.*;
import org.json.JSONArray;

/** Shared specialist composer, dictation controls and chat bubbles. */
final class SpecialistChat {
    final MainActivity activity;
    final AppUi ui;
    final LinearLayout view,files;
    final EditText input;
    final Button send;
    final ImageButton mic,attach;
    final String draft,voice;
    private String fileSignature;
    private boolean enabled=true;

    SpecialistChat(MainActivity activity,AppUi ui,String hint,String text,String draft,String voice,
                   boolean attachments,int limit,Runnable submit){
        this.activity=activity;this.ui=ui;this.draft=draft;this.voice=voice;
        view=ui.column();
        view.setPadding(ui.dp(16),ui.dp(8),ui.dp(16),ui.dp(18));
        files=ui.column();
        view.addView(files);
        input=ui.field(hint,text,true);
        input.setMinLines(2);
        input.setMaxLines(5);
        input.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(limit)});
        view.addView(input);
        LinearLayout actions=ui.row();
        mic=ui.iconButton("voice","Dictate message",this::dictate);
        actions.addView(mic,new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));
        attach=ui.iconButton("attach","Add attachment",()->TaskAttachments.choose(activity,draft));
        if(attachments)actions.addView(attach,new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));
        send=ui.primaryButton("Send",submit);
        actions.addView(send,MainParts.weighted(ui,1,10,0,0,0));
        view.addView(actions,MainParts.params(ui,-1,-2,0,10,0,0));
        if(attachments)refreshFiles();
    }

    void refreshFiles(){
        String current=TaskAttachments.draft(activity,draft).toString();
        if(current.equals(fileSignature))return;
        fileSignature=current;
        TaskAttachments.renderDraft(activity,ui,files,draft,this::refreshFiles);
    }

    void enabled(boolean value){
        enabled=value;
        input.setEnabled(value);
        attach.setEnabled(value);
        mic.setEnabled(value);
    }

    void dictate(){
        if(!enabled)return;
        if(dictating()){finishDictation();return;}
        if(!TaskVoice.busy(activity,voice))activity.taskVoice("dictate:"+voice);
    }

    boolean dictating(){return "dictate".equals(TaskVoice.mode(activity,voice));}

    void finishDictation(){
        if(!dictating())return;
        android.content.Intent finish=TaskVoice.finish(activity,voice);
        if(finish!=null)activity.startService(finish);
    }

    void captureDictation(){
        String words=enabled?TaskVoice.take(activity,voice):"";
        if(!words.isEmpty())input.append((input.length()==0?"":" ")+words);
        mic.setContentDescription(dictating()?"Finish dictation":"Dictate message");
    }

    void clearFiles(){
        Cloud.prefs(activity).edit().remove("attachment_draft:"+draft).apply();
        refreshFiles();
    }

    static LinearLayout bubble(MainActivity activity,AppUi ui,LinearLayout rows,String who,String text,
                               double time,boolean mine,JSONArray attachments){
        LinearLayout card=ui.card();
        card.setBackground(ui.outline(mine?ui.accentSoft:ui.surface,22,0,0));
        card.addView(ui.small(who+(time>0?" · "+AppUi.stamp((long)(time*1000)):"")));
        TextView words=ui.detail(mine?text:"");
        words.setTextColor(ui.text);
        words.setTextIsSelectable(true);
        if(!mine)RichText.show(ui,words,text);
        card.addView(words,MainParts.params(ui,-1,-2,0,6,0,0));
        if(attachments!=null&&attachments.length()>0){
            LinearLayout files=ui.column();
            TaskAttachments.show(activity,ui,files,attachments);
            card.addView(files);
        }
        rows.addView(card,MainParts.params(ui,-1,-2,mine?24:0,0,mine?0:24,12));
        return card;
    }
}
