package com.personalassistant.companion;

import android.content.res.ColorStateList;
import android.graphics.drawable.*;
import android.text.InputFilter;
import android.text.InputType;
import android.view.*;
import android.view.inputmethod.EditorInfo;
import android.widget.*;

/**
 * The one message composer shared by every native chat (new task, task follow-ups, Coach, Money): a rounded
 * container holding attachment previews, a frameless multiline field that grows up to six lines and then scrolls,
 * and an action row with Add attachment on the left and Dictate plus a round Send on the right. Icons keep 48dp
 * touch targets; the field never draws its own frame, so it blends into the container focused or not.
 */
final class Composer {
    static final int MAX_LINES=6;
    final AppUi ui;
    final LinearLayout view,files,actions;
    final EditText input;
    final ImageButton attach,mic,send;
    private final Drawable idle,focused;
    private boolean sendable=true;

    /** onAttach null hides the attachment control (and the preview area stays empty). */
    Composer(AppUi ui,String hint,String text,int maxLength,Runnable onAttach,String micLabel,Runnable onMic,String sendLabel,Runnable onSend){
        this.ui=ui;
        view=ui.column();view.setTag("composer");
        idle=ui.outline(ui.surfaceAlt,24,ui.stroke,1);
        focused=ui.outline(ui.surfaceAlt,24,ui.strokeStrong,1.25f);
        view.setBackground(idle);
        view.setPadding(ui.dp(6),ui.dp(6),ui.dp(6),ui.dp(4));
        files=ui.column();// renderDraft keeps its signature in this view's tag, so it carries no tag of its own.
        files.setVisibility(View.GONE);files.setPadding(ui.dp(6),ui.dp(2),ui.dp(6),ui.dp(2));
        view.addView(files,new LinearLayout.LayoutParams(-1,-2));
        input=new EditText(ui.context);
        input.setBackground(null);
        input.setText(text==null?"":text);input.setHint(hint);
        input.setTextColor(ui.text);input.setHintTextColor(ui.muted);input.setHighlightColor(AppUi.alpha(ui.accent,.28f));
        input.setTextSize(16);input.setTypeface(AppUi.face(400));input.setIncludeFontPadding(true);
        input.setGravity(Gravity.TOP|Gravity.START);
        input.setSingleLine(false);input.setMinLines(1);input.setMaxLines(MAX_LINES);input.setVerticalScrollBarEnabled(true);
        input.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_MULTI_LINE|InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        input.setImeOptions(EditorInfo.IME_FLAG_NO_EXTRACT_UI);
        if(maxLength>0)input.setFilters(new InputFilter[]{new InputFilter.LengthFilter(maxLength)});
        input.setPadding(ui.dp(10),ui.dp(8),ui.dp(10),ui.dp(6));input.setMinHeight(ui.dp(44));
        input.setContentDescription(hint);
        input.setOnFocusChangeListener((v,has)->view.setBackground(has?focused:idle));
        view.addView(input,new LinearLayout.LayoutParams(-1,-2));
        actions=ui.row();actions.setGravity(Gravity.CENTER_VERTICAL);
        attach=bare("plus","Add attachment",onAttach);attach.setTag("composer_attach");
        if(onAttach!=null)actions.addView(attach,new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));
        actions.addView(new View(ui.context),new LinearLayout.LayoutParams(0,1,1));
        mic=bare("voice",micLabel,onMic);mic.setTag("composer_mic");
        if(onMic!=null)actions.addView(mic,new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));
        send=new ImageButton(ui.context);send.setTag("composer_send");
        GradientDrawable disc=new GradientDrawable();disc.setShape(GradientDrawable.OVAL);disc.setColor(ui.accent);
        GradientDrawable mask=new GradientDrawable();mask.setShape(GradientDrawable.OVAL);mask.setColor(0xFFFFFFFF);
        send.setBackground(new InsetDrawable(new RippleDrawable(ColorStateList.valueOf(0x40FFFFFF),disc,mask),ui.dp(4)));
        send.setImageDrawable(ui.glyph("send",ui.onAccent,20));send.setScaleType(ImageView.ScaleType.CENTER);
        send.setContentDescription(sendLabel);send.setMinimumWidth(ui.dp(48));send.setMinimumHeight(ui.dp(48));
        send.setOnClickListener(v->{if(onSend!=null)onSend.run();});AppUi.press(send);
        LinearLayout.LayoutParams sp=new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48));sp.leftMargin=ui.dp(2);
        actions.addView(send,sp);
        view.addView(actions,new LinearLayout.LayoutParams(-1,-2));
    }

    /** A borderless icon with a round ripple, like the reference composer's + and microphone. */
    private ImageButton bare(String icon,String description,Runnable action){
        ImageButton b=new ImageButton(ui.context);b.setImageDrawable(ui.glyph(icon,ui.text,22));b.setScaleType(ImageView.ScaleType.CENTER);
        GradientDrawable mask=new GradientDrawable();mask.setShape(GradientDrawable.OVAL);mask.setColor(0xFFFFFFFF);
        b.setBackground(new RippleDrawable(ColorStateList.valueOf(AppUi.alpha(ui.accent,.18f)),null,new InsetDrawable(mask,ui.dp(4))));
        b.setMinimumWidth(ui.dp(48));b.setMinimumHeight(ui.dp(48));b.setContentDescription(description);
        if(action!=null)b.setOnClickListener(v->action.run());
        return b;
    }

    /** The microphone shows Stop while dictating; labels follow so TalkBack says what a tap will do. */
    void dictating(boolean on,String idleLabel,String activeLabel){
        mic.setImageDrawable(ui.glyph(on?"stop":"voice",on?ui.accent:ui.text,22));
        mic.setContentDescription(on?activeLabel:idleLabel);
    }

    /** Editing controls (field, attachment, microphone); Send has its own rule. */
    void editable(boolean value){
        input.setEnabled(value);input.setAlpha(value?1f:.55f);
        control(attach,value);control(mic,value);
    }

    void control(View button,boolean value){if(button.isEnabled()!=value){button.setEnabled(value);button.setAlpha(value?1f:.4f);}}

    void sendable(boolean value){sendable=value;control(send,value);}
    boolean sendable(){return sendable;}

    String text(){return input.getText().toString();}
}
