package com.personalassistant.companion;

import android.animation.*;
import android.app.Activity;
import android.app.Dialog;
import android.content.*;
import android.content.res.*;
import android.graphics.*;
import android.graphics.drawable.*;
import android.os.Build;
import android.text.Layout;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.*;
import android.view.animation.*;
import android.widget.*;
import java.util.*;
import java.util.function.IntConsumer;
import java.util.function.BooleanSupplier;

/**
 * Dusk Aurora presentation toolkit shared by the app, locked voice entry and dialogs.
 * The aurora gradient is spent only on the voice orb, the selected navigation pill and primary actions;
 * buttons and the pill use violet to orchid, rose appears only inside the orb.
 */
final class AppUi {
    static final android.view.animation.Interpolator OUT=new PathInterpolator(.05f,.7f,.1f,1f),SLIDE=new PathInterpolator(.2f,0f,0f,1f);
    private static final Typeface[] FACES=new Typeface[3];

    /** Null when built for a non-Activity host (assistant overlay); window() and sheets need an Activity. */
    /** Null when built for a non-Activity host such as the assistant overlay; window() needs an Activity. */
    final Activity activity;final Context context;final boolean dark;final float density;
    final int background,surface,surfaceAlt,text,muted,accent,onAccent,accentSoft,stroke,strokeStrong;
    final int success,successSoft,warning,warningSoft,danger,dangerSoft,info,infoSoft,onDanger,glow;
    final int[] aurora;
    /** Legacy names kept for screens that have not been restyled yet. */
    final int soft,warm,cool,coolAccent;

    AppUi(Activity activity){this(activity,activity);}
    AppUi(Context context){this(context,context instanceof Activity?(Activity)context:null);}
    private AppUi(Context context,Activity activity){
        this.context=context;this.activity=activity;dark=dark(context);density=context.getResources().getDisplayMetrics().density;
        background=pick(0xFFFAF5EC,0xFF130E1C);surface=pick(0xFFFFFEFB,0xFF1D1729);surfaceAlt=pick(0xFFF3ECE4,0xFF281F38);
        text=pick(0xFF231A2E,0xFFF5F0FB);muted=pick(0xFF675C73,0xFFADA3BF);
        accent=pick(0xFF5B35D5,0xFFB39CFF);onAccent=pick(0xFFFFFFFF,0xFF1B1230);accentSoft=pick(0xFFECE5FF,0xFF2E2357);
        stroke=pick(0xFFE7DDD3,0xFF322849);strokeStrong=pick(0xFF8E829E,0xFF8479A3);
        success=pick(0xFF17784A,0xFF74DFA5);successSoft=pick(0xFFE0F2E7,0xFF173A2A);
        warning=pick(0xFF965800,0xFFFFC766);warningSoft=pick(0xFFFFEFCF,0xFF3E2D10);
        danger=pick(0xFFB3263E,0xFFFF8FA0);dangerSoft=pick(0xFFFCE3E7,0xFF44192A);onDanger=pick(0xFFFFFFFF,0xFF3A0B17);
        info=pick(0xFF3D52CC,0xFFA4B5FF);infoSoft=pick(0xFFE3E8FF,0xFF232B5C);
        aurora=dark?new int[]{0xFF8E6BFF,0xFFC46CF0,0xFFF08FC4}:new int[]{0xFF5B35D5,0xFFA23BC6,0xFFCC3F78};glow=pick(0xFF8EA2FF,0xFF8FA8FF);
        soft=accentSoft;warm=muted;cool=surfaceAlt;coolAccent=accent;
    }
    private int pick(int light,int night){return dark?night:light;}
    /** Sun follows System until this deployment explicitly configures private coordinates. */
    private static Double coordinate(Context c,String key){try{return Double.valueOf(Cloud.prefs(c).getString(key,""));}catch(RuntimeException error){return null;}}
    static boolean daylightConfigured(Context c){Double latitude=coordinate(c,"daylight_latitude"),longitude=coordinate(c,"daylight_longitude");return latitude!=null&&longitude!=null&&DaylightTheme.valid(latitude,longitude);}
    static boolean dark(Context c){return dark(c,System.currentTimeMillis());}
    static boolean dark(Context c,long at){boolean system=(c.getResources().getConfiguration().uiMode&Configuration.UI_MODE_NIGHT_MASK)==Configuration.UI_MODE_NIGHT_YES;return DaylightTheme.resolve(Cloud.prefs(c).getString("ui_theme","sun"),system,at,coordinate(c,"daylight_latitude"),coordinate(c,"daylight_longitude"));}
    static long nextThemeChange(Context c,long at){if(!"sun".equals(Cloud.prefs(c).getString("ui_theme","sun"))||!daylightConfigured(c))return Long.MAX_VALUE;return DaylightTheme.nextChange(at,coordinate(c,"daylight_latitude"),coordinate(c,"daylight_longitude"));}
    static void theme(Activity activity){activity.setTheme(dark(activity)?R.style.AssistantDarkTheme:R.style.AssistantLightTheme);}
    /** Foreground-only scheduling; the host decides when recreation is safe. */
    static final class ThemeWatcher {
        final Activity activity;final BooleanSupplier displayedDark,ready;final Runnable apply;
        final android.os.Handler main=new android.os.Handler(android.os.Looper.getMainLooper());
        boolean active,refreshPending;
        final Runnable evaluate=()->evaluate();
        final BroadcastReceiver clock=new BroadcastReceiver(){@Override public void onReceive(Context c,Intent i){check();}};
        final SharedPreferences.OnSharedPreferenceChangeListener preferences=(p,key)->{if("ui_theme".equals(key)||"daylight_latitude".equals(key)||"daylight_longitude".equals(key))check();};
        ThemeWatcher(Activity activity,BooleanSupplier displayedDark,BooleanSupplier ready,Runnable apply){this.activity=activity;this.displayedDark=displayedDark;this.ready=ready;this.apply=apply;}
        void resume(){if(active)return;active=true;refreshPending=false;IntentFilter filter=new IntentFilter(Intent.ACTION_TIME_CHANGED);filter.addAction(Intent.ACTION_TIMEZONE_CHANGED);filter.addAction(Intent.ACTION_DATE_CHANGED);filter.addAction(Intent.ACTION_CONFIGURATION_CHANGED);if(Build.VERSION.SDK_INT>=33)activity.registerReceiver(clock,filter,Context.RECEIVER_NOT_EXPORTED);else activity.registerReceiver(clock,filter);Cloud.prefs(activity).registerOnSharedPreferenceChangeListener(preferences);check();}
        void stop(){if(!active)return;active=false;main.removeCallbacks(evaluate);Cloud.prefs(activity).unregisterOnSharedPreferenceChangeListener(preferences);activity.unregisterReceiver(clock);}
        void check(){main.removeCallbacks(evaluate);if(active&&!refreshPending)main.post(evaluate);}
        private void evaluate(){if(!active||refreshPending||activity.isFinishing()||activity.isDestroyed())return;long at=System.currentTimeMillis();DaylightTheme.Refresh plan=DaylightTheme.refresh(displayedDark.getAsBoolean(),dark(activity,at),ready.getAsBoolean(),at,nextThemeChange(activity,at));if(plan.apply){refreshPending=true;apply.run();}else if(plan.delay!=Long.MAX_VALUE)main.postDelayed(evaluate,plan.delay);}
    }
    int dp(float n){return Math.round(n*density);}
    float dpf(float n){return n*density;}
    static int mix(int a,int b,float fraction){return Color.rgb(Math.round(Color.red(a)*(1-fraction)+Color.red(b)*fraction),Math.round(Color.green(a)*(1-fraction)+Color.green(b)*fraction),Math.round(Color.blue(a)*(1-fraction)+Color.blue(b)*fraction));}
    static int alpha(int color,float a){return Color.argb(Math.round(255*a),Color.red(color),Color.green(color),Color.blue(color));}
    static boolean motion(){return Build.VERSION.SDK_INT<26||ValueAnimator.areAnimatorsEnabled();}

    /** Light bars on a light page and the reverse; Android 15 ignores bar colours but still honours the icon appearance. */
    void window(){
        Window w=activity.getWindow();
        if(Build.VERSION.SDK_INT<35){w.setStatusBarColor(background);w.setNavigationBarColor(background);}
        if(Build.VERSION.SDK_INT>=29)w.setNavigationBarContrastEnforced(false);
        w.getDecorView().setSystemUiVisibility(dark?0:View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR|View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);
        if(Build.VERSION.SDK_INT>=30){WindowInsetsController controller=w.getInsetsController();if(controller!=null){int appearance=WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS|WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;controller.setSystemBarsAppearance(dark?0:appearance,appearance);}}
        w.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
    }

    // ------------------------------------------------------------------ typography
    static Typeface face(int weight){
        int slot=weight>=700?2:weight>=500?1:0;
        if(FACES[slot]==null)FACES[slot]=Build.VERSION.SDK_INT>=28?Typeface.create(Typeface.DEFAULT,weight>=700?700:weight>=500?500:400,false):slot==2?Typeface.create("sans-serif",Typeface.BOLD):Typeface.create(slot==1?"sans-serif-medium":"sans-serif",Typeface.NORMAL);
        return FACES[slot];
    }
    /** Size in sp, line height in sp (0 keeps the font's natural height), tracking in em. */
    TextView type(String value,float size,float line,int weight,float tracking,int color){
        TextView view=new TextView(context);view.setText(value);view.setTextSize(size);view.setTextColor(color);view.setTypeface(face(weight));view.setLetterSpacing(tracking);view.setIncludeFontPadding(false);
        if(line>0){int px=Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP,line,context.getResources().getDisplayMetrics()));view.setLineSpacing(Math.max(0,px-view.getPaint().getFontMetricsInt(null)),1f);}
        return view;
    }
    TextView text(String value,int size,boolean bold){return type(value,size,size*(size>=28?1.19f:size>=22?1.25f:size>=16?1.4f:1.43f),bold?700:400,size>=28?-.019f:size>=22?-.0125f:size>=17?-.006f:0f,text);}
    TextView display(String value){return type(value,32,38,700,-.019f,text);}
    TextView title(String value){return type(value,24,30,700,-.0125f,text);}
    TextView heading(String value){return type(value,17,24,700,-.006f,text);}
    TextView body(String value){return type(value,15,22,400,0,text);}
    TextView small(String value){return type(value,13,18,500,0,muted);}
    TextView detail(String value){return type(value,14,20,400,0,muted);}
    TextView label(String value){TextView view=type(value,12,16,700,.075f,muted);view.setAllCaps(true);return view;}
    void label(LinearLayout parent,String title){TextView view=label(title);LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.leftMargin=dp(4);p.topMargin=dp(6);p.bottomMargin=dp(8);parent.addView(view,p);}
    void section(LinearLayout box,String title){label(box,title);}
    /** Page header: display title with an optional muted subtitle. */
    LinearLayout header(String title,String subtitle){LinearLayout box=column();box.addView(display(title));if(subtitle!=null&&!subtitle.isEmpty()){space(box,4);box.addView(detail(subtitle));}return box;}

    // ------------------------------------------------------------------ layout and surfaces
    LinearLayout column(){LinearLayout box=new LinearLayout(context);box.setOrientation(LinearLayout.VERTICAL);return box;}
    LinearLayout row(){LinearLayout box=new LinearLayout(context);box.setOrientation(LinearLayout.HORIZONTAL);box.setGravity(Gravity.CENTER_VERTICAL);return box;}
    void space(LinearLayout parent,int height){View space=new View(context);parent.addView(space,new LinearLayout.LayoutParams(1,dp(height)));}
    GradientDrawable outline(int fill,float radiusDp,int strokeColor,float strokeDp){GradientDrawable d=new GradientDrawable();d.setColor(fill);d.setCornerRadius(dpf(radiusDp));if(strokeDp>0)d.setStroke(Math.max(1,Math.round(dpf(strokeDp))),strokeColor);return d;}
    GradientDrawable shape(int color,int radius,int border){return outline(color,radius,border,border!=0?1:0);}
    Drawable insetOf(Drawable d,int l,int t,int r,int b){return new InsetDrawable(d,dp(l),dp(t),dp(r),dp(b));}
    Drawable pillMask(){GradientDrawable m=new GradientDrawable();m.setColor(Color.WHITE);m.setCornerRadius(dpf(100));return m;}
    /** Ripple that follows a rounded outline; face may be null for transparent rows. */
    RippleDrawable pressable(Drawable face,float radiusDp){GradientDrawable mask=new GradientDrawable();mask.setColor(Color.WHITE);mask.setCornerRadius(dpf(radiusDp));return new RippleDrawable(ColorStateList.valueOf(alpha(accent,.16f)),face,mask);}
    Drawable aurora(int radiusDp,float angle,boolean threeStops){return new Aurora(threeStops?aurora:new int[]{aurora[0],aurora[1]},angle,radiusDp<0?-1:dpf(radiusDp),dpf(1));}
    Drawable pageBackground(){return new Wash(this);}
    Drawable backgroundDrawable(){return pageBackground();}
    /** Card face: hairline everywhere, plus a faint lavender top highlight in dark mode. */
    Drawable cardFace(float radiusDp){GradientDrawable base=outline(surface,radiusDp,stroke,1);return dark?new LayerDrawable(new Drawable[]{base,new TopLight(0x33B39CFF,dpf(radiusDp)*.6f,dpf(1))}):base;}
    Drawable sheetFace(){float r=dpf(28);GradientDrawable d=new GradientDrawable();d.setColor(surface);d.setCornerRadii(new float[]{r,r,r,r,0,0,0,0});d.setStroke(Math.max(1,dp(1)),stroke);return d;}
    Drawable bubble(boolean user){float r=dpf(20),t=dpf(8);GradientDrawable d=new GradientDrawable();d.setColor(user?accentSoft:surface);d.setCornerRadii(user?new float[]{r,r,r,r,t,t,r,r}:new float[]{r,r,r,r,r,r,t,t});d.setStroke(Math.max(1,dp(1)),user?alpha(accent,.2f):stroke);return d;}
    /** Soft accent-tinted shadow on API 28+; a negative radius gives a pill outline. */
    <T extends View> T lift(T view,float radiusDp,float elevationDp,boolean strong){
        final float r=dpf(radiusDp);view.setElevation(dpf(elevationDp));
        view.setOutlineProvider(new ViewOutlineProvider(){@Override public void getOutline(View v,Outline o){o.setRoundRect(0,0,v.getWidth(),v.getHeight(),r<0?v.getHeight()/2f:r);}});
        view.addOnAttachStateChangeListener(new View.OnAttachStateChangeListener(){@Override public void onViewAttachedToWindow(View v){unclip(v);}@Override public void onViewDetachedFromWindow(View v){}});
        if(Build.VERSION.SDK_INT>=28){view.setOutlineSpotShadowColor(dark?0xFF000000:strong?aurora[0]:mix(aurora[0],0xFF46286E,.45f));view.setOutlineAmbientShadowColor(dark?0xFF000000:0xFF46286E);}
        return view;
    }
    /** Parents clip children to their padding by default, which cuts off shadows at the page gutter. */
    static void unclip(View view){for(ViewParent p=view.getParent();p instanceof ViewGroup&&!(p instanceof ScrollView)&&!(p instanceof HorizontalScrollView);p=p.getParent()){((ViewGroup)p).setClipChildren(false);((ViewGroup)p).setClipToPadding(false);}}
    LinearLayout card(){LinearLayout box=column();box.setPadding(dp(18),dp(18),dp(18),dp(18));box.setBackground(cardFace(24));lift(box,24,3,false);LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(-1,-2);params.bottomMargin=dp(16);box.setLayoutParams(params);return box;}
    /** Card for stacked rows: no inner padding beyond the rounded edge. */
    LinearLayout rowsCard(){LinearLayout box=card();box.setPadding(dp(6),dp(6),dp(6),dp(6));return box;}
    LinearLayout tonalCard(){LinearLayout box=column();box.setPadding(dp(18),dp(18),dp(18),dp(18));box.setBackground(outline(accentSoft,24,alpha(accent,.22f),1));LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(-1,-2);params.bottomMargin=dp(16);box.setLayoutParams(params);return box;}
    LinearLayout panel(){LinearLayout box=column();box.setPadding(dp(14),dp(12),dp(14),dp(12));box.setBackground(outline(surfaceAlt,16,0,0));return box;}
    void divider(LinearLayout parent){hairline(parent,0);}
    View hairline(LinearLayout parent,int startInsetDp){View line=new View(context);line.setBackgroundColor(stroke);LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,Math.max(1,dp(1)));p.leftMargin=dp(startInsetDp);p.topMargin=dp(8);p.bottomMargin=dp(8);parent.addView(line,p);return line;}

    // ------------------------------------------------------------------ buttons
    private <T extends Button> T style(T b,String title,float size,int weight,int color){b.setStateListAnimator(null);b.setElevation(0);b.setTranslationZ(0);b.setText(title);b.setAllCaps(false);b.setTextSize(size);b.setTypeface(face(weight));b.setLetterSpacing(0);b.setTextColor(color);b.setIncludeFontPadding(false);b.setMinWidth(0);b.setMinimumWidth(0);b.setMinHeight(dp(48));b.setMinimumHeight(dp(48));b.setGravity(Gravity.CENTER);b.setPadding(dp(20),0,dp(20),0);press(b);return b;}
    private Button plain(String title,float size,int weight,int color,Runnable action){Button b=style(new Button(context),title,size,weight,color);b.setOnClickListener(v->action.run());return b;}
    private Pill filled(String title,int[] stops,int fg,Runnable action){
        Pill b=style(new Pill(this),title,15,700,fg);b.setMinHeight(dp(52));b.setMinimumHeight(dp(52));
        b.setTextColor(new ColorStateList(new int[][]{{-android.R.attr.state_enabled},{}},new int[]{mix(muted,background,.3f),fg}));
        StateListDrawable face=new StateListDrawable();face.addState(new int[]{-android.R.attr.state_enabled},outline(surfaceAlt,26,stroke,1));face.addState(new int[]{},new Aurora(stops,120,-1,dpf(1)));
        b.setBackground(new RippleDrawable(ColorStateList.valueOf(0x38FFFFFF),face,pillMask()));lift(b,-1,4,false);b.lift=b.getElevation();b.setOnClickListener(v->action.run());return b;
    }
    /** Primary is the aurora pill (52 dp); otherwise a full-width row with a trailing chevron. */
    Button button(String title,boolean primary,Runnable action){
        if(primary)return filled(title,new int[]{aurora[0],aurora[1]},onAccent,action);
        Button b=plain(title,15,500,text,action);b.setGravity(Gravity.CENTER_VERTICAL|Gravity.START);b.setPadding(dp(14),dp(10),dp(14),dp(10));b.setMinHeight(dp(52));b.setMinimumHeight(dp(52));b.setBackground(pressable(null,16));
        b.setCompoundDrawablesWithIntrinsicBounds(null,null,new GlyphDrawable("arrow",muted,dp(18)),null);b.setCompoundDrawablePadding(dp(8));return b;
    }
    /** Tonal pill: accent text on accent-soft, 52 dp touch height around a 40 dp face. */
    Button quietButton(String title,Runnable action){Button b=plain(title,14.5f,700,accent,action);b.setMinHeight(dp(52));b.setMinimumHeight(dp(52));b.setBackground(new RippleDrawable(ColorStateList.valueOf(alpha(accent,.2f)),insetOf(outline(accentSoft,26,0,0),0,6,0,6),insetOf(pillMask(),0,6,0,6)));b.setPadding(dp(20),0,dp(20),0);return b;}
    Button ghostButton(String title,Runnable action){Button b=plain(title,14.5f,700,accent,action);b.setBackground(pressable(null,24));return b;}
    Pill dangerButton(String title,Runnable action){return filled(title,new int[]{danger,danger},onDanger,action);}
    /** Always a strong filled control: ink pill with a stop glyph. */
    Pill stopButton(String title,Runnable action){Pill b=filled(title,new int[]{text,text},background,action);b.glyph("stop",background,20);return b;}
    /** Outlined action chip with a leading glyph; 48 dp touch area around a 36 dp face. */
    Pill chip(String label,String icon,Runnable action){
        Pill b=style(new Pill(this),label,13.5f,500,text);b.setBackground(new RippleDrawable(ColorStateList.valueOf(alpha(accent,.16f)),insetOf(outline(Color.TRANSPARENT,18,strokeStrong,1.25f),3,6,3,6),insetOf(pillMask(),3,6,3,6)));b.glyph(icon,accent,18);b.setOnClickListener(v->action.run());return b;
    }
    ImageButton iconButton(String icon,String description,Runnable action){
        ImageButton b=new ImageButton(context);b.setImageDrawable(new GlyphDrawable(icon,text,dp(22)));b.setScaleType(ImageView.ScaleType.CENTER);b.setMinimumWidth(dp(48));b.setMinimumHeight(dp(48));
        b.setBackground(new RippleDrawable(ColorStateList.valueOf(alpha(accent,.16f)),insetOf(outline(surface,24,stroke,1),3,3,3,3),insetOf(pillMask(),3,3,3,3)));b.setContentDescription(description);b.setOnClickListener(v->action.run());press(b);return b;
    }
    /** Round aurora action (add, send). */
    ImageButton fab(String icon,String description,Runnable action){
        ImageButton b=new ImageButton(context);b.setImageDrawable(new GlyphDrawable(icon,onAccent,dp(24)));b.setScaleType(ImageView.ScaleType.CENTER);b.setMinimumWidth(dp(52));b.setMinimumHeight(dp(52));
        b.setBackground(new RippleDrawable(ColorStateList.valueOf(0x38FFFFFF),new Aurora(new int[]{aurora[0],aurora[1]},130,-1,dpf(1)),pillMask()));lift(b,-1,5,false);b.setContentDescription(description);b.setOnClickListener(v->action.run());press(b);return b;
    }
    ActionRow actionRow(String title,String icon,Runnable action){return new ActionRow(this,title,icon,"",false,action);}
    /** Settings-style row with a muted value ("Balanced") before the chevron. */
    ActionRow actionRow(String title,String icon,String value,Runnable action){return new ActionRow(this,title,icon,value,false,action);}
    ActionRow dangerRow(String title,String icon,Runnable action){return new ActionRow(this,title,icon,"",true,action);}
    StatusChip statusChip(String value,String tone){return new StatusChip(this,value,tone,true);}
    /** Tone: success, warning, danger, info, accent; anything else is neutral. Returns {foreground, soft background}. */
    int[] toneColors(String tone){
        if("success".equals(tone))return new int[]{success,successSoft};if("warning".equals(tone))return new int[]{warning,warningSoft};if("danger".equals(tone))return new int[]{danger,dangerSoft};
        if("info".equals(tone))return new int[]{info,infoSoft};if("accent".equals(tone))return new int[]{accent,accentSoft};if("orchid".equals(tone))return new int[]{mix(aurora[1],text,dark?0:.1f),mix(surface,aurora[1],dark?.2f:.12f)};return new int[]{muted,surfaceAlt};
    }
    /** Maps raw or labelled task states to a chip tone. */
    static String toneOf(String state){
        String s=state==null?"":state.toLowerCase(Locale.ROOT).replace(' ','_');
        if(s.equals("completed")||s.equals("complete")||s.equals("answer")||s.equals("done"))return "success";if(s.equals("failed")||s.equals("error"))return "danger";if(s.equals("needs_input")||s.equals("needs_your_input")||s.equals("waiting"))return "warning";
        if(s.equals("running")||s.equals("in_progress")||s.equals("leased")||s.equals("queued")||s.equals("pending")||s.equals("received"))return "info";return "neutral";
    }
    /** Tinted tile colours for a leading row icon. */
    int[] iconTone(String icon){
        String k=Glyphs.canonical(icon);
        if(k.equals("voice")||k.equals("sparkle")||k.equals("appearance")||k.equals("waveform"))return toneColors("accent");
        if(k.equals("settings")||k.equals("download")||k.equals("link")||k.equals("cloud")||k.equals("tile")||k.equals("info")||k.equals("history"))return toneColors("info");
        if(k.equals("check")||k.equals("shield-check")||k.equals("phone-saved"))return toneColors("success");
        if(k.equals("bell")||k.equals("battery")||k.equals("clock")||k.equals("alert"))return toneColors("warning");
        if(k.equals("logout")||k.equals("trash")||k.equals("x-circle"))return toneColors("danger");
        return toneColors("orchid");
    }

    // ------------------------------------------------------------------ inputs
    EditText field(String hint,String value){return field(hint,value,false);}
    /** Surface fill with a strong boundary (3:1); accent boundary while focused. */
    EditText field(String hint,String value,boolean pill){
        EditText f=new EditText(context);f.setText(value);f.setHint(hint);f.setTextColor(text);f.setHintTextColor(muted);f.setTextSize(16);f.setTypeface(face(400));f.setIncludeFontPadding(false);f.setSingleLine(true);f.setGravity(Gravity.CENTER_VERTICAL);
        f.setPadding(dp(pill?20:16),dp(14),dp(pill?20:16),dp(14));f.setMinHeight(dp(52));f.setMinimumHeight(dp(52));f.setHighlightColor(alpha(accent,.28f));
        float r=pill?26:16;StateListDrawable face=new StateListDrawable();face.addState(new int[]{android.R.attr.state_focused},outline(surface,r,accent,2));face.addState(new int[]{},outline(surface,r,strokeStrong,1.5f));f.setBackground(face);return f;
    }
    Switch toggle(String title,String description,LinearLayout parent,boolean checked,android.widget.CompoundButton.OnCheckedChangeListener listener){
        LinearLayout row=row();row.setMinimumHeight(dp(56));LinearLayout labels=column();labels.addView(text(title,15,true));if(!description.isEmpty()){space(labels,3);TextView note=detail(description);note.setTextSize(13);labels.addView(note);}
        row.addView(labels,new LinearLayout.LayoutParams(0,-2,1));
        Switch control=new Switch(context);control.setShowText(false);control.setSplitTrack(false);control.setTrackDrawable(new SwitchTrack(this));control.setThumbDrawable(new SwitchThumb(this));control.setChecked(checked);control.setContentDescription(title);
        LinearLayout.LayoutParams sp=new LinearLayout.LayoutParams(dp(60),dp(48));sp.leftMargin=dp(8);row.addView(control,sp);row.setOnClickListener(v->control.performClick());row.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        parent.addView(row);control.setOnCheckedChangeListener(listener);control.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_YES);return control;
    }
    TextView badge(String value){return new StatusChip(this,value,"accent",false);}
    LinearLayout empty(String icon,String title,String detail){return empty(icon,title,detail,null,null);}
    /** Small vector illustration, a heading, one line of guidance and optionally the next useful action. */
    LinearLayout empty(String icon,String title,String detail,String actionLabel,Runnable action){
        LinearLayout box=column();box.setGravity(Gravity.CENTER_HORIZONTAL);box.setPadding(dp(24),dp(24),dp(24),dp(28));
        box.addView(new Illustration(this,icon),new LinearLayout.LayoutParams(dp(132),dp(104)));space(box,12);
        TextView head=heading(title);head.setGravity(Gravity.CENTER);box.addView(head);space(box,6);TextView note=detail(detail);note.setGravity(Gravity.CENTER);box.addView(note);
        if(actionLabel!=null&&action!=null){space(box,12);Button next=quietButton(actionLabel,action);box.addView(next,new LinearLayout.LayoutParams(-2,-2));}
        return box;
    }
    /** Theme for full-screen sheets (edge to edge, slide-up animation); use with new Dialog(context, ui.sheetTheme()). */
    int sheetTheme(){return dark?R.style.AssistantDarkSheet:R.style.AssistantLightSheet;}
    Dialog sheet(){Dialog dialog=new Dialog(context,sheetTheme());dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);return dialog;}
    VoiceButton voiceButton(Runnable action){VoiceButton button=new VoiceButton(context,this);button.setOnClickListener(v->action.run());return button;}
    NavBar navBar(String[] labels,String[] icons,String[] tags,IntConsumer onSelect){return new NavBar(this,labels,icons,tags,onSelect);}
    Drawable glyph(String kind,int color,int sizeDp){return new GlyphDrawable(kind,color,dp(sizeDp));}

    // ------------------------------------------------------------------ prefs
    static float level(Context context){try{return Math.max(0,Math.min(1,Cloud.prefs(context).getFloat("voice_level",0f)));}catch(ClassCastException e){return Math.max(0,Math.min(1,(float)number(context,"voice_level")));}}
    static boolean micActive(Context context){long at=number(context,"voice_metrics_elapsed"),age=android.os.SystemClock.elapsedRealtime()-at;return Cloud.prefs(context).getBoolean("voice_mic_active",false)&&at>0&&age>=0&&age<=3000;}
    static long number(Context context,String key){
        SharedPreferences p=Cloud.prefs(context);
        try{return p.getLong(key,0);}catch(ClassCastException a){try{return p.getInt(key,0);}catch(ClassCastException b){try{return (long)p.getFloat(key,0f);}catch(ClassCastException c){return 0;}}}
    }

    // ------------------------------------------------------------------ motion (all gated by motion())
    /** Press feedback: scale .97 in 90 ms, back in 160 ms. */
    static void press(View view){
        view.setOnTouchListener((v,e)->{int a=e.getActionMasked();
            if(a==MotionEvent.ACTION_DOWN&&motion())v.animate().scaleX(.97f).scaleY(.97f).setDuration(90).start();
            else if(a==MotionEvent.ACTION_UP||a==MotionEvent.ACTION_CANCEL){if(motion())v.animate().scaleX(1f).scaleY(1f).setDuration(160).start();else{v.setScaleX(1f);v.setScaleY(1f);}}
            return false;});
    }
    /** Fade plus a 12 dp rise; new entries only. */
    static void enter(View view,int delayMs){
        view.animate().cancel();
        if(!motion()||!view.isShown()){view.setAlpha(1f);view.setTranslationY(0f);return;}
        view.setAlpha(0f);view.setTranslationY(12*view.getResources().getDisplayMetrics().density);view.animate().alpha(1f).translationY(0f).setStartDelay(delayMs).setDuration(260).setInterpolator(OUT).start();
    }
    static void stagger(ViewGroup group){for(int i=0;i<group.getChildCount();i++)enter(group.getChildAt(i),Math.min(i,7)*45);}
    /** Direction-aware page switch: +1 enters from the right, -1 from the left. */
    static void slide(View page,int direction){
        page.animate().cancel();
        if(!motion()||!page.isShown()){page.setAlpha(1f);page.setTranslationX(0f);return;}
        page.setAlpha(0f);page.setTranslationX(direction*20*page.getResources().getDisplayMetrics().density);page.animate().alpha(1f).translationX(0f).setStartDelay(0).setDuration(260).setInterpolator(SLIDE).start();
    }
    static void fade(View view){view.animate().cancel();if(view.isShown()&&motion()){view.setAlpha(.2f);view.animate().alpha(1f).setStartDelay(0).setDuration(150).setInterpolator(OUT).start();}else view.setAlpha(1f);}
    /** Status text change: the new text fades in over 150 ms; nothing is left translucent when motion is off. */
    static void update(TextView view,String value){if(view!=null&&!view.getText().toString().equals(value)){view.setText(value);fade(view);}}
    static void collapse(View row,Runnable done){
        if(!motion()||!row.isShown()||row.getHeight()==0){row.setVisibility(View.GONE);if(done!=null)done.run();return;}
        final ViewGroup.LayoutParams lp=row.getLayoutParams();final int from=row.getHeight();ValueAnimator a=ValueAnimator.ofInt(from,0);a.setDuration(240);a.setInterpolator(SLIDE);
        a.addUpdateListener(x->{lp.height=(Integer)x.getAnimatedValue();row.setLayoutParams(lp);row.setAlpha(1f-x.getAnimatedFraction());});
        a.addListener(new AnimatorListenerAdapter(){@Override public void onAnimationEnd(Animator x){row.setVisibility(View.GONE);lp.height=ViewGroup.LayoutParams.WRAP_CONTENT;row.setLayoutParams(lp);row.setAlpha(1f);if(done!=null)done.run();}});a.start();
    }
    static void expand(View row){
        row.setVisibility(View.VISIBLE);if(!motion()||!row.isAttachedToWindow())return;
        final ViewGroup.LayoutParams lp=row.getLayoutParams();row.measure(View.MeasureSpec.makeMeasureSpec(((View)row.getParent()).getWidth(),View.MeasureSpec.AT_MOST),View.MeasureSpec.makeMeasureSpec(0,View.MeasureSpec.UNSPECIFIED));
        final int to=row.getMeasuredHeight();ValueAnimator a=ValueAnimator.ofInt(0,to);a.setDuration(240);a.setInterpolator(SLIDE);
        a.addUpdateListener(x->{lp.height=(Integer)x.getAnimatedValue();row.setLayoutParams(lp);row.setAlpha(x.getAnimatedFraction());});
        a.addListener(new AnimatorListenerAdapter(){@Override public void onAnimationEnd(Animator x){lp.height=ViewGroup.LayoutParams.WRAP_CONTENT;row.setLayoutParams(lp);row.setAlpha(1f);}});a.start();
    }

    // ------------------------------------------------------------------ glyph library (24x24, stroke 1.75, round caps and joins)
    /** Path mini-language: SVG commands M L H V C Q A Z, plus O cx cy r and R x y w h r; segments are separated by |, F fills, B fills and strokes. */
    static final class Glyphs {
        private static final String[] DATA={
            "voice","R9 3 6 11 3|M5.5 11 A6.5 6.5 0 0 0 18.5 11|M12 17.5 V21|M8.5 21 H15.5",
            "shopping","M6.5 3 L3.5 7 V19.5 A1.8 1.8 0 0 0 5.3 21.3 H18.7 A1.8 1.8 0 0 0 20.5 19.5 V7 L17.5 3 Z|M3.5 7 H20.5|M15.5 10.5 A3.5 3.5 0 0 1 8.5 10.5",
            "activity","M3 12 H7 L9.5 5.5 L14 18.5 L16.5 12 H21",
            "settings","M4 7 H11.8|M16.2 7 H20|O14 7 2.2|M4 17 H7.8|M12.2 17 H20|O10 17 2.2",
            "check","M5 12.5 L9.5 17 L19 7.5",
            "arrow","M9.5 6 L15.5 12 L9.5 18",
            "back","M19 12 H5|M11 6 L5 12 L11 18",
            "down","M6 9.5 L12 15.5 L18 9.5",
            "up","M6 14.5 L12 8.5 L18 14.5",
            "plus","M12 5 V19|M5 12 H19",
            "close","M6.5 6.5 L17.5 17.5|M17.5 6.5 L6.5 17.5",
            "refresh","M20 12 A8 8 0 1 1 17.7 6.3 L20 8.5|M20 4 V8.5 H15.5",
            "recipe","M12 7 C10.5 5.7 8.2 5 4.5 5.2 V18.2 C8.2 18 10.5 18.7 12 20 C13.5 18.7 15.8 18 19.5 18.2 V5.2 C15.8 5 13.5 5.7 12 7 Z|M12 7 V20",
            "bell","M6 16.5 V11 A6 6 0 0 1 18 11 V16.5 L19.5 18 H4.5 Z|M10 20.5 A2 2 0 0 0 14 20.5",
            "battery","R2.5 7.5 16 9 2.5|M20.5 10.5 V13.5|M6.5 10.5 V13.5|M10 10.5 V13.5",
            "shield-check","M12 3 L19 5.5 V11 C19 15.3 16 18.6 12 20.3 C8 18.6 5 15.3 5 11 V5.5 Z|M8.8 12 L11.2 14.4 L15.4 9.8",
            "sparkle","M12 3.5 Q12.9 11.1 20.5 12 Q12.9 12.9 12 20.5 Q11.1 12.9 3.5 12 Q11.1 11.1 12 3.5 Z|M19 2.8 V6.2|M17.3 4.5 H20.7",
            "appearance","M12 3 A6 6 0 0 0 21 12 A9 9 0 1 1 12 3 Z",
            "link","M10 13 A5 5 0 0 0 17.54 13.54 L20.54 10.54 A5 5 0 0 0 13.47 3.47 L11.75 5.18|M14 11 A5 5 0 0 0 6.46 10.46 L3.46 13.46 A5 5 0 0 0 10.53 20.53 L12.24 18.82",
            "logout","M9.5 4.5 H6.5 A2 2 0 0 0 4.5 6.5 V17.5 A2 2 0 0 0 6.5 19.5 H9.5|M16 8 L20 12 L16 16|M20 12 H9.5",
            "download","M12 4 V15|M7.5 10.5 L12 15 L16.5 10.5|M5 19.5 H19",
            "tile","R4 4 6.5 6.5 1.8|R13.5 4 6.5 6.5 1.8|R4 13.5 6.5 6.5 1.8|R13.5 13.5 6.5 6.5 1.8",
            "send","M12 19 V5.5|M6 11 L12 5 L18 11",
            "search","O10.5 10.5 6.2|M15.2 15.2 L19.5 19.5",
            "history","M3.5 12 A8.5 8.5 0 1 0 6 6 L3.5 8.5|M3.5 4 V8.5 H8|M12 7.5 V12 L15 13.8",
            "cloud","M17.5 19 H9 A7 7 0 1 1 15.71 10 H17.5 A4.5 4.5 0 1 1 17.5 19 Z",
            "cloud-off","M17.5 19 H9 A7 7 0 1 1 15.71 10 H17.5 A4.5 4.5 0 1 1 17.5 19 Z|M4 4 L20 20",
            "phone-saved","R7 2.5 10 19 2.5|M9.8 12.2 L11.6 14 L14.6 10.8|M11 18 H13",
            "clock","O12 12 8.5|M12 7.5 V12 L15 14",
            "alert","M10.29 3.86 L1.82 18 A2 2 0 0 0 3.53 21 H20.47 A2 2 0 0 0 22.18 18 L13.71 3.86 A2 2 0 0 0 10.29 3.86 Z|M12 9.5 V13.5|FO12 17.2 1",
            "x-circle","O12 12 8.5|M9.2 9.2 L14.8 14.8|M14.8 9.2 L9.2 14.8",
            "undo","M9 14.5 L4 9.5 L9 4.5|M4 9.5 H14.5 A5.5 5.5 0 0 1 14.5 20.5 H11",
            "waveform","M4 10 V14|M8 6.5 V17.5|M12 3.5 V20.5|M16 7.5 V16.5|M20 10 V14",
            "chat","M4 6.5 A2.5 2.5 0 0 1 6.5 4 H17.5 A2.5 2.5 0 0 1 20 6.5 V13.5 A2.5 2.5 0 0 1 17.5 16 H10 L5.5 20 V16 H6.5 A2.5 2.5 0 0 1 4 13.5 Z",
            "headphones","M4 14 V12 A8 8 0 0 1 20 12 V14|R3.5 13.5 4 6.5 1.8|R16.5 13.5 4 6.5 1.8",
            "trash","M4.5 7 H19.5|M9.5 7 V5 A1 1 0 0 1 10.5 4 H13.5 A1 1 0 0 1 14.5 5 V7|M6.5 7 L7.3 18.6 A2 2 0 0 0 9.3 20.5 H14.7 A2 2 0 0 0 16.7 18.6 L17.5 7|M10 11 V16|M14 11 V16",
            "info","O12 12 8.5|M12 11 V16|FO12 7.9 1",
            "stop","BR7.5 7.5 9 9 1.6",
            "play","BM8.5 6 L18 12 L8.5 18 Z",
            "star","FM12 2 Q12.9 11.1 22 12 Q12.9 12.9 12 22 Q11.1 12.9 2 12 Q11.1 11.1 12 2 Z",
            "bolt","M13 2.5 L4.5 13.5 H11.5 L10.5 21.5 L19.5 10.5 H12.5 Z",
            "edit","M4.5 19.5 L5.3 15.7 L16 5 A2 2 0 0 1 19 8 L8.3 18.7 Z|M14 7 L17 10"};
        private static final String[] ALIAS={"mic","voice","bag","shopping","cart","shopping","pulse","activity","sliders","settings","tick","check","chevron","arrow","chevron-right","arrow","next","arrow","moon","appearance","grid","tile","book","recipe","shield","shield-check","arrow-up","send","wave","waveform","spark","sparkle","delete","trash","warning","alert","error","x-circle","offline","cloud-off","time","clock","disconnect","logout","install","download","cog","settings"};
        private static HashMap<String,Object[]> cache;
        static String canonical(String kind){if(kind==null)return "";for(int i=0;i<ALIAS.length;i+=2)if(ALIAS[i].equals(kind))return ALIAS[i+1];return kind;}
        private static synchronized Object[] get(String kind){
            if(cache==null)cache=new HashMap<>();String k=canonical(kind);Object[] hit=cache.get(k);if(hit!=null)return hit;
            String data="O12 12 7.5|FO12 12 1.6";for(int i=0;i<DATA.length;i+=2)if(DATA[i].equals(k)){data=DATA[i+1];break;}
            String[] parts=data.split("\\|");Path[] paths=new Path[parts.length];int[] modes=new int[parts.length];
            for(int i=0;i<parts.length;i++){String s=parts[i];if(s.charAt(0)=='F'){modes[i]=1;s=s.substring(1);}else if(s.charAt(0)=='B'){modes[i]=2;s=s.substring(1);}paths[i]=path(s);}
            hit=new Object[]{paths,modes};cache.put(k,hit);return hit;
        }
        /** Draws into a 24x24 box already mapped onto the canvas; the caller sets colour and alpha. */
        static void draw(Canvas c,String kind,Paint p,float units){
            Object[] g=get(kind);Path[] paths=(Path[])g[0];int[] modes=(int[])g[1];p.setStrokeCap(Paint.Cap.ROUND);p.setStrokeJoin(Paint.Join.ROUND);p.setStrokeWidth(units);
            for(int i=0;i<paths.length;i++){p.setStyle(modes[i]==0?Paint.Style.STROKE:modes[i]==1?Paint.Style.FILL:Paint.Style.FILL_AND_STROKE);c.drawPath(paths[i],p);}
            p.setStyle(Paint.Style.STROKE);
        }
        /** Stroke in glyph units that stays at least ~1.5 dp when a glyph is drawn small. */
        static float units(float sizePx,float density){return Math.max(1.75f,1.45f*density*24f/Math.max(1f,sizePx));}
        private static void skip(String d,int[] i){while(i[0]<d.length()&&(d.charAt(i[0])==' '||d.charAt(i[0])==','))i[0]++;}
        private static float num(String d,int[] i){skip(d,i);int s=i[0],n=d.length();if(i[0]<n&&(d.charAt(i[0])=='-'||d.charAt(i[0])=='+'))i[0]++;boolean dot=false;while(i[0]<n){char ch=d.charAt(i[0]);if(ch>='0'&&ch<='9')i[0]++;else if(ch=='.'&&!dot){dot=true;i[0]++;}else break;}return Float.parseFloat(d.substring(s,i[0]));}
        private static boolean flag(String d,int[] i){skip(d,i);return d.charAt(i[0]++)=='1';}
        private static Path path(String d){
            Path p=new Path();int[] i={0};float x=0,y=0,sx=0,sy=0;char c=0;
            while(true){
                skip(d,i);if(i[0]>=d.length())break;
                char ch=d.charAt(i[0]);if(Character.isLetter(ch)){c=ch;i[0]++;if(c=='Z'||c=='z'){p.close();x=sx;y=sy;continue;}}
                boolean rel=Character.isLowerCase(c);
                switch(Character.toUpperCase(c)){
                    case 'M':{float a=num(d,i),b=num(d,i);if(rel){a+=x;b+=y;}p.moveTo(a,b);x=sx=a;y=sy=b;c=rel?'l':'L';break;}
                    case 'L':{float a=num(d,i),b=num(d,i);if(rel){a+=x;b+=y;}p.lineTo(a,b);x=a;y=b;break;}
                    case 'H':{float a=num(d,i);if(rel)a+=x;p.lineTo(a,y);x=a;break;}
                    case 'V':{float b=num(d,i);if(rel)b+=y;p.lineTo(x,b);y=b;break;}
                    case 'C':{float a=num(d,i),b=num(d,i),e=num(d,i),f=num(d,i),g=num(d,i),h=num(d,i);if(rel){a+=x;b+=y;e+=x;f+=y;g+=x;h+=y;}p.cubicTo(a,b,e,f,g,h);x=g;y=h;break;}
                    case 'Q':{float a=num(d,i),b=num(d,i),e=num(d,i),f=num(d,i);if(rel){a+=x;b+=y;e+=x;f+=y;}p.quadTo(a,b,e,f);x=e;y=f;break;}
                    case 'A':{float rx=num(d,i),ry=num(d,i);num(d,i);boolean large=flag(d,i),sweep=flag(d,i);float ex=num(d,i),ey=num(d,i);if(rel){ex+=x;ey+=y;}arc(p,x,y,rx,ry,large,sweep,ex,ey);x=ex;y=ey;break;}
                    case 'O':{float a=num(d,i),b=num(d,i),r=num(d,i);p.addCircle(a,b,r,Path.Direction.CW);break;}
                    case 'R':{float a=num(d,i),b=num(d,i),w=num(d,i),h=num(d,i),r=num(d,i);p.addRoundRect(new RectF(a,b,a+w,b+h),r,r,Path.Direction.CW);break;}
                    default:return p;
                }
            }
            return p;
        }
        private static void arc(Path p,float x0,float y0,float rx,float ry,boolean large,boolean sweep,float x,float y){
            if(rx==0||ry==0){p.lineTo(x,y);return;}
            double dx=(x0-x)/2.0,dy=(y0-y)/2.0,lambda=dx*dx/((double)rx*rx)+dy*dy/((double)ry*ry);if(lambda>1){double s=Math.sqrt(lambda);rx*=s;ry*=s;}
            double rx2=(double)rx*rx,ry2=(double)ry*ry,num=rx2*ry2-rx2*dy*dy-ry2*dx*dx,den=rx2*dy*dy+ry2*dx*dx,coef=(large==sweep?-1:1)*Math.sqrt(Math.max(0,num/den));
            double cxp=coef*(rx*dy/ry),cyp=coef*(-ry*dx/rx),cx=cxp+(x0+x)/2.0,cy=cyp+(y0+y)/2.0;
            double t1=Math.atan2((dy-cyp)/ry,(dx-cxp)/rx),t2=Math.atan2((-dy-cyp)/ry,(-dx-cxp)/rx),delta=t2-t1;
            if(!sweep&&delta>0)delta-=2*Math.PI;else if(sweep&&delta<0)delta+=2*Math.PI;
            p.arcTo(new RectF((float)(cx-rx),(float)(cy-ry),(float)(cx+rx),(float)(cy+ry)),(float)Math.toDegrees(t1),(float)Math.toDegrees(delta));
        }
    }
    static final class Icon extends View {
        String kind;int color;float strokeUnits;final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
        Icon(Context context,String kind,int color){super(context);this.kind=kind;this.color=color;setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);}
        void color(int value){color=value;invalidate();}
        void kind(String value){kind=value;invalidate();}
        /** Fixed stroke in glyph units; default scales so small icons keep a 1.5 dp line. */
        void stroke(float units){strokeUnits=units;invalidate();}
        @Override protected void onDraw(Canvas canvas){
            super.onDraw(canvas);if(getWidth()==0)return;canvas.save();canvas.scale(getWidth()/24f,getHeight()/24f);paint.setColor(color);
            Glyphs.draw(canvas,kind,paint,strokeUnits>0?strokeUnits:Glyphs.units(getWidth(),getResources().getDisplayMetrics().density));canvas.restore();
        }
    }
    static final class GlyphDrawable extends Drawable {
        final String kind;int color;final int size;final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
        GlyphDrawable(String kind,int color,int size){this.kind=kind;this.color=color;this.size=size;}
        void color(int value){color=value;invalidateSelf();}
        @Override public int getIntrinsicWidth(){return size;}@Override public int getIntrinsicHeight(){return size;}
        @Override public void draw(Canvas canvas){
            Rect b=getBounds();if(b.isEmpty())return;canvas.save();canvas.translate(b.left,b.top);canvas.scale(b.width()/24f,b.height()/24f);paint.setColor(color);
            Glyphs.draw(canvas,kind,paint,Glyphs.units(b.width(),Resources.getSystem().getDisplayMetrics().density));canvas.restore();
        }
        @Override public void setAlpha(int a){paint.setAlpha(a);invalidateSelf();}@Override public void setColorFilter(ColorFilter filter){paint.setColorFilter(filter);}@Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
    }

    // ------------------------------------------------------------------ drawables
    /** Linear gradient pill or rounded rect at a CSS angle with a 1 dp light rim along the top edge. */
    static final class Aurora extends Drawable {
        final int[] colors;final float angle,radius,rimPx;final Paint fill=new Paint(Paint.ANTI_ALIAS_FLAG),rim=new Paint(Paint.ANTI_ALIAS_FLAG);final RectF box=new RectF(),inner=new RectF();
        Aurora(int[] colors,float angle,float radiusPx,float rimPx){this.colors=colors;this.angle=angle;this.radius=radiusPx;this.rimPx=rimPx;rim.setStyle(Paint.Style.STROKE);rim.setStrokeWidth(rimPx);}
        @Override protected void onBoundsChange(Rect b){
            box.set(b);double a=Math.toRadians(angle);float dx=(float)Math.sin(a),dy=-(float)Math.cos(a),len=Math.abs(b.width()*dx)+Math.abs(b.height()*dy),cx=b.exactCenterX(),cy=b.exactCenterY();
            fill.setShader(new LinearGradient(cx-dx*len/2,cy-dy*len/2,cx+dx*len/2,cy+dy*len/2,colors,colors.length==3?new float[]{0,.58f,1}:null,Shader.TileMode.CLAMP));
            if(rimPx>0){rim.setShader(new LinearGradient(0,b.top,0,b.top+b.height()*.6f,0x52FFFFFF,0x00FFFFFF,Shader.TileMode.CLAMP));inner.set(box);inner.inset(rimPx/2,rimPx/2);}
        }
        @Override public void draw(Canvas c){float r=radius<0?box.height()/2f:radius;c.drawRoundRect(box,r,r,fill);if(rimPx>0)c.drawRoundRect(inner,Math.max(0,r-rimPx/2),Math.max(0,r-rimPx/2),rim);}
        @Override public void getOutline(Outline o){Rect b=getBounds();o.setRoundRect(b,radius<0?b.height()/2f:radius);}
        @Override public void setAlpha(int a){fill.setAlpha(a);rim.setAlpha(a);invalidateSelf();}@Override public void setColorFilter(ColorFilter f){fill.setColorFilter(f);}@Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
    }
    /** Page background: flat colour with a faint periwinkle wash from the top and violet/rose corners. */
    static final class Wash extends Drawable {
        final int base;final float density;final boolean dark;final int[] colors;final Paint[] spots=new Paint[3];final Paint flat=new Paint();
        Wash(AppUi ui){base=ui.background;density=ui.density;dark=ui.dark;colors=new int[]{alpha(dark?ui.aurora[0]:ui.glow,dark?.26f:.30f),alpha(ui.aurora[2],dark?.08f:.11f),alpha(dark?ui.glow:ui.aurora[0],dark?.10f:.10f)};flat.setColor(base);for(int i=0;i<3;i++)spots[i]=new Paint();}
        @Override protected void onBoundsChange(Rect b){
            float w=b.width(),hh=Math.min(b.height(),430*density);float[][] geo={{.5f,-.04f,.66f,.45f},{1.04f,.10f,.43f,.29f},{-.04f,.14f,.40f,.29f}};
            for(int i=0;i<3;i++){RadialGradient g=new RadialGradient(0,0,1,new int[]{colors[i],colors[i]&0x00FFFFFF},null,Shader.TileMode.CLAMP);Matrix m=new Matrix();m.setScale(geo[i][2]*w,geo[i][3]*hh);m.postTranslate(b.left+geo[i][0]*w,b.top+geo[i][1]*hh);g.setLocalMatrix(m);spots[i].setShader(g);}
        }
        @Override public void draw(Canvas c){Rect b=getBounds();c.drawRect(b,flat);for(Paint p:spots)c.drawRect(b,p);}
        @Override public void setAlpha(int a){}@Override public void setColorFilter(ColorFilter f){}@Override public int getOpacity(){return PixelFormat.OPAQUE;}
    }
    /** 1 dp lavender highlight along the top edge of dark cards. */
    static final class TopLight extends Drawable {
        final Paint p=new Paint();final int color;final float inset,thickness;
        TopLight(int color,float inset,float thickness){this.color=color;this.inset=inset;this.thickness=Math.max(1,thickness);}
        @Override protected void onBoundsChange(Rect b){p.setShader(new LinearGradient(b.left+inset,0,b.right-inset,0,new int[]{color&0x00FFFFFF,color,color&0x00FFFFFF},new float[]{0,.5f,1},Shader.TileMode.CLAMP));}
        @Override public void draw(Canvas c){Rect b=getBounds();c.drawRect(b.left+inset,b.top+thickness,b.right-inset,b.top+2*thickness,p);}
        @Override public void setAlpha(int a){p.setAlpha(a);}@Override public void setColorFilter(ColorFilter f){}@Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
    }
    static final class SwitchTrack extends Drawable {
        final int on0,on1,off,edge;final float w,h,pad,ring;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);boolean checked;
        SwitchTrack(AppUi ui){on0=ui.aurora[0];on1=ui.aurora[1];off=ui.surfaceAlt;edge=ui.strokeStrong;w=ui.dpf(52);h=ui.dpf(32);pad=ui.dpf(4);ring=ui.dpf(2);}
        @Override public int getIntrinsicWidth(){return Math.round(w);}@Override public int getIntrinsicHeight(){return Math.round(h);}
        @Override public boolean getPadding(Rect r){r.set(Math.round(pad),0,Math.round(pad),0);return true;}
        @Override public boolean isStateful(){return true;}
        @Override protected boolean onStateChange(int[] state){boolean now=false;for(int s:state)if(s==android.R.attr.state_checked)now=true;boolean changed=now!=checked;checked=now;return changed;}
        @Override public void draw(Canvas c){
            Rect b=getBounds();float r=b.height()/2f;RectF box=new RectF(b);
            if(checked){p.setStyle(Paint.Style.FILL);p.setShader(new LinearGradient(b.left,0,b.right,0,on0,on1,Shader.TileMode.CLAMP));c.drawRoundRect(box,r,r,p);p.setShader(null);}
            else{p.setStyle(Paint.Style.FILL);p.setColor(off);c.drawRoundRect(box,r,r,p);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(ring);p.setColor(edge);box.inset(ring/2,ring/2);c.drawRoundRect(box,r-ring/2,r-ring/2,p);}
        }
        @Override public void setAlpha(int a){p.setAlpha(a);}@Override public void setColorFilter(ColorFilter f){p.setColorFilter(f);}@Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
    }
    static final class SwitchThumb extends Drawable {
        final int knob,tick,dot,size;final float density;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);boolean checked;
        SwitchThumb(AppUi ui){knob=ui.onAccent;tick=ui.accent;dot=ui.strokeStrong;size=ui.dp(24);density=ui.density;}
        @Override public int getIntrinsicWidth(){return size;}@Override public int getIntrinsicHeight(){return size;}
        @Override public boolean isStateful(){return true;}
        @Override protected boolean onStateChange(int[] state){boolean now=false;for(int s:state)if(s==android.R.attr.state_checked)now=true;boolean changed=now!=checked;checked=now;return changed;}
        @Override public void draw(Canvas c){
            Rect b=getBounds();float cx=b.exactCenterX(),cy=b.exactCenterY();p.setStyle(Paint.Style.FILL);
            if(checked){p.setColor(knob);c.drawCircle(cx,cy,b.width()/2f-density,p);float g=b.width()*.58f;c.save();c.translate(cx-g/2,cy-g/2);c.scale(g/24f,g/24f);p.setColor(tick);Glyphs.draw(c,"check",p,3.2f);c.restore();}
            else{p.setColor(dot);c.drawCircle(cx,cy,b.width()*.29f,p);}
        }
        @Override public void setAlpha(int a){p.setAlpha(a);}@Override public void setColorFilter(ColorFilter f){p.setColorFilter(f);}@Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
    }

    // ------------------------------------------------------------------ components
    /** Button with a leading glyph centred together with its label; the elevation drops while disabled. */
    static final class Pill extends Button {
        final AppUi ui;String glyph;int glyphColor,glyphPx,gap;float lift;final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
        Pill(AppUi ui){super(ui.context);this.ui=ui;}
        Pill glyph(String kind,int color,int sizeDp){glyph=kind;glyphColor=color;glyphPx=ui.dp(sizeDp);gap=ui.dp(8);setGravity(Gravity.START|Gravity.CENTER_VERTICAL);setPadding(ui.dp(14)+glyphPx+gap,0,ui.dp(14),0);return this;}
        @Override public void setEnabled(boolean on){super.setEnabled(on);if(lift>0)setElevation(on?lift:0);}
        @Override protected void onDraw(Canvas c){
            if(glyph==null){super.onDraw(c);return;}
            int base=ui.dp(14);float textWidth=getPaint().measureText(getText().toString()),group=glyphPx+gap+textWidth,shift=Math.max(0,(getWidth()-group)/2f-base);
            c.save();c.translate(shift,0);super.onDraw(c);c.translate(base,(getHeight()-glyphPx)/2f);c.scale(glyphPx/24f,glyphPx/24f);paint.setColor(isEnabled()?glyphColor:ui.muted);Glyphs.draw(c,glyph,paint,Glyphs.units(glyphPx,ui.density));c.restore();
        }
    }
    /** Settings row: tinted icon tile, title, optional value and a chevron (hidden for destructive rows). */
    static final class ActionRow extends Button {
        final AppUi ui;final String icon;final boolean danger;final int[] tone;String value;final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
        ActionRow(AppUi ui,String title,String icon,String value,boolean danger,Runnable action){
            super(ui.context);this.ui=ui;this.icon=icon;this.danger=danger;this.value=value==null?"":value;tone=ui.toneColors(danger?"danger":null).clone();
            if(!danger){int[] t=ui.iconTone(icon);tone[0]=t[0];tone[1]=t[1];}
            setStateListAnimator(null);setElevation(0);setAllCaps(false);setText(title);setTextSize(15);setTypeface(face(500));setLetterSpacing(0);setTextColor(danger?ui.danger:ui.text);setIncludeFontPadding(false);setGravity(Gravity.START|Gravity.CENTER_VERTICAL);
            setMinWidth(0);setMinimumWidth(0);setMinHeight(ui.dp(56));setMinimumHeight(ui.dp(56));setBackground(ui.pressable(null,16));setOnClickListener(v->action.run());press(this);pad();
        }
        private void pad(){
            paint.setTextSize(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP,14,getResources().getDisplayMetrics()));
            int end=ui.dp(14)+(danger?0:ui.dp(22))+(value.isEmpty()?0:(int)Math.ceil(paint.measureText(value))+ui.dp(8));
            setPadding(ui.dp(16)+ui.dp(36)+ui.dp(14),ui.dp(8),end,ui.dp(8));
        }
        /** Updates the muted value shown before the chevron. */
        void value(String v){value=v==null?"":v;setContentDescription(value.isEmpty()?null:getText()+", "+value);pad();requestLayout();invalidate();}
        @Override protected void onDraw(Canvas c){
            super.onDraw(c);int h=getHeight(),w=getWidth(),tile=ui.dp(36),left=ui.dp(16);float top=(h-tile)/2f;
            paint.setStyle(Paint.Style.FILL);paint.setColor(tone[1]);c.drawRoundRect(left,top,left+tile,top+tile,ui.dpf(12),ui.dpf(12),paint);
            int g=ui.dp(20);c.save();c.translate(left+(tile-g)/2f,top+(tile-g)/2f);c.scale(g/24f,g/24f);paint.setColor(tone[0]);Glyphs.draw(c,icon,paint,Glyphs.units(g,ui.density));c.restore();
            float right=w-ui.dp(14);
            if(!danger){int cs=ui.dp(18);c.save();c.translate(right-cs,(h-cs)/2f);c.scale(cs/24f,cs/24f);paint.setColor(ui.muted);Glyphs.draw(c,"arrow",paint,Glyphs.units(cs,ui.density));c.restore();right-=cs+ui.dp(4);}
            if(!value.isEmpty()){paint.setStyle(Paint.Style.FILL);paint.setColor(ui.muted);paint.setTypeface(face(400));paint.setTextAlign(Paint.Align.RIGHT);Paint.FontMetrics fm=paint.getFontMetrics();c.drawText(value,right,(h-fm.ascent-fm.descent)/2f,paint);}
        }
    }
    /** Soft semantic chip: tone fill, tone text, leading glyph. */
    static final class StatusChip extends TextView {
        final AppUi ui;final boolean withGlyph;String tone;
        StatusChip(AppUi ui,String value,String tone,boolean withGlyph){
            super(ui.context);this.ui=ui;this.withGlyph=withGlyph;setText(value);setTextSize(12);setTypeface(face(700));setLetterSpacing(.004f);setIncludeFontPadding(false);setGravity(Gravity.CENTER_VERTICAL);setSingleLine(true);
            setPadding(ui.dp(withGlyph?8:11),ui.dp(5),ui.dp(11),ui.dp(5));setCompoundDrawablePadding(ui.dp(5));setMinHeight(ui.dp(26));tone(tone);
        }
        @Override protected void onMeasure(int widthSpec,int heightSpec){
            ViewGroup.LayoutParams lp=getLayoutParams();
            if(lp!=null&&lp.width==ViewGroup.LayoutParams.MATCH_PARENT&&MeasureSpec.getMode(widthSpec)==MeasureSpec.EXACTLY)widthSpec=MeasureSpec.makeMeasureSpec(MeasureSpec.getSize(widthSpec),MeasureSpec.AT_MOST);
            super.onMeasure(widthSpec,heightSpec);
        }
        void tone(String value){
            tone=value;int[] c=ui.toneColors(value);setTextColor(c[0]);setBackground(ui.outline(c[1],14,0,0));
            if(withGlyph){String g="success".equals(value)?"check":"warning".equals(value)?"alert":"danger".equals(value)?"x-circle":"info".equals(value)?"clock":"accent".equals(value)?"sparkle":null;setCompoundDrawablesWithIntrinsicBounds(g==null?null:new GlyphDrawable(g,c[0],ui.dp(14)),null,null,null);}
        }
    }
    /** Soft aurora disc with the glyph and two sparkles for empty states. */
    static final class Illustration extends View {
        final AppUi ui;final String kind;final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
        Illustration(AppUi ui,String kind){super(ui.context);this.ui=ui;this.kind=kind;setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);}
        @Override protected void onDraw(Canvas c){
            float w=getWidth(),h=getHeight(),cx=w/2f,cy=h/2f,d=ui.density,r=Math.min(w,h)*.34f;
            paint.setStyle(Paint.Style.FILL);paint.setShader(new RadialGradient(cx,cy,Math.min(w,h)*.5f,new int[]{alpha(ui.glow,ui.dark?.22f:.34f),alpha(ui.glow,0f)},null,Shader.TileMode.CLAMP));c.drawCircle(cx,cy,Math.min(w,h)*.5f,paint);
            paint.setShader(new LinearGradient(cx-r,cy-r,cx+r,cy+r,new int[]{alpha(ui.aurora[0],ui.dark?.30f:.16f),alpha(ui.aurora[1],ui.dark?.30f:.2f)},null,Shader.TileMode.CLAMP));c.drawCircle(cx,cy,r,paint);paint.setShader(null);
            paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(1.25f*d);paint.setColor(alpha(ui.accent,.32f));c.drawCircle(cx,cy,r,paint);
            float g=r*.95f;c.save();c.translate(cx-g/2,cy-g/2);c.scale(g/24f,g/24f);paint.setColor(ui.accent);Glyphs.draw(c,kind,paint,Glyphs.units(g,d));c.restore();
            paint.setStyle(Paint.Style.FILL);star(c,cx+r*.95f,cy-r*.78f,7*d,alpha(ui.aurora[1],.9f));star(c,cx-r*1.12f,cy+r*.62f,4.5f*d,alpha(ui.glow,.95f));
        }
        private void star(Canvas c,float x,float y,float size,int color){c.save();c.translate(x-size,y-size);c.scale(size/12f,size/12f);paint.setColor(color);Glyphs.draw(c,"star",paint,0f);c.restore();}
    }
    static final class TimelineMark extends View {
        final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);final int color,line,fill;final boolean hollow;
        TimelineMark(Context context,int color,int line){this(context,color,line,false,0);}
        /** Hollow marks draw a ring over the page colour (in progress); filled marks are a solid dot (finished). */
        TimelineMark(Context context,int color,int line,boolean hollow,int fill){super(context);this.color=color;this.line=line;this.hollow=hollow;this.fill=fill;setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);}
        @Override protected void onDraw(Canvas c){
            float d=getResources().getDisplayMetrics().density,x=getWidth()/2f,y=14*d;p.setStyle(Paint.Style.STROKE);p.setStrokeCap(Paint.Cap.ROUND);p.setColor(line);p.setStrokeWidth(2*d);c.drawLine(x,0,x,getHeight(),p);
            if(hollow){p.setStyle(Paint.Style.FILL);p.setColor(fill);c.drawCircle(x,y,6.5f*d,p);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(3.2f*d);p.setColor(color);c.drawCircle(x,y,5f*d,p);}
            else{p.setStyle(Paint.Style.FILL);p.setColor(color);c.drawCircle(x,y,5f*d,p);}
        }
    }
    /** Circular checkbox with ring, fill and tick drawn in sequence on real state changes only. */
    static final class CheckDot extends View {
        final int ring,fill,tick;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);final Path tickPath=new Path(),segment=new Path();float progress;boolean on;ValueAnimator animation;
        CheckDot(AppUi ui){super(ui.context);ring=ui.strokeStrong;fill=ui.accent;tick=ui.onAccent;setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);}
        boolean checked(){return on;}
        void set(boolean value,boolean animate){
            if(animation!=null)animation.cancel();
            if(!animate||!motion()||!isShown()){on=value;progress=value?1:0;invalidate();return;}
            on=value;animation=ValueAnimator.ofFloat(progress,value?1:0);animation.setDuration(180);animation.addUpdateListener(a->{progress=(Float)a.getAnimatedValue();invalidate();});animation.start();
        }
        @Override protected void onDetachedFromWindow(){if(animation!=null)animation.cancel();super.onDetachedFromWindow();}
        @Override protected void onDraw(Canvas c){
            float w=getWidth(),h=getHeight(),d=getResources().getDisplayMetrics().density,r=Math.min(w,h)/2f-1.5f*d,cx=w/2f,cy=h/2f,fillProgress=Math.min(1f,progress*1.3f);
            p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(2*d);p.setColor(ring);p.setAlpha(Math.round(255*(1-fillProgress)));c.drawCircle(cx,cy,r,p);
            if(fillProgress>0){p.setStyle(Paint.Style.FILL);p.setColor(fill);c.drawCircle(cx,cy,(r+d)*fillProgress,p);}
            if(progress>0){tickPath.reset();tickPath.moveTo(cx-r*.42f,cy+r*.02f);tickPath.lineTo(cx-r*.1f,cy+r*.36f);tickPath.lineTo(cx+r*.46f,cy-r*.34f);PathMeasure m=new PathMeasure(tickPath,false);segment.reset();m.getSegment(0,m.getLength()*progress,segment,true);p.setStyle(Paint.Style.STROKE);p.setStrokeCap(Paint.Cap.ROUND);p.setStrokeJoin(Paint.Join.ROUND);p.setStrokeWidth(2.4f*d);p.setColor(tick);c.drawPath(segment,p);}
        }
    }
    /** Text that draws a strike line across itself; the line grows over 220 ms when the state really changes. */
    static final class StrikeText extends TextView {
        final Paint line=new Paint(Paint.ANTI_ALIAS_FLAG);float progress;boolean on;ValueAnimator animation;
        StrikeText(Context context,int color){super(context);line.setColor(color);line.setStyle(Paint.Style.STROKE);line.setStrokeCap(Paint.Cap.ROUND);line.setStrokeWidth(1.6f*context.getResources().getDisplayMetrics().density);}
        void strike(boolean value,boolean animate){
            if(animation!=null)animation.cancel();
            if(!animate||!motion()||!isShown()){on=value;progress=value?1:0;invalidate();return;}
            on=value;animation=ValueAnimator.ofFloat(progress,value?1:0);animation.setDuration(220);animation.setInterpolator(SLIDE);animation.addUpdateListener(a->{progress=(Float)a.getAnimatedValue();invalidate();});animation.start();
        }
        @Override protected void onDetachedFromWindow(){if(animation!=null)animation.cancel();super.onDetachedFromWindow();}
        @Override protected void onDraw(Canvas c){
            super.onDraw(c);Layout layout=getLayout();if(progress<=0||layout==null)return;
            for(int i=0;i<layout.getLineCount();i++){float y=getCompoundPaddingTop()+layout.getLineBaseline(i)-getTextSize()*.3f,x=getCompoundPaddingLeft()+layout.getLineLeft(i);c.drawLine(x,y,x+(layout.getLineRight(i)-layout.getLineLeft(i))*progress,y,line);}
        }
    }
    static final class Meter extends View {
        final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);final int color,idle;final int[] stops;float amplitude;boolean active;ValueAnimator transition;
        /** Aurora bars run from the given colour to orchid. */
        Meter(Context context,int color){super(context);this.color=color;idle=alpha(color,.45f);stops=new int[]{color,Color.red(color)+Color.green(color)+Color.blue(color)>380?0xFFC46CF0:0xFFA23BC6};setContentDescription("Microphone level");}
        Meter(Context context,AppUi ui){super(context);color=ui.aurora[0];idle=ui.muted;stops=new int[]{ui.aurora[0],ui.aurora[1]};setContentDescription("Microphone level");}
        /** Attack 60 ms, release 220 ms, only when a new real level arrives. */
        void value(float level,boolean on){
            active=on;if(transition!=null)transition.cancel();float target=on?level:0;
            if(isShown()&&motion()&&Math.abs(amplitude-target)>.01f){transition=ValueAnimator.ofFloat(amplitude,target);transition.setDuration(target>amplitude?60:220);transition.addUpdateListener(animation->{amplitude=(Float)animation.getAnimatedValue();invalidate();});transition.start();}
            else{amplitude=target;invalidate();}
        }
        @Override protected void onSizeChanged(int w,int h,int ow,int oh){paint.setShader(new LinearGradient(0,0,Math.max(1,w),0,stops,null,Shader.TileMode.CLAMP));}
        @Override protected void onDetachedFromWindow(){if(transition!=null)transition.cancel();super.onDetachedFromWindow();}
        @Override protected void onDraw(Canvas c){
            super.onDraw(c);float d=getResources().getDisplayMetrics().density;
            if(!active||amplitude<=.02f){paint.setShader(null);paint.setColor(idle);float y=getHeight()/2f,t=1.5f*d;c.drawRoundRect(getWidth()*.2f,y-t,getWidth()*.8f,y+t,t,t,paint);paint.setShader(new LinearGradient(0,0,Math.max(1,getWidth()),0,stops,null,Shader.TileMode.CLAMP));return;}
            paint.setColor(0xFF000000);int count=23;float gap=getWidth()/(float)count,width=Math.max(2*d,gap*.46f);
            for(int i=0;i<count;i++){float taper=.25f+.75f*(float)Math.sin(Math.PI*(i+1)/(count+1)),height=Math.max(5*d,getHeight()*.9f*amplitude*taper);c.drawRoundRect(i*gap+(gap-width)/2,(getHeight()-height)/2,i*gap+(gap+width)/2,(getHeight()+height)/2,width/2,width/2,paint);}
        }
    }

    /** Floating pill navigation with an aurora indicator that slides under the selected item. */
    static final class NavBar extends FrameLayout {
        final AppUi ui;final LinearLayout row;final View[] items;final Icon[] glyphs;final TextView[] names;final Aurora pill;final IntConsumer pick;
        int selected=-1;float pillX,pillW;ValueAnimator slide,tint;
        NavBar(AppUi ui,String[] labels,String[] icons,String[] tags,IntConsumer pick){
            super(ui.context);this.ui=ui;this.pick=pick;int n=labels.length;items=new View[n];glyphs=new Icon[n];names=new TextView[n];
            pill=new Aurora(new int[]{ui.aurora[0],ui.aurora[1]},120,-1,ui.dpf(1));setBackground(ui.cardFace(28));ui.lift(this,28,10,true);setMinimumHeight(ui.dp(64));setClipChildren(false);
            row=ui.row();row.setPadding(ui.dp(6),0,ui.dp(6),0);addView(row,new FrameLayout.LayoutParams(-1,-1));
            for(int i=0;i<n;i++){
                final int index=i;LinearLayout item=ui.column();item.setGravity(Gravity.CENTER);item.setPadding(ui.dp(4),ui.dp(8),ui.dp(4),ui.dp(8));
                glyphs[i]=new Icon(ui.context,icons[i],ui.muted);item.addView(glyphs[i],new LinearLayout.LayoutParams(ui.dp(22),ui.dp(22)));
                names[i]=ui.type(labels[i],11.5f,0,500,.004f,ui.muted);names[i].setSingleLine(true);names[i].setEllipsize(TextUtils.TruncateAt.END);names[i].setGravity(Gravity.CENTER_HORIZONTAL);LinearLayout.LayoutParams np=new LinearLayout.LayoutParams(-2,-2);np.topMargin=ui.dp(3);item.addView(names[i],np);
                item.setTag(tags[i]);item.setContentDescription(labels[i]);item.setClickable(true);item.setFocusable(true);item.setOnClickListener(v->{select(index,true);if(pick!=null)pick.accept(index);});press(item);items[i]=item;row.addView(item,new LinearLayout.LayoutParams(0,-1,1));
            }
        }
        /** Margins for a floating bar: 8 dp at the sides, clear of the gesture area below. */
        LinearLayout.LayoutParams params(){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.leftMargin=p.rightMargin=ui.dp(8);p.topMargin=ui.dp(4);p.bottomMargin=ui.dp(12);return p;}
        int selected(){return selected;}
        private float left(int i){return row.getLeft()+items[i].getLeft()+ui.dpf(4);}
        private float width(int i){return items[i].getWidth()-ui.dpf(8);}
        void select(int index,boolean animate){
            if(index<0||index>=items.length||(index==selected&&pillW>0))return;int old=selected;selected=index;for(int i=0;i<items.length;i++)items[i].setSelected(i==index);
            if(tint!=null)tint.cancel();
            if(old!=index&&animate&&motion()&&isShown()){final int from=old;tint=ValueAnimator.ofFloat(0,1);tint.setDuration(200);tint.addUpdateListener(a->{float f=a.getAnimatedFraction();if(from>=0)color(from,AppUi.mix(ui.onAccent,ui.muted,f));color(index,AppUi.mix(ui.muted,ui.onAccent,f));});tint.start();}
            else for(int i=0;i<items.length;i++)color(i,i==index?ui.onAccent:ui.muted);
            if(row.getWidth()==0)return;
            float tx=left(index),tw=width(index);if(slide!=null)slide.cancel();
            if(old>=0&&old!=index&&animate&&motion()&&isShown()){final float x0=pillX,w0=pillW;slide=ValueAnimator.ofFloat(0,1);slide.setDuration(260);slide.setInterpolator(SLIDE);slide.addUpdateListener(a->{float f=a.getAnimatedFraction();pillX=x0+(tx-x0)*f;pillW=w0+(tw-w0)*f;invalidate();});slide.start();}
            else{pillX=tx;pillW=tw;invalidate();}
        }
        private void color(int i,int value){glyphs[i].color(value);names[i].setTextColor(value);names[i].setTypeface(face(value==ui.muted?500:700));}
        @Override protected void onLayout(boolean changed,int l,int t,int r,int b){super.onLayout(changed,l,t,r,b);if(selected>=0&&(slide==null||!slide.isRunning())){pillX=left(selected);pillW=width(selected);}}
        @Override protected void onDetachedFromWindow(){if(slide!=null)slide.cancel();if(tint!=null)tint.cancel();super.onDetachedFromWindow();}
        @Override protected void dispatchDraw(Canvas c){
            if(selected>=0&&pillW>0){int inset=ui.dp(6);pill.setBounds(0,inset,Math.round(pillW),getHeight()-inset);c.save();c.translate(pillX,0);pill.draw(c);c.restore();}
            super.dispatchDraw(c);
        }
    }

    /**
     * The aurora orb. Idle is static; level() follows the real microphone level only when a new value arrives
     * (attack 60 ms, release 220 ms) and state() crossfades colour and glyph in 180 ms on change.
     * States: idle, listening, working, conversation, attention, offline. Size the view roughly 240 to 300 dp square.
     */
    static final class VoiceButton extends Button {
        final AppUi ui;final Paint halo=paint(),l1=paint(),l2=paint(),l3=paint(),glow=paint(),core=paint(),sheen=paint(),rose=paint(),ring=paint(),mark=paint(),label=paint();
        String state="idle",fromGlyph="voice",toGlyph="voice";boolean fromLabel=true,toLabel=true,live;int[] from,to;float blend=1,shown;ValueAnimator stateAnim,levelAnim;
        VoiceButton(Context context,AppUi ui){
            super(context);this.ui=ui;setText("Talk");setContentDescription("Talk");setAllCaps(false);setStateListAnimator(null);setElevation(0);setPadding(0,0,0,0);setBackgroundColor(Color.TRANSPARENT);setMinWidth(0);setMinimumWidth(0);setMinHeight(0);setMinimumHeight(0);
            to=from=palette("idle");label.setTypeface(face(700));label.setTextAlign(Paint.Align.CENTER);label.setLetterSpacing(.015f);build();
        }
        private static Paint paint(){return new Paint(Paint.ANTI_ALIAS_FLAG);}
        private int[] palette(String s){
            if(s.equals("attention"))return ui.dark?new int[]{ui.warning,mix(ui.warning,ui.danger,.5f),ui.danger,ui.warning}:new int[]{0xFFB86500,0xFFCF4A27,0xFFC02A4B,0xFFE08A1E};
            if(s.equals("offline")){int m=ui.dark?mix(ui.muted,ui.background,.3f):ui.muted;return new int[]{m,mix(m,ui.aurora[0],.3f),mix(m,ui.aurora[1],.35f),m};}
            return new int[]{ui.aurora[0],ui.aurora[1],ui.aurora[2],ui.glow};
        }
        private String glyphFor(String s){return s.equals("listening")?"bars":s.equals("conversation")?"chat":s.equals("working")?"sparkle":s.equals("attention")?"alert":s.equals("offline")?"cloud-off":"voice";}
        private boolean labelFor(String s){return s.equals("idle")||s.equals("attention")||s.equals("offline");}
        /** Colours and shaders live in unit space (disc radius 1) so drawing is size independent. */
        private void build(){
            int[] p=new int[4];for(int i=0;i<4;i++)p[i]=mix(from[i],to[i],blend);
            halo.setShader(new RadialGradient(0,0,1,new int[]{p[3],alpha(p[0],.5f),alpha(p[0],0f)},new float[]{0,.55f,1},Shader.TileMode.CLAMP));
            l1.setShader(diag(135,p[3],p[0]));l2.setShader(diag(200,p[1],p[0]));l3.setShader(diag(320,p[2],p[1]));
            glow.setShader(new RadialGradient(0,.35f,1.55f,new int[]{alpha(p[1],.42f),alpha(p[1],0f)},new float[]{.5f,1},Shader.TileMode.CLAMP));
            core.setShader(diag(150,p[0],p[1],p[2]));
            RadialGradient s=new RadialGradient(-.36f,-.62f,.92f,0x57FFFFFF,0x00FFFFFF,Shader.TileMode.CLAMP);Matrix m=new Matrix();m.setScale(1f,.74f,-.36f,-.62f);s.setLocalMatrix(m);sheen.setShader(s);
            rose.setShader(new RadialGradient(0,1f,1f,alpha(p[2],.34f),alpha(p[2],0f),Shader.TileMode.CLAMP));
            ring.setStyle(Paint.Style.STROKE);ring.setColor(0x5CFFFFFF);
        }
        private static Shader diag(float angle,int... colors){double a=Math.toRadians(angle);float dx=(float)Math.sin(a),dy=-(float)Math.cos(a);return new LinearGradient(-dx,-dy,dx,dy,colors,colors.length==3?new float[]{0,.62f,1}:null,Shader.TileMode.CLAMP);}
        void state(String value){
            if(value==null)value="idle";if(value.equals(state))return;
            int[] now=new int[4];for(int i=0;i<4;i++)now[i]=mix(from[i],to[i],blend);String nowGlyph=blend<.5f?fromGlyph:toGlyph;boolean nowLabel=blend<.5f?fromLabel:toLabel;
            state=value;from=now;fromGlyph=nowGlyph;fromLabel=nowLabel;to=palette(value);toGlyph=glyphFor(value);toLabel=labelFor(value);if(stateAnim!=null)stateAnim.cancel();
            if(Build.VERSION.SDK_INT>=30)setStateDescription(value.equals("idle")?null:value);
            if(isShown()&&motion()){blend=0;stateAnim=ValueAnimator.ofFloat(0,1);stateAnim.setDuration(180);stateAnim.addUpdateListener(a->{blend=(Float)a.getAnimatedValue();build();invalidate();});stateAnim.start();}
            else{blend=1;from=to;fromGlyph=toGlyph;fromLabel=toLabel;build();invalidate();}
        }
        /** Halo alpha is about .28 plus .25 of the level; layers scale by 1 plus .76, .5 and .25 of the level. */
        void level(float value,boolean on){
            live=on;float target=on?Math.max(0,Math.min(1,value)):0;if(levelAnim!=null)levelAnim.cancel();
            if(!motion()){shown=Math.round(target*4)/4f;invalidate();return;}
            if(!isShown()||Math.abs(target-shown)<.004f){shown=target;invalidate();return;}
            levelAnim=ValueAnimator.ofFloat(shown,target);levelAnim.setDuration(target>shown?60:220);levelAnim.addUpdateListener(a->{shown=(Float)a.getAnimatedValue();invalidate();});levelAnim.start();
        }
        @Override public boolean onTouchEvent(MotionEvent event){
            int a=event.getActionMasked();if(a==MotionEvent.ACTION_DOWN&&motion())animate().scaleX(.97f).scaleY(.97f).setDuration(90).start();
            else if(a==MotionEvent.ACTION_UP||a==MotionEvent.ACTION_CANCEL){if(motion())animate().scaleX(1f).scaleY(1f).setDuration(160).start();else{setScaleX(1f);setScaleY(1f);}}
            return super.onTouchEvent(event);
        }
        @Override protected void onDetachedFromWindow(){if(stateAnim!=null)stateAnim.cancel();if(levelAnim!=null)levelAnim.cancel();super.onDetachedFromWindow();}
        @Override protected void onDraw(Canvas c){
            float w=getWidth(),h=getHeight(),u=Math.min(w,h)/2f;if(u<=0)return;float cx=w/2f,cy=h/2f,level=shown,dim=ui.dark?.62f:1f,d=ui.density;
            halo.setAlpha(Math.round(255*Math.min(1f,(live?.28f+.25f*level:.2f)*(ui.dark?.75f:1f))));c.save();c.translate(cx,cy);c.scale(u*.99f,u*.99f);c.drawCircle(0,0,1f,halo);c.restore();
            float[] base={.60f,.565f,.53f},k={.76f,.5f,.25f},ox={-.015f,.02f,0f},oy={-.015f,.007f,.027f},alphas={.55f,.5f,.5f};Paint[] layers={l1,l2,l3};
            for(int i=0;i<3;i++){float r=Math.min(.98f,base[i]*(1+k[i]*level))*u;layers[i].setAlpha(Math.round(255*alphas[i]*dim));c.save();c.translate(cx+ox[i]*u,cy+oy[i]*u);c.scale(r,r);c.drawCircle(0,0,1f,layers[i]);c.restore();}
            ring.setStrokeWidth(1.5f*d/(u*.7f));ring.setColor(alpha(to[1],(.26f-.14f*level)*(ui.dark?.8f:1f)));c.save();c.translate(cx,cy);float rr=Math.min(.98f,.71f*(1+.34f*level))*u;c.scale(rr,rr);c.drawCircle(0,0,1f,ring);c.restore();
            float coreR=.44f*u;c.save();c.translate(cx,cy);c.scale(coreR,coreR);glow.setAlpha(Math.round(255*(ui.dark?.6f:1f)));c.drawCircle(0,.35f,1.55f,glow);c.drawCircle(0,0,1f,core);c.drawCircle(0,0,1f,rose);c.drawCircle(0,0,1f,sheen);
            ring.setColor(0x5CFFFFFF);ring.setStrokeWidth(1.5f*d/coreR);c.drawCircle(0,0,1f-.75f*d/coreR,ring);if(isPressed()){core.setAlpha(255);Paint tint=paint();tint.setColor(0x1FFFFFFF);c.drawCircle(0,0,1f,tint);}c.restore();
            if(blend<1)glyph(c,cx,cy,coreR,fromGlyph,fromLabel,1f-blend);glyph(c,cx,cy,coreR,toGlyph,toLabel,blend);
        }
        private void glyph(Canvas c,float cx,float cy,float coreR,String kind,boolean withLabel,float fade){
            if(fade<=0)return;int color=ui.onAccent;float size=withLabel?coreR*.62f:coreR*.8f,gy=withLabel?cy-coreR*.17f:cy;mark.setColor(color);mark.setAlpha(Math.round(255*fade));
            c.save();c.translate(cx-size/2,gy-size/2);c.scale(size/24f,size/24f);
            if(kind.equals("bars")){mark.setStyle(Paint.Style.STROKE);mark.setStrokeCap(Paint.Cap.ROUND);mark.setStrokeWidth(2.6f);float[] shape={.38f,.7f,1f,.7f,.38f};for(int i=0;i<5;i++){float x=4+i*4f,half=Math.max(1.2f,10f*shape[i]*(.4f+.6f*shown));c.drawLine(x,12-half,x,12+half,mark);}}
            else Glyphs.draw(c,kind,mark,2f);
            c.restore();
            if(withLabel){label.setColor(color);label.setAlpha(Math.round(255*fade));label.setTextSize(coreR*.31f);c.drawText("Talk",cx,cy+coreR*.54f,label);}
        }
    }
}
