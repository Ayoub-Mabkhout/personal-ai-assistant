package com.personalassistant.companion;
import android.service.voice.VoiceInteractionSession;
import android.content.*;
import android.os.Build;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.widget.*;

/** Assistant gesture overlay: a themed bottom card whose orb follows the live voice status. */
public class AssistantVoiceSession extends VoiceInteractionSession {
    private AppUi ui;private AppUi.VoiceButton orb;private TextView title,detail;private boolean orbLive,watching;
    private final SharedPreferences.OnSharedPreferenceChangeListener prefs=(p,key)->{if("voice_level".equals(key)){if(orb!=null)orb.level(AppUi.level(getContext()),orbLive&&AppUi.micActive(getContext()));}else refresh();};
    AssistantVoiceSession(Context context){super(context);}
    @Override public View onCreateContentView(){
        Context c=getContext();ui=new AppUi(c);
        FrameLayout root=new FrameLayout(c);root.setOnClickListener(v->hide());
        LinearLayout card=ui.column();card.setBackground(ui.cardFace(28));card.setPadding(ui.dp(20),ui.dp(20),ui.dp(20),ui.dp(20));card.setClickable(true);ui.lift(card,28,12,false);
        LinearLayout top=ui.row();orb=ui.voiceButton(this::talk);top.addView(orb,new LinearLayout.LayoutParams(ui.dp(104),ui.dp(104)));
        LinearLayout words=ui.column();words.setPadding(ui.dp(14),0,0,0);title=ui.type("Assistant voice",20,26,700,-.01f,ui.text);title.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);words.addView(title);ui.space(words,4);detail=ui.detail("");words.addView(detail);top.addView(words,new LinearLayout.LayoutParams(0,-2,1));card.addView(top);ui.space(card,18);
        Button open=ui.primaryButton("Open voice controls",()->{c.startActivity(new Intent(c,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));hide();});card.addView(open,new LinearLayout.LayoutParams(-1,-2));ui.space(card,12);
        Button stop=ui.stopButton("Stop microphone",()->{c.stopService(new Intent(c,VoiceService.class));hide();});card.addView(stop,new LinearLayout.LayoutParams(-1,-2));
        FrameLayout.LayoutParams cp=new FrameLayout.LayoutParams(-1,-2,Gravity.BOTTOM);cp.setMargins(ui.dp(12),0,ui.dp(12),ui.dp(12));root.addView(card,cp);
        root.setOnApplyWindowInsetsListener((v,insets)->{cp.bottomMargin=ui.dp(12)+insets.getSystemWindowInsetBottom();card.setLayoutParams(cp);return insets;});
        refresh();return root;
    }
    private void refresh(){
        if(orb==null)return;VoiceStatus s=AppUi.voiceStatus(getContext(),false);orbLive=s.live();
        orb.state(s.orb);orb.level(AppUi.level(getContext()),orbLive&&AppUi.micActive(getContext()));AppUi.update(title,s.title);AppUi.update(detail,s.detail);
    }
    private void talk(){try{if(getContext().checkSelfPermission("android.permission.RECORD_AUDIO")==android.content.pm.PackageManager.PERMISSION_GRANTED)getContext().startForegroundService(new Intent(getContext(),VoiceService.class).setAction(VoiceService.TALK));else getContext().startActivity(new Intent(getContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));}catch(Exception error){Cloud.prefs(getContext()).edit().putString("voice_status","Open voice controls to start microphone").commit();}}
    @Override public void onShow(Bundle args,int flags){
        super.onShow(args,flags);if(ui!=null&&AppUi.dark(getContext())!=ui.dark)setContentView(onCreateContentView());
        styleWindow();
        if(!watching){Cloud.prefs(getContext()).registerOnSharedPreferenceChangeListener(prefs);watching=true;}refresh();talk();
    }
    @Override public void onHide(){unwatch();super.onHide();}
    @Override public void onDestroy(){unwatch();super.onDestroy();}
    /** Dims what is behind the card and keeps the gesture handle legible. */
    private void styleWindow(){
        try{Window w=getWindow().getWindow();
            if(Build.VERSION.SDK_INT>=29)w.setNavigationBarContrastEnforced(false);
            w.getDecorView().setSystemUiVisibility(ui.dark?0:View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
            w.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);w.setDimAmount(ui.dark?.5f:.3f);}catch(RuntimeException ignored){}
    }
    private void unwatch(){if(watching){Cloud.prefs(getContext()).unregisterOnSharedPreferenceChangeListener(prefs);watching=false;}}
}
