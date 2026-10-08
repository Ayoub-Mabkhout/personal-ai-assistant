package com.personalassistant.companion;

import android.app.Activity;
import android.animation.ValueAnimator;
import android.content.*;
import android.content.res.*;
import android.graphics.*;
import android.graphics.drawable.*;
import android.os.Build;
import android.view.*;
import android.widget.*;

/** Native, accessible presentation primitives shared by app and locked voice entry. */
final class AppUi {
    final Activity activity;final boolean dark;
    final int background,surface,text,muted,accent,soft,stroke,warm,cool,coolAccent;
    AppUi(Activity activity){this.activity=activity;String choice=Cloud.prefs(activity).getString("ui_theme","system");dark=choice.equals("dark")||(choice.equals("system")&&(activity.getResources().getConfiguration().uiMode&Configuration.UI_MODE_NIGHT_MASK)==Configuration.UI_MODE_NIGHT_YES);background=Color.parseColor(dark?"#17131D":"#F7F5F1");surface=Color.parseColor(dark?"#231D2B":"#FFFEFC");text=Color.parseColor(dark?"#F4F0F7":"#282630");muted=Color.parseColor(dark?"#AFA5B9":"#67606F");accent=Color.parseColor(dark?"#C6B4F4":"#7254AA");soft=Color.parseColor(dark?"#34283F":"#EEE8F4");stroke=Color.parseColor(dark?"#362D3E":"#E8E3DD");warm=Color.parseColor(dark?"#D9B095":"#855D43");cool=Color.parseColor(dark?"#26323F":"#E1E7EC");coolAccent=Color.parseColor(dark?"#9EB3CD":"#5C728C");}
    static void theme(Activity activity){String value=Cloud.prefs(activity).getString("ui_theme","system");boolean dark=value.equals("dark")||(value.equals("system")&&(activity.getResources().getConfiguration().uiMode&Configuration.UI_MODE_NIGHT_MASK)==Configuration.UI_MODE_NIGHT_YES);activity.setTheme(dark?R.style.AssistantDarkTheme:R.style.AssistantLightTheme);}
    int dp(float n){return Math.round(n*activity.getResources().getDisplayMetrics().density);}
    void window(){activity.getWindow().setStatusBarColor(background);activity.getWindow().setNavigationBarColor(surface);activity.getWindow().getDecorView().setSystemUiVisibility(dark?0:View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR|View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);if(Build.VERSION.SDK_INT>=30){WindowInsetsController controller=activity.getWindow().getInsetsController();if(controller!=null){int appearance=WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS|WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;controller.setSystemBarsAppearance(dark?0:appearance,appearance);}}activity.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);}
    TextView text(String value,int size,boolean bold){TextView view=new TextView(activity);view.setText(value);view.setTextSize(size);view.setTextColor(text);view.setFontFeatureSettings("kern");view.setTypeface(Typeface.create(bold?"sans-serif-medium":"sans-serif",Typeface.NORMAL));view.setIncludeFontPadding(false);view.setLineSpacing(dp(3),1);return view;}
    TextView detail(String value){TextView view=text(value,14,false);view.setTextColor(muted);return view;}
    LinearLayout column(){LinearLayout box=new LinearLayout(activity);box.setOrientation(LinearLayout.VERTICAL);return box;}
    LinearLayout row(){LinearLayout box=new LinearLayout(activity);box.setOrientation(LinearLayout.HORIZONTAL);box.setGravity(Gravity.CENTER_VERTICAL);return box;}
    LinearLayout card(){LinearLayout box=column();box.setPadding(dp(17),dp(17),dp(17),dp(17));GradientDrawable tonal=new GradientDrawable(GradientDrawable.Orientation.TL_BR,new int[]{surface,mix(surface,cool,.10f)});tonal.setCornerRadius(dp(18));tonal.setStroke(dp(1),mix(stroke,surface,.45f));box.setBackground(tonal);LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(-1,-2);params.bottomMargin=dp(18);box.setLayoutParams(params);return box;}
    void space(LinearLayout parent,int height){View space=new View(activity);parent.addView(space,new LinearLayout.LayoutParams(1,dp(height)));}
    GradientDrawable shape(int color,int radius,int border){GradientDrawable drawable=new GradientDrawable();drawable.setColor(color);drawable.setCornerRadius(dp(radius));if(border!=0)drawable.setStroke(dp(1),border);return drawable;}
    static int mix(int a,int b,float fraction){return Color.rgb(Math.round(Color.red(a)*(1-fraction)+Color.red(b)*fraction),Math.round(Color.green(a)*(1-fraction)+Color.green(b)*fraction),Math.round(Color.blue(a)*(1-fraction)+Color.blue(b)*fraction));}
    Drawable backgroundDrawable(){return new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,new int[]{background,mix(background,cool,.18f)});}
    static boolean motion(){return Build.VERSION.SDK_INT<26||ValueAnimator.areAnimatorsEnabled();}
    static void fade(View view){view.animate().cancel();if(view.isShown()&&motion()){view.setAlpha(.25f);view.animate().alpha(1f).setDuration(170).start();}else view.setAlpha(1f);}
    Button button(String title,boolean primary,Runnable action){Button button=new Button(activity);button.setStateListAnimator(null);button.setElevation(0);button.setTranslationZ(0);button.setText(title);button.setAllCaps(false);button.setTextSize(14);button.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));button.setTextColor(primary?(dark?Color.parseColor("#261A36"):Color.WHITE):text);button.setMinHeight(dp(48));button.setMinimumHeight(dp(48));button.setPadding(dp(12),dp(10),dp(12),dp(10));button.setGravity(primary?Gravity.CENTER:Gravity.CENTER_VERTICAL|Gravity.START);button.setBackground(new RippleDrawable(ColorStateList.valueOf(dark?0x16FFFFFF:0x107254AA),shape(primary?accent:Color.TRANSPARENT,12,0),null));if(!primary){button.setCompoundDrawablesWithIntrinsicBounds(null,null,new GlyphDrawable("arrow",muted,dp(15)),null);button.setCompoundDrawablePadding(dp(8));}button.setOnClickListener(v->action.run());return button;}
    Button quietButton(String title,Runnable action){Button button=button(title,false,action);button.setTextColor(accent);button.setGravity(Gravity.CENTER);button.setCompoundDrawables(null,null,null,null);return button;}
    Button actionRow(String title,String icon,Runnable action){Button button=button(title,false,action);button.setCompoundDrawablesWithIntrinsicBounds(new GlyphDrawable(icon,coolAccent,dp(20)),null,new GlyphDrawable("arrow",muted,dp(15)),null);button.setCompoundDrawablePadding(dp(13));return button;}
    void divider(LinearLayout parent){View line=new View(activity);line.setBackgroundColor(stroke);LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,dp(1));p.topMargin=dp(10);p.bottomMargin=dp(10);parent.addView(line,p);}
    void label(LinearLayout parent,String title){TextView label=text(title,11,true);label.setTextColor(muted);label.setLetterSpacing(.11f);LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.bottomMargin=dp(12);parent.addView(label,p);}
    LinearLayout empty(String icon,String title,String detail){LinearLayout box=column();box.setGravity(Gravity.CENTER);box.setPadding(dp(24),dp(36),dp(24),dp(36));Icon mark=new Icon(activity,icon,warm);box.addView(mark,new LinearLayout.LayoutParams(dp(34),dp(34)));space(box,16);TextView head=text(title,20,true);head.setGravity(Gravity.CENTER);box.addView(head);space(box,8);TextView note=detail(detail);note.setGravity(Gravity.CENTER);box.addView(note);return box;}
    VoiceButton voiceButton(Runnable action){VoiceButton button=new VoiceButton(activity,this);button.setOnClickListener(v->action.run());return button;}
    EditText field(String hint,String value){EditText field=new EditText(activity);field.setText(value);field.setHint(hint);field.setTextColor(text);field.setHintTextColor(muted);field.setTextSize(16);field.setSingleLine(true);field.setPadding(dp(14),dp(12),dp(14),dp(12));field.setBackground(shape(surface,13,stroke));field.setMinHeight(dp(50));return field;}
    Switch toggle(String title,String description,LinearLayout parent,boolean checked,android.widget.CompoundButton.OnCheckedChangeListener listener){LinearLayout row=row();LinearLayout labels=column();labels.addView(text(title,15,true));if(!description.isEmpty()){space(labels,5);labels.addView(detail(description));}row.addView(labels,new LinearLayout.LayoutParams(0,-2,1));Switch control=new Switch(activity);control.setChecked(checked);control.setContentDescription(title);control.setThumbTintList(new ColorStateList(new int[][]{new int[]{android.R.attr.state_checked},new int[]{}},new int[]{accent,muted}));control.setTrackTintList(ColorStateList.valueOf(soft));row.addView(control,new LinearLayout.LayoutParams(dp(64),dp(50)));parent.addView(row);control.setOnCheckedChangeListener(listener);return control;}
    TextView badge(String value){TextView view=text(value,12,true);view.setTextColor(accent);view.setPadding(dp(10),dp(5),dp(10),dp(5));view.setBackground(shape(soft,9,0));return view;}
    void section(LinearLayout box,String title){TextView view=text(title,12,true);view.setTextColor(muted);view.setLetterSpacing(.09f);box.addView(view);space(box,13);}
    static void update(TextView view,String value){if(view!=null&&!view.getText().toString().equals(value)){view.setText(value);fade(view);}}
    static float level(Context context){Object raw=Cloud.prefs(context).getAll().get("voice_level");return raw instanceof Number?Math.max(0,Math.min(1,((Number)raw).floatValue())):0;}
    static boolean micActive(Context context){long at=number(context,"voice_metrics_elapsed"),age=android.os.SystemClock.elapsedRealtime()-at;return Cloud.prefs(context).getBoolean("voice_mic_active",false)&&at>0&&age>=0&&age<=3000;}
    static long number(Context context,String key){Object raw=Cloud.prefs(context).getAll().get(key);return raw instanceof Number?((Number)raw).longValue():0;}

    static final class Icon extends View {
        final String kind;int color;final Paint paint=new Paint(3);
        Icon(Context context,String kind,int color){super(context);this.kind=kind;this.color=color;setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);}
        void color(int value){color=value;invalidate();}
        @Override protected void onDraw(Canvas original){super.onDraw(original);Canvas canvas=original;canvas.save();canvas.scale(getWidth()/24f,getHeight()/24f);paint.setColor(color);paint.setStrokeWidth(1.7f);paint.setStrokeCap(Paint.Cap.ROUND);paint.setStrokeJoin(Paint.Join.ROUND);paint.setStyle(Paint.Style.STROKE);
            if(kind.equals("voice")){canvas.drawRoundRect(9,3,15,14,3,3,paint);canvas.drawArc(6,7,18,18,0,180,false,paint);canvas.drawLine(12,18,12,21,paint);canvas.drawLine(9,21,15,21,paint);}
            else if(kind.equals("shopping")){canvas.drawRoundRect(4,7,20,21,3,3,paint);canvas.drawArc(8,2,16,12,180,180,false,paint);}
            else if(kind.equals("activity")){canvas.drawCircle(12,12,8,paint);canvas.drawLine(12,7,12,12,paint);canvas.drawLine(12,12,16,14,paint);}
            else if(kind.equals("settings")){canvas.drawCircle(12,12,4,paint);for(int i=0;i<8;i++){double a=i*Math.PI/4;canvas.drawLine((float)(12+Math.cos(a)*7),(float)(12+Math.sin(a)*7),(float)(12+Math.cos(a)*10),(float)(12+Math.sin(a)*10),paint);}}
            else if(kind.equals("check")){canvas.drawLine(5,12,10,17,paint);canvas.drawLine(10,17,19,7,paint);}
            else if(kind.equals("arrow")){canvas.drawLine(9,5,16,12,paint);canvas.drawLine(16,12,9,19,paint);}
            canvas.restore();
        }
    }
    final class GlyphDrawable extends Drawable {
        final String kind;final int color,size;final Paint paint=new Paint(3);
        GlyphDrawable(String kind,int color,int size){this.kind=kind;this.color=color;this.size=size;}
        @Override public int getIntrinsicWidth(){return size;}@Override public int getIntrinsicHeight(){return size;}
        @Override public void draw(Canvas canvas){canvas.save();canvas.translate(getBounds().left,getBounds().top);canvas.scale(getBounds().width()/24f,getBounds().height()/24f);paint.setColor(color);paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(1.6f);paint.setStrokeCap(Paint.Cap.ROUND);paint.setStrokeJoin(Paint.Join.ROUND);
            if(kind.equals("arrow")){canvas.drawLine(10,7,15,12,paint);canvas.drawLine(15,12,10,17,paint);}
            else if(kind.equals("voice")){canvas.drawRoundRect(9,3,15,14,3,3,paint);canvas.drawArc(6,7,18,18,0,180,false,paint);canvas.drawLine(12,18,12,21,paint);}
            else if(kind.equals("settings")){canvas.drawCircle(12,12,5,paint);canvas.drawLine(12,2,12,5,paint);canvas.drawLine(12,19,12,22,paint);canvas.drawLine(2,12,5,12,paint);canvas.drawLine(19,12,22,12,paint);}
            else if(kind.equals("activity")){canvas.drawCircle(12,12,8,paint);canvas.drawLine(12,7,12,12,paint);canvas.drawLine(12,12,16,14,paint);}
            else if(kind.equals("shopping")){canvas.drawRoundRect(5,7,19,21,2,2,paint);canvas.drawArc(8,2,16,12,180,180,false,paint);}
            else if(kind.equals("check")){canvas.drawLine(5,12,10,17,paint);canvas.drawLine(10,17,19,7,paint);}
            else if(kind.equals("plus")){canvas.drawLine(5,12,19,12,paint);canvas.drawLine(12,5,12,19,paint);}
            else {canvas.drawCircle(12,12,7,paint);canvas.drawCircle(12,12,2,paint);}canvas.restore();}
        @Override public void setAlpha(int a){paint.setAlpha(a);}@Override public void setColorFilter(ColorFilter filter){paint.setColorFilter(filter);}@Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
    }
    static final class VoiceButton extends Button {
        final AppUi ui;final Paint paint=new Paint(3);
        VoiceButton(Context context,AppUi ui){super(context);this.ui=ui;setText("Talk");setContentDescription("Talk");setAllCaps(false);setStateListAnimator(null);setElevation(0);setPadding(0,0,0,0);setBackgroundColor(Color.TRANSPARENT);setMinWidth(0);setMinimumWidth(0);setMinHeight(0);setMinimumHeight(0);}
        @Override public boolean onTouchEvent(android.view.MotionEvent event){if(motion()){if(event.getAction()==android.view.MotionEvent.ACTION_DOWN)animate().scaleX(.96f).scaleY(.96f).setDuration(100).start();else if(event.getAction()==android.view.MotionEvent.ACTION_UP||event.getAction()==android.view.MotionEvent.ACTION_CANCEL)animate().scaleX(1).scaleY(1).setDuration(130).start();}return super.onTouchEvent(event);}
        @Override protected void onDraw(Canvas c){float x=getWidth()/2f,y=getHeight()/2f,r=Math.min(getWidth(),getHeight())*.49f;paint.setStyle(Paint.Style.FILL);paint.setAlpha(255);paint.setShader(new RadialGradient(x,y,r,new int[]{mix(ui.soft,ui.cool,.24f),ui.background},new float[]{.45f,1f},Shader.TileMode.CLAMP));c.drawCircle(x,y,r,paint);paint.setShader(null);paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(ui.dp(1));paint.setColor(ui.stroke);c.drawCircle(x,y,r*.90f,paint);paint.setColor(ui.dark?0x554E3B64:0x60DCD1E8);c.drawCircle(x,y,r*.76f,paint);float inner=r*.65f;paint.setStyle(Paint.Style.FILL);paint.setAlpha(255);paint.setShader(new LinearGradient(x-inner,y-inner,x+inner,y+inner,ui.dark?0xFF695286:0xFF9A87BA,ui.dark?0xFF302A43:0xFF554365,Shader.TileMode.CLAMP));c.drawCircle(x,y,inner,paint);paint.setShader(null);paint.setColor(isPressed()?0x20FFFFFF:0x0AFFFFFF);c.drawCircle(x,y,inner,paint);paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(ui.dp(2.4f));paint.setStrokeCap(Paint.Cap.ROUND);paint.setColor(0xFFF8F3FF);float u=ui.dp(1);c.drawRoundRect(x-8*u,y-31*u,x+8*u,y-5*u,8*u,8*u,paint);c.drawArc(x-15*u,y-22*u,x+15*u,y+3*u,0,180,false,paint);c.drawLine(x,y+3*u,x,y+11*u,paint);c.drawLine(x-6*u,y+11*u,x+6*u,y+11*u,paint);paint.setStyle(Paint.Style.FILL);paint.setTextAlign(Paint.Align.CENTER);paint.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));paint.setTextSize(17*getResources().getDisplayMetrics().scaledDensity);c.drawText("Talk",x,y+37*u,paint);}
    }
    static final class TimelineMark extends View {
        final Paint p=new Paint(3);final int color,line;
        TimelineMark(Context context,int color,int line){super(context);this.color=color;this.line=line;setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);}
        @Override protected void onDraw(Canvas c){p.setColor(line);p.setStrokeWidth(1.5f*getResources().getDisplayMetrics().density);c.drawLine(getWidth()/2f,0,getWidth()/2f,getHeight(),p);p.setColor(color);c.drawCircle(getWidth()/2f,13*getResources().getDisplayMetrics().density,4*getResources().getDisplayMetrics().density,p);}
    }
    static final class Meter extends View {
        final Paint paint=new Paint(3);final int color;float amplitude;boolean active;ValueAnimator transition;
        Meter(Context context,int color){super(context);this.color=color;setContentDescription("Microphone level");}
        void value(float level,boolean on){active=on;if(transition!=null)transition.cancel();float target=on?level:0;if(isShown()&&motion()&&Math.abs(amplitude-target)>.01f){transition=ValueAnimator.ofFloat(amplitude,target);transition.setDuration(130);transition.addUpdateListener(animation->{amplitude=(Float)animation.getAnimatedValue();invalidate();});transition.start();}else{amplitude=target;invalidate();}}
        @Override protected void onDetachedFromWindow(){if(transition!=null)transition.cancel();super.onDetachedFromWindow();}
        @Override protected void onDraw(Canvas c){super.onDraw(c);paint.setColor(color);paint.setAlpha(active?210:45);if(!active||amplitude<=.02f){paint.setAlpha(active?100:45);paint.setStrokeWidth(1);c.drawLine(getWidth()*.2f,getHeight()/2f,getWidth()*.8f,getHeight()/2f,paint);return;}int count=23;float gap=getWidth()/(float)count,width=Math.max(2,gap*.38f);for(int i=0;i<count;i++){float taper=.25f+.75f*(float)Math.sin(Math.PI*(i+1)/(count+1));float height=Math.max(4,getHeight()*.88f*amplitude*taper);c.drawRoundRect(i*gap+(gap-width)/2,(getHeight()-height)/2,i*gap+(gap+width)/2,(getHeight()+height)/2,width,width,paint);}}
    }
}
