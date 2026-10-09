package com.personalassistant.companion;

import android.content.SharedPreferences;
import android.text.TextUtils;
import android.view.*;
import android.widget.*;
import org.json.*;

/** Voice tab: brand header, orb hero, live words, latest answer, hands-free controls and the conversation. */
final class MainVoice {
    private static final long ANSWER_FRESH_MS=30*60000L;
    private final MainActivity a;private final AppUi ui;
    final AppUi.VoiceButton talk;final AppUi.Meter meter;final AppUi.StatusChip connection;final Switch background;final AppUi.Pill stop,conversation,testWake;final Button resume;final ChatTimeline chat;
    private final TextView status,detail,hint,words,answer,answerMeta,testCount,heard;private final Button answerTask;private final View liveCard,answerCard,testCard;private final LinearLayout actions;
    private long answerRevision=-1,answerTime;private String answerText="",answerKind="",answerId="";boolean changing;

    MainVoice(MainActivity a,AppUi ui,LinearLayout page){
        this.a=a;this.ui=ui;
        LinearLayout top=ui.row();View mark=new View(a);mark.setBackground(ui.aurora(150,true));mark.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);top.addView(mark,new LinearLayout.LayoutParams(ui.dp(22),ui.dp(22)));
        top.addView(ui.type("Companion",17,24,700,-.012f,ui.text),MainParts.weighted(ui,1,10,0,0,0));
        connection=ui.statusChip("Connect phone","neutral");FrameLayout hit=new FrameLayout(a);hit.setPadding(ui.dp(4),0,ui.dp(4),0);hit.setBackground(ui.pressable(null,24));hit.setClickable(true);hit.setFocusable(true);hit.setOnClickListener(v->a.openConnection());hit.addView(connection,new FrameLayout.LayoutParams(-2,-2,Gravity.CENTER_VERTICAL|Gravity.END));top.addView(hit,new LinearLayout.LayoutParams(-2,ui.dp(48)));page.addView(top);

        LinearLayout hero=ui.column();hero.setGravity(Gravity.CENTER_HORIZONTAL);
        talk=ui.voiceButton(a::talkTapped);talk.setTag("talk");hero.addView(talk,MainParts.params(ui,ui.dp(252),ui.dp(252),0,2,0,0));
        status=ui.title("Microphone off");status.setGravity(Gravity.CENTER);status.setTag("voice_status");status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);hero.addView(status,MainParts.params(ui,-1,-2,16,6,16,0));
        detail=ui.detail("Tap Talk to start.");detail.setGravity(Gravity.CENTER);hero.addView(detail,MainParts.params(ui,-1,-2,24,4,24,16));
        meter=new AppUi.Meter(a,ui);meter.setTag("voice_level");hero.addView(meter,MainParts.params(ui,ui.dp(150),ui.dp(26),0,0,0,20));page.addView(hero);

        LinearLayout live=ui.card();liveCard=live;LinearLayout liveHead=ui.row();View dot=new View(a);dot.setBackground(ui.outline(ui.aurora[2],4,0,0));liveHead.addView(dot,new LinearLayout.LayoutParams(ui.dp(8),ui.dp(8)));liveHead.addView(ui.label("Live transcript"),MainParts.params(ui,-2,-2,8,0,0,0));live.addView(liveHead);
        words=ui.type("",17,25,500,-.003f,ui.text);live.addView(words,MainParts.params(ui,-1,-2,0,6,0,0));page.addView(liveCard);

        LinearLayout reply=ui.card();answerCard=reply;LinearLayout answerHead=ui.row();answerHead.addView(MainParts.icon(ui,"sparkle",ui.accent),new LinearLayout.LayoutParams(ui.dp(15),ui.dp(15)));answerHead.addView(ui.label("Latest answer"),MainParts.params(ui,-2,-2,8,0,0,0));reply.addView(answerHead);
        answer=ui.type("",17,25,500,-.003f,ui.text);answer.setMaxLines(8);answer.setEllipsize(TextUtils.TruncateAt.END);reply.addView(answer,MainParts.params(ui,-1,-2,0,6,0,0));
        answerMeta=ui.type("",12,16,400,0,ui.muted);reply.addView(answerMeta,MainParts.params(ui,-1,-2,0,6,0,0));
        answerTask=ui.linkButton("View task",2,()->a.openTask(answerId));answerTask.setTag("answer_task");LinearLayout.LayoutParams link=MainParts.params(ui,-2,-2,0,2,0,-6);reply.addView(answerTask,link);page.addView(answerCard);

        actions=ui.column();stop=ui.stopButton("Stop microphone",a::stopMic);stop.setTag("stop_microphone");actions.addView(stop,MainParts.params(ui,-1,-2,0,0,0,0));
        hint=ui.type("Pause when you finish and I will send it.",13,18,400,0,ui.muted);hint.setGravity(Gravity.CENTER);actions.addView(hint,MainParts.params(ui,-1,-2,16,10,16,0));
        resume=ui.primaryButton("Resume listening",()->a.startVoice(false));resume.setTag("resume_listening");actions.addView(resume,MainParts.params(ui,-1,-2,0,0,0,0));page.addView(actions,MainParts.params(ui,-1,-2,0,0,0,16));

        LinearLayout free=ui.card();LinearLayout freeHead=ui.row();freeHead.addView(MainParts.icon(ui,"waveform",ui.accent),new LinearLayout.LayoutParams(ui.dp(15),ui.dp(15)));freeHead.addView(ui.label("Hands-free"),MainParts.params(ui,-2,-2,8,0,0,0));free.addView(freeHead);ui.space(free,4);
        background=ui.toggle("Background listening","Hey Chat, even while your phone is locked.",free,false,(button,on)->{if(!changing)a.setBackground(on);});background.setTag("background_listening");
        LinearLayout chips=ui.row();conversation=ui.chip("Start conversation","chat",a::toggleConversation);conversation.setTag("conversation_mode");testWake=ui.chip("Test wake","bolt",a::toggleTest);testWake.setTag("test_wake");
        chips.addView(conversation,MainParts.weighted(ui,1.3f,-3,0,0,0));chips.addView(testWake,MainParts.weighted(ui,1,0,0,-3,0));free.addView(chips,MainParts.params(ui,-1,-2,0,6,0,0));
        TextView help=ui.type("Say \u201cStart conversation mode\u201d to keep talking, and \u201cThat was all\u201d to finish.",12.5f,17,400,0,ui.muted);free.addView(help,MainParts.params(ui,-1,-2,2,6,2,0));page.addView(free);

        LinearLayout test=ui.column();test.setPadding(ui.dp(18),ui.dp(16),ui.dp(18),ui.dp(14));test.setBackground(ui.outline(ui.infoSoft,24,AppUi.alpha(ui.info,.3f),1));
        LinearLayout testHead=ui.row();testHead.addView(MainParts.icon(ui,"bolt",ui.info),new LinearLayout.LayoutParams(ui.dp(15),ui.dp(15)));TextView tag=ui.label("Local test");tag.setTextColor(ui.info);testHead.addView(tag,MainParts.params(ui,-2,-2,8,0,0,0));test.addView(testHead);
        test.addView(ui.heading("Say Hey Chat normally"),MainParts.params(ui,-2,-2,0,8,0,0));test.addView(ui.detail("Try your usual volume, then lock the phone. No commands or API calls are sent."),MainParts.params(ui,-2,-2,0,4,0,0));
        testCount=ui.type("Waiting for a wake...",14,20,700,0,ui.text);test.addView(testCount,MainParts.params(ui,-2,-2,0,12,0,0));heard=ui.detail("No words detected yet.");test.addView(heard,MainParts.params(ui,-2,-2,0,2,0,8));
        AppUi.Pill tune=ui.chip("Adjust sensitivity","waveform",a::sensitivity);tune.setTag("test_sensitivity");test.addView(tune,MainParts.params(ui,-2,-2,-3,0,0,0));
        LinearLayout.LayoutParams tp=MainParts.params(ui,-1,-2,0,0,0,16);testCard=test;page.addView(test,tp);

        MainParts.conversationLabel(ui,page);chat=new ChatTimeline(ui);page.addView(chat.rows);
    }

    /** Whether the latest chat entry is a recent assistant answer; cached until the chat file changes. */
    private boolean freshAnswer(){
        long revision=AppUi.number(a,"voice_chat_updated_at");
        if(revision!=answerRevision){answerRevision=revision;answerText="";JSONArray entries=VoiceChat.history(a);JSONObject last=entries.length()>0?entries.optJSONObject(entries.length()-1):null;
            if(last!=null&&"assistant".equals(last.optString("role"))){answerText=last.optString("text");answerTime=last.optLong("time");answerKind=last.optString("kind");answerId=last.optString("task_id");}}
        return !answerText.isEmpty()&&System.currentTimeMillis()-answerTime<ANSWER_FRESH_MS;
    }

    private static void label(TextView view,String value){if(!view.getText().toString().equals(value))view.setText(value);}

    void update(String title,String text,String orb,boolean loading,boolean mic,boolean testing,boolean wake,boolean paired,boolean conversationOn){
        SharedPreferences p=Cloud.prefs(a);boolean live=VoiceStatus.live(orb),engaged=mic||loading;
        talk.state(orb);talk.level(AppUi.level(a),live&&mic);AppUi.update(status,title);AppUi.update(detail,text);
        meter.setVisibility(engaged?View.VISIBLE:View.GONE);meter.value(AppUi.level(a),mic);boolean resuming=wake&&!mic&&!loading;stop.setVisibility(engaged?View.VISIBLE:View.GONE);hint.setVisibility(orb.equals("listening")?View.VISIBLE:View.GONE);resume.setVisibility(resuming?View.VISIBLE:View.GONE);actions.setVisibility(engaged||resuming?View.VISIBLE:View.GONE);
        String partial=p.getString("voice_last_partial",""),spoken=partial.isEmpty()?p.getString("voice_user_text",""):partial;liveCard.setVisibility(live&&!spoken.isEmpty()?View.VISIBLE:View.GONE);if(!spoken.isEmpty())label(words,spoken);
        boolean fresh=freshAnswer();answerCard.setVisibility(fresh&&!live?View.VISIBLE:View.GONE);
        if(fresh){AppUi.update(answer,answerText);AppUi.update(answerMeta,"Assistant \u00b7 "+AppUi.stamp(answerTime));answerTask.setVisibility(!answerId.isEmpty()&&answerKind.equals("acknowledgement")?View.VISIBLE:View.GONE);}
        String link=paired?(VoiceOutbox.networkReady(a)?"Online":"Offline"):"Connect phone";if(!link.equals(connection.getText().toString())){AppUi.update(connection,link);connection.tone(link.equals("Online")?"success":link.equals("Offline")?"warning":"neutral");}
        changing=true;background.setChecked(testing?p.getBoolean("ui_test_background_desired",false):wake);changing=false;
        testCard.setVisibility(testing?View.VISIBLE:View.GONE);label(testWake,testing?"Finish test":"Test wake");label(conversation,conversationOn?"End conversation":"Start conversation");
        long wakes=AppUi.number(a,"voice_wake_count")-AppUi.number(a,"ui_test_wake_baseline");AppUi.update(testCount,wakes>0?"Heard Hey Chat "+wakes+" time"+(wakes==1?"":"s"):"Waiting for a wake...");label(heard,partial.isEmpty()?"No words detected yet.":"Heard: "+partial);
        chat.render(id->a.openTask(id));
    }
}
