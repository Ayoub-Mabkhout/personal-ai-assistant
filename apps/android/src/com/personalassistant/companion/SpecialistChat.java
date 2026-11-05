package com.personalassistant.companion;

import android.view.*;
import android.widget.*;
import java.util.*;

/** Shared specialist composer, dictation controls and the task-chat style timeline used by Coach and Money. */
final class SpecialistChat {
    final MainActivity activity;
    final AppUi ui;
    final LinearLayout view,files;
    final Composer composer;
    final EditText input;
    final ImageButton send,mic,attach;
    final String draft,voice;
    private String fileSignature,shownMode;
    private boolean enabled=true;

    SpecialistChat(MainActivity activity,AppUi ui,String hint,String text,String draft,String voice,
                   boolean attachments,int limit,Runnable submit){
        this.activity=activity;this.ui=ui;this.draft=draft;this.voice=voice;
        view=ui.column();
        view.setTag("specialist_composer");
        view.setPadding(ui.dp(12),ui.dp(6),ui.dp(12),ui.dp(10));
        composer=new Composer(ui,hint,text,limit,attachments?()->{if(this.enabled)TaskAttachments.choose(activity,draft);}:null,
            "Dictate message",this::dictate,"Send message",submit);
        view.addView(composer.view,new LinearLayout.LayoutParams(-1,-2));
        files=composer.files;input=composer.input;send=composer.send;mic=composer.mic;attach=composer.attach;
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
        composer.editable(value);
        composer.sendable(value);
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

    /** Dictated words join the draft at the caret while the field is focused, otherwise at its end. */
    void captureDictation(){
        String words=enabled?TaskVoice.take(activity,voice):"";
        if(!words.isEmpty()){
            android.text.Editable text=input.getText();int length=text.length(),s=input.getSelectionStart(),e=input.getSelectionEnd();
            if(!input.hasFocus()||s<0||e<0)s=e=length;
            int lo=Math.max(0,Math.min(Math.min(s,e),length)),hi=Math.max(lo,Math.min(Math.max(s,e),length));
            TaskTurns.Insertion result=TaskTurns.insert(text.toString(),lo,hi,words);text.replace(lo,hi,result.piece);input.setSelection(Math.min(result.caret,input.length()));
        }
        String mode=dictating()?"dictate":"";
        if(!mode.equals(shownMode)){shownMode=mode;composer.dictating(!mode.isEmpty(),"Dictate message","Finish dictation");}
    }

    void clearFiles(){
        Cloud.prefs(activity).edit().remove("attachment_draft:"+draft).apply();
        refreshFiles();
    }

    /** Puts saved attachment rows back into the draft (Edit on an unsent message). */
    void restoreFiles(String rows){
        if(rows==null||rows.isEmpty()||"[]".equals(rows))return;
        Cloud.prefs(activity).edit().putString("attachment_draft:"+draft,rows).apply();
        refreshFiles();
    }

    /**
     * Keeps the composer above the keyboard and the system bars, like the task conversation. The send button's lift
     * unclips its ancestors for its shadow; the root clips again once attached so the scrolled list cannot paint over the header.
     */
    static void insets(ViewGroup root){
        root.setOnApplyWindowInsetsListener((v,insets)->{int[] bars=TaskViews.bars(insets);v.setPadding(bars[0],bars[1],bars[2],bars[3]);return insets;});
        root.addOnAttachStateChangeListener(new View.OnAttachStateChangeListener(){
            public void onViewAttachedToWindow(View v){root.post(()->{root.setClipChildren(true);root.setClipToPadding(true);});}
            public void onViewDetachedFromWindow(View v){}
        });
    }

    /** Chat bubbles diffed by message ID: the reply slot of a message is one bubble from "Queued" to the final answer. */
    static final class Timeline {
        interface Extras {String signature(SpecialistThread.Row row);void fill(SpecialistThread.Row row,LinearLayout box);}
        interface Action {void run(String id);}
        final MainActivity activity;final AppUi ui;final LinearLayout rows;final ScrollView scroll;final View content;
        private final HashMap<String,Bubble> shown=new HashMap<>();private View empty;private String emptyText;private boolean settled;
        Action retry,edit;Extras extras;

        Timeline(MainActivity activity,AppUi ui,ScrollView scroll,View content){
            this.activity=activity;this.ui=ui;this.scroll=scroll;this.content=content;rows=ui.column();rows.setTag("specialist_messages");
            // The keyboard shrinks the list: stay at the newest message when the reader was already there.
            scroll.addOnLayoutChangeListener((v,l,t,r,b,ol,ot,or,ob)->{int was=ob-ot;if(was>0&&b-t<was&&content.getHeight()-scroll.getScrollY()-was<=ui.dp(80))scroll.post(()->end(true));});
        }

        boolean atEnd(){return scroll.getScrollY()+scroll.getHeight()>=content.getHeight()-ui.dp(80);}
        void end(boolean snap){int to=Math.max(0,content.getHeight()-(scroll.getHeight()-scroll.getPaddingTop()-scroll.getPaddingBottom()));if(snap||!AppUi.motion())scroll.scrollTo(0,to);else scroll.smoothScrollTo(0,to);}

        void render(List<SpecialistThread.Row> list,String emptyMessage){
            boolean tail=!settled||atEnd();HashSet<String> live=new HashSet<>();ArrayList<Bubble> order=new ArrayList<>(),fresh=new ArrayList<>();
            for(SpecialistThread.Row row:list){
                Bubble bubble=shown.get(row.key);
                if(bubble==null){bubble=new Bubble(this,row.user());bubble.outer.setTag("specialist_entry:"+row.key);shown.put(row.key,bubble);fresh.add(bubble);}
                bubble.set(row);live.add(row.key);order.add(bubble);
            }
            for(Iterator<Map.Entry<String,Bubble>> it=shown.entrySet().iterator();it.hasNext();){Map.Entry<String,Bubble> held=it.next();if(!live.contains(held.getKey())){rows.removeView(held.getValue().outer);it.remove();}}
            if(order.isEmpty()&&!emptyMessage.isEmpty()){
                if(empty==null||!emptyMessage.equals(emptyText)){if(empty!=null)rows.removeView(empty);emptyText=emptyMessage;empty=ui.detail(emptyMessage);empty.setPadding(ui.dp(8),ui.dp(8),ui.dp(8),ui.dp(16));rows.addView(empty);}
            }else if(!order.isEmpty()&&empty!=null||emptyMessage.isEmpty()&&empty!=null){rows.removeView(empty);empty=null;emptyText=null;}
            for(int at=0;at<order.size();at++){View v=order.get(at).outer;if(rows.getChildAt(at)!=v){rows.removeView(v);rows.addView(v,at);}}
            if(settled)for(int i=0;i<fresh.size();i++)AppUi.enter(fresh.get(i).outer,Math.min(i,3)*60);
            settled=true;
            if(tail)scroll.post(()->end(true));
        }
    }

    /** A TaskViews-style bubble whose words, label and actions change in place. */
    private static final class Bubble {
        final Timeline timeline;final AppUi ui;final boolean user;final LinearLayout outer,item,box,actions,extras;final TextView words,meta,note;
        String text,kind="",extrasSignature;SpecialistThread.Row row;

        Bubble(Timeline timeline,boolean user){
            this.timeline=timeline;ui=timeline.ui;this.user=user;
            item=ui.column();item.setGravity(user?Gravity.END:Gravity.START);
            box=ui.column();box.setPadding(ui.dp(14),ui.dp(10),ui.dp(14),ui.dp(11));box.setBackground(ui.bubble(user));
            words=ui.body("");words.setMaxWidth(Math.min(Math.round(ui.context.getResources().getDisplayMetrics().widthPixels*.84f),ui.dp(520))-ui.dp(28)-(user?0:ui.dp(36)));box.addView(words);
            box.setLongClickable(true);box.setOnLongClickListener(v->{if(text!=null&&!text.isEmpty())TaskViews.copy(ui.context,text);return true;});
            extras=ui.column();box.addView(extras,new LinearLayout.LayoutParams(-1,-2));
            item.addView(box,new LinearLayout.LayoutParams(-2,-2));
            meta=ui.type("",12,16,500,0,ui.muted);meta.setPadding(ui.dp(6),0,ui.dp(6),0);LinearLayout.LayoutParams mp=new LinearLayout.LayoutParams(-2,-2);mp.topMargin=ui.dp(5);item.addView(meta,mp);
            note=ui.type("",12.5f,18,500,0,ui.warning);note.setPadding(ui.dp(6),ui.dp(2),ui.dp(6),0);note.setVisibility(View.GONE);note.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);item.addView(note,new LinearLayout.LayoutParams(-2,-2));
            actions=ui.row();actions.setVisibility(View.GONE);
            Button retry=ui.ghostButton("Retry",()->{if(row!=null&&timeline.retry!=null)timeline.retry.run(row.id);});retry.setTag("specialist_retry");
            Button edit=ui.ghostButton("Edit",()->{if(row!=null&&timeline.edit!=null)timeline.edit.run(row.id);});edit.setTag("specialist_edit");
            actions.addView(retry);actions.addView(edit);item.addView(actions,new LinearLayout.LayoutParams(-2,-2));
            LinearLayout.LayoutParams op=new LinearLayout.LayoutParams(-1,-2);op.bottomMargin=ui.dp(14);
            if(user){outer=item;outer.setLayoutParams(op);}
            else{
                outer=ui.row();outer.setGravity(Gravity.START|Gravity.TOP);outer.setLayoutParams(op);
                LinearLayout.LayoutParams ap=new LinearLayout.LayoutParams(ui.dp(28),ui.dp(28));ap.topMargin=ui.dp(4);outer.addView(ui.avatar(),ap);
                LinearLayout.LayoutParams cp=new LinearLayout.LayoutParams(-2,-2);cp.leftMargin=ui.dp(8);outer.addView(item,cp);
            }
        }

        void set(SpecialistThread.Row value){
            row=value;boolean status="status".equals(value.kind);
            if(!value.text.equals(text)||!value.kind.equals(kind)){
                text=value.text;kind=value.kind;
                if(user||status){words.setText(text);words.setTextColor(status?ui.muted:ui.text);}
                else{words.setTextColor(ui.text);RichText.show(ui,words,text);}
            }
            String stamp=value.time>0?AppUi.stamp((long)(value.time*1000)):"";
            AppUi.update(meta,stamp.isEmpty()?value.label:value.label+" · "+stamp);
            boolean showNote=!value.note.isEmpty();note.setVisibility(showNote?View.VISIBLE:View.GONE);if(showNote)AppUi.update(note,value.note);
            note.setTextColor(value.retry?ui.warning:ui.muted);
            actions.setVisibility(value.retry?View.VISIBLE:View.GONE);
            Timeline.Extras source=timeline.extras;String signature=source==null?"":source.signature(value);
            if(!signature.equals(extrasSignature)){extrasSignature=signature;extras.removeAllViews();if(source!=null&&!signature.isEmpty())source.fill(value,extras);extras.setVisibility(extras.getChildCount()==0?View.GONE:View.VISIBLE);}
        }
    }
}
