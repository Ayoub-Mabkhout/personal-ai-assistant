package com.personalassistant.companion;

import android.app.Dialog;
import android.content.Context;
import android.graphics.*;
import android.graphics.drawable.Drawable;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.util.*;

/** Drawn pieces of Train: tier crests, the ridge of camps, the muscle map, simple line charts and the shared full-height sheet. */
final class WorkoutViews {
    private WorkoutViews(){}
    static final String[] TIERS={"Iron","Bronze","Silver","Gold","Platinum","Emerald","Diamond","Master","Grandmaster","Challenger"};
    static final int[] FLOORS={0,200,300,400,500,600,700,800,900,950};
    private static final int FIRST_APEX=7;
    private static final int[][] COLORS={{0xFFA6ABB4,0xFF565B64,0xFFDADDE2},{0xFFD98A4E,0xFF7E4318,0xFFF6C196},{0xFFC9D3E6,0xFF6F7C96,0xFFFFFFFF},{0xFFFFC233,0xFFB96D08,0xFFFFEC9C},{0xFF7DE3FF,0xFF2A7FB8,0xFFE2FAFF},{0xFF3FD58F,0xFF137A52,0xFFC4F7DE},{0xFF5B9BFF,0xFF2A3FC4,0xFFBFE0FF},{0xFFB66DFF,0xFF5A1FB8,0xFFE7CCFF},{0xFFFF5F7E,0xFFA81A3E,0xFFFFC4D2},{0xFFFFE27A,0xFFE0562E,0xFFFFFFFF}};
    /** The rank in a name such as Gold 2. */
    static int tier(String name){for(int i=0;i<TIERS.length;i++)if(name.equalsIgnoreCase(TIERS[i])||name.toLowerCase(Locale.ROOT).startsWith(TIERS[i].toLowerCase(Locale.ROOT)+" "))return i;return 0;}
    /** Rank and division, which climb from 4 to 1; the apex ranks have no divisions. */
    static String label(int score){int t=tierOf(score);if(t>=FIRST_APEX)return TIERS[t];return TIERS[t]+" "+(4-(score-FLOORS[t])*4/(FLOORS[t+1]-FLOORS[t]));}
    static int tierOf(int score){int t=0;for(int i=0;i<FLOORS.length;i++)if(score>=FLOORS[i])t=i;return t;}
    static int color(int tier,boolean dark){return dark||tier!=2?COLORS[tier][tier==3&&!dark?1:0]:COLORS[tier][1];}
    /** Tier colour for text on the page: the deep shade in light mode so pale tiers stay readable. */
    static int ink(int tier,boolean dark){return COLORS[tier][dark?0:1];}
    /** The tier's bright face, for marks on the dark hero and ridge backgrounds. */
    static int bright(int tier){return COLORS[tier][0];}

    /** A ten-step heraldic crest on a 120×134 grid: a shield gains a crown, then wings, a star and a second pair of wings. */
    static final class Crest extends View {
        final int[] c;final boolean locked;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);final int tier;
        Crest(Context context,int tier,boolean locked){super(context);this.tier=tier;this.locked=locked;c=COLORS[tier];setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);}
        private void poly(Canvas k,int color,float... v){Path a=new Path();a.moveTo(v[0],v[1]);for(int i=2;i<v.length;i+=2)a.lineTo(v[i],v[i+1]);a.close();p.setColor(locked?gray(color):color);k.drawPath(a,p);}
        private int gray(int color){int y=(Color.red(color)*3+Color.green(color)*6+Color.blue(color))/10/2+40;return Color.rgb(y,y,y+8);}
        @Override protected void onDraw(Canvas k){float s=Math.min(getWidth()/120f,getHeight()/134f);k.save();k.translate((getWidth()-120*s)/2,(getHeight()-134*s)/2+4*s);k.scale(s,s);
            if(tier>=6){poly(k,c[0],2,26,24,20,24,44,8,50);poly(k,c[0],118,26,96,20,96,44,112,50);}
            if(tier>=3){poly(k,c[1],10,44,26,30,26,74,14,66);poly(k,c[1],110,44,94,30,94,74,106,66);}
            if(tier>=2)poly(k,c[2],44,16,50,4,60,12,70,4,76,16);
            poly(k,c[1],60,14,96,28,92,84,60,122,28,84,24,28);poly(k,c[0],60,14,96,28,92,84,60,122);poly(k,0x47120A24,60,24,86,34,83,80,60,108,37,80,34,34);
            if(tier>=4)poly(k,c[2],60,40,65,54,80,55,68,64,72,79,60,70,48,79,52,64,40,55,55,54);else poly(k,c[2],60,44,74,60,60,76,46,60);k.restore();}
    }

    /** The ten camps up a dusk ridge; camps above the current rank are dimmed. A rival's view also pins your own camp with a "You" pill. */
    static final class Ridge extends View {
        static final float[][] CAMPS={{.06f,.86f},{.15f,.74f},{.24f,.76f},{.34f,.66f},{.43f,.58f},{.53f,.64f},{.63f,.42f},{.71f,.48f},{.81f,.28f},{.91f,.14f}};
        final AppUi ui;final int current,you;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);final Bitmap[] marks=new Bitmap[CAMPS.length];
        Ridge(AppUi ui,int current){this(ui,current,-1);}
        Ridge(AppUi ui,int current,int you){super(ui.context);this.ui=ui;this.current=current;this.you=you;}
        private void hill(Canvas c,int color,float... v){Path a=new Path();a.moveTo(0,getHeight());for(int i=0;i<v.length;i+=2)a.lineTo(v[i]*getWidth(),v[i+1]*getHeight());a.lineTo(getWidth(),getHeight());a.close();p.setColor(color);p.setShader(null);c.drawPath(a,p);}
        @Override protected void onDraw(Canvas c){int w=getWidth(),h=getHeight();p.setShader(new LinearGradient(0,0,0,h,new int[]{0xFF1A1248,0xFF5A2A9A,0xFFC95F8E},new float[]{0,.65f,1},Shader.TileMode.CLAMP));c.drawRect(0,0,w,h,p);p.setShader(null);
            hill(c,0xFF2A1460,0,.9f,.2f,.68f,.3f,.76f,.43f,.54f,.53f,.62f,.63f,.38f,.71f,.46f,.91f,.08f,1,.24f);hill(c,ui.dark?ui.background:0xFF1D1729,0,.98f,.3f,.88f,.6f,.94f,1,.78f);
            for(int i=0;i<CAMPS.length;i++){boolean here=i==current;int cw=ui.dp(here?36:20),ch=ui.dp(here?40:23);if(marks[i]==null){Crest crest=new Crest(getContext(),i,i>current&&i>you);crest.layout(0,0,cw,ch);Bitmap b=Bitmap.createBitmap(cw,ch,Bitmap.Config.ARGB_8888);crest.draw(new Canvas(b));marks[i]=b;}c.drawBitmap(marks[i],CAMPS[i][0]*w-cw/2f,CAMPS[i][1]*h-ch/2f,null);}
            if(you>=0&&you<CAMPS.length)pin(c,w,h);}
        /** White "You" pill with a pointer, beside the camp when it is also the rival's, kept inside the card. */
        private void pin(Canvas c,int w,int h){boolean shared=you==current;float pw=ui.dpf(34),ph=ui.dpf(17);
            float cx=Math.max(pw/2+ui.dpf(2),Math.min(w-pw/2-ui.dpf(2),CAMPS[you][0]*w+(shared?ui.dpf(26):0))),cy=Math.max(ph+ui.dpf(4),CAMPS[you][1]*h-ui.dpf(shared?24:14));
            p.setShader(null);p.setColor(Color.WHITE);c.drawRoundRect(new RectF(cx-pw/2,cy-ph-ui.dpf(2),cx+pw/2,cy-ui.dpf(2)),ph/2,ph/2,p);
            Path tip=new Path();tip.moveTo(cx-ui.dpf(4),cy-ui.dpf(2.5f));tip.lineTo(cx+ui.dpf(4),cy-ui.dpf(2.5f));tip.lineTo(cx,cy+ui.dpf(3));tip.close();c.drawPath(tip,p);
            p.setColor(0xFF3A2470);p.setTypeface(AppUi.face(800));p.setTextSize(ui.dpf(10));p.setTextAlign(Paint.Align.CENTER);Paint.FontMetrics m=p.getFontMetrics();c.drawText("You",cx,cy-ui.dpf(2)-ph/2-(m.ascent+m.descent)/2,p);p.setTextAlign(Paint.Align.LEFT);p.setTypeface(null);}
    }

    /** A geometric figure whose regions take the tier colour of each trained muscle group. */
    static final class BodyMap extends View {
        static final Object[][] REGIONS={{"shoulder",14f,26f,25f,26f,22f,44f,11f,42f},{"shoulder",71f,26f,82f,26f,85f,42f,74f,44f},{"chest",26f,26f,46f,26f,46f,44f,24f,42f},{"chest",50f,26f,70f,26f,72f,42f,50f,44f},{"arm",11f,45f,22f,46f,19f,70f,8f,68f},{"arm",74f,46f,85f,45f,88f,68f,77f,70f},{"back",30f,46f,46f,47f,46f,76f,33f,76f},{"back",50f,47f,66f,46f,63f,76f,50f,76f},{"leg",30f,79f,47f,79f,45f,118f,32f,118f},{"leg",49f,79f,66f,79f,64f,118f,51f,118f},{"calf",33f,121f,44f,121f,43f,146f,35f,146f},{"calf",52f,121f,63f,121f,61f,146f,53f,146f}};
        final AppUi ui;final JSONObject scores;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);
        BodyMap(AppUi ui,JSONObject scores){super(ui.context);this.ui=ui;this.scores=scores==null?new JSONObject():scores;setContentDescription("Muscle ranks on a body map");}
        private int score(String region){String[][] words={{"shoulder","delt"},{"chest","pec"},{"arm","bicep","tricep","forearm"},{"back","lat","trap","erector","core","ab"},{"leg","quad","hamstring","glute","thigh"},{"calf","calves"}};int best=-1;for(String[] w:words)if(w[0].equals(region))for(Iterator<String> i=scores.keys();i.hasNext();){String k=i.next();String lower=k.toLowerCase(Locale.ROOT);for(String x:w)if(lower.contains(x))best=Math.max(best,scores.optInt(k));}return best;}
        @Override protected void onDraw(Canvas c){float s=Math.min(getWidth()/96f,getHeight()/150f);c.save();c.translate((getWidth()-96*s)/2,0);c.scale(s,s);p.setColor(ui.strokeStrong);c.drawCircle(48,12,9,p);
            for(Object[] r:REGIONS){int v=score((String)r[0]);p.setColor(v<0?ui.stroke:COLORS[tierOf(v)][0]);Path a=new Path();a.moveTo((float)r[1],(float)r[2]);for(int i=3;i<r.length;i+=2)a.lineTo((float)r[i],(float)r[i+1]);a.close();c.drawPath(a,p);}c.restore();}
    }

    /** A row that slides under the finger: left past a third deletes, right past a quarter completes. Vertical scrolling and taps pass through. */
    static final class SwipeRow extends LinearLayout {
        final Runnable remove,complete;final int slop;float startX,startY;boolean dragging;
        SwipeRow(AppUi ui,Runnable remove){this(ui,remove,null);}
        SwipeRow(AppUi ui,Runnable remove,Runnable complete){super(ui.context);this.remove=remove;this.complete=complete;slop=android.view.ViewConfiguration.get(ui.context).getScaledTouchSlop()*2;}
        @Override public boolean onInterceptTouchEvent(MotionEvent e){if(e.getAction()==MotionEvent.ACTION_DOWN){startX=e.getRawX();startY=e.getRawY();dragging=false;}else if(e.getAction()==MotionEvent.ACTION_MOVE){float dx=e.getRawX()-startX;if((dx<-slop||complete!=null&&dx>slop)&&Math.abs(e.getRawY()-startY)<slop){dragging=true;getParent().requestDisallowInterceptTouchEvent(true);return true;}}return false;}
        @Override public boolean onTouchEvent(MotionEvent e){if(!dragging)return e.getAction()==MotionEvent.ACTION_DOWN;if(e.getAction()==MotionEvent.ACTION_MOVE){float dx=e.getRawX()-startX;setTranslationX(complete==null?Math.min(0,dx):dx);setAlpha(1-Math.abs(getTranslationX())/getWidth());}else if(e.getAction()==MotionEvent.ACTION_UP||e.getAction()==MotionEvent.ACTION_CANCEL){dragging=false;float x=getTranslationX();if(e.getAction()==MotionEvent.ACTION_UP&&-x>getWidth()/3f){performHapticFeedback(HapticFeedbackConstants.CONFIRM);remove.run();}else if(e.getAction()==MotionEvent.ACTION_UP&&complete!=null&&x>getWidth()/4f){performHapticFeedback(HapticFeedbackConstants.CONFIRM);setTranslationX(0);setAlpha(1);complete.run();}else animate().translationX(0).alpha(1).setDuration(160).start();}return true;}
    }

    /** Minus and plus around a value; holding either keeps it moving. */
    static final class Stepper extends LinearLayout {
        final AppUi ui;double value;final double step,min;final java.util.function.DoubleFunction<String> shown;final TextView label;Runnable changed;Runnable repeat;
        Stepper(AppUi ui,double value,double step,double min,java.util.function.DoubleFunction<String> shown){super(ui.context);this.ui=ui;this.value=value;this.step=step;this.min=min;this.shown=shown;setOrientation(HORIZONTAL);setGravity(Gravity.CENTER_VERTICAL);label=ui.type(shown.apply(value),20,26,800,0,ui.text);label.setGravity(Gravity.CENTER);addView(button("minus","Less",-1),new LayoutParams(ui.dp(48),ui.dp(48)));addView(label,new LayoutParams(0,-2,1));addView(button("plus","More",1),new LayoutParams(ui.dp(48),ui.dp(48)));}
        private void nudge(int way){value=Math.max(min,Math.round((value+way*step)/step)*step);label.setText(shown.apply(value));if(changed!=null)changed.run();}
        private View button(String icon,String name,int way){ImageButton b=ui.iconButton(icon,name,ui.accent,()->{});b.setOnClickListener(null);b.setOnTouchListener((v,e)->{if(e.getActionMasked()==MotionEvent.ACTION_DOWN){nudge(way);v.setPressed(true);repeat=new Runnable(){public void run(){nudge(way);v.postDelayed(this,70);}};v.postDelayed(repeat,380);}else if(e.getActionMasked()==MotionEvent.ACTION_UP||e.getActionMasked()==MotionEvent.ACTION_CANCEL){v.setPressed(false);v.removeCallbacks(repeat);}return true;});return b;}
    }

    /** Full-height sheet with a back control. */
    static final class Sheet {
        final AppUi ui;final Dialog dialog;final LinearLayout root,body,bar;final ScrollView scroll;
        Sheet(AppUi ui,String heading){this.ui=ui;dialog=ui.sheet();root=ui.column();root.setBackgroundColor(ui.background);root.setFitsSystemWindows(true);bar=ui.row();bar.setPadding(ui.dp(8),ui.dp(8),ui.dp(12),ui.dp(4));bar.addView(ui.iconButton("back","Back",dialog::dismiss),new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));TextView h=ui.type(heading,20,26,700,0,ui.text);h.setMaxLines(2);bar.addView(h,MainParts.weighted(ui,1,4,0,0,0));root.addView(bar);
            scroll=new ScrollView(ui.context);body=ui.column();body.setPadding(ui.dp(16),ui.dp(8),ui.dp(16),ui.dp(28));scroll.addView(body);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));dialog.setContentView(root);}
        Sheet show(){dialog.show();Window w=dialog.getWindow();if(w!=null)w.setLayout(-1,-1);return this;}
    }
    static int setColor(AppUi ui,String kind){switch(kind){case "warmup":return ui.hue(AppUi.ORANGE);case "drop":return ui.hue(AppUi.BLUE);case "failure":return ui.hue(AppUi.RED);default:return ui.text;}}
    static String setMark(String kind,int number){switch(kind){case "warmup":return "W";case "drop":return "D";case "failure":return "F";default:return String.valueOf(number);}}
    /** A working set shows its number; warm-up, drop and failure sets show a coloured letter. */
    static TextView setTag(AppUi ui,String kind,int number){int color=setColor(ui,kind);TextView t=ui.type(setMark(kind,number),14,20,800,0,color);t.setGravity(Gravity.CENTER);t.setBackground(ui.outline("working".equals(kind)?0:AppUi.alpha(color,.18f),10,0,0));t.setContentDescription(("warmup".equals(kind)?"Warm-up":"drop".equals(kind)?"Drop":"failure".equals(kind)?"Failure":"Working")+" set. Tap to change type");return t;}
    static View stat(AppUi ui,String value,String label){LinearLayout c=ui.column();c.setGravity(Gravity.CENTER);c.addView(ui.type(value,18,24,800,0,ui.text));c.addView(ui.type(label,11.5f,16,500,0,ui.muted));return c;}
    static LinearLayout card(AppUi ui){LinearLayout box=ui.column();box.setPadding(ui.dp(14),ui.dp(12),ui.dp(14),ui.dp(12));box.setBackground(ui.outline(ui.surface,18,ui.stroke,1));return box;}
    static LinearLayout.LayoutParams gap(AppUi ui,int bottom){return MainParts.params(ui,-1,-2,0,0,0,bottom);}
    static View pair(AppUi ui,String left,String right,int rightColor){LinearLayout r=ui.row();r.addView(ui.type(left,14,20,400,0,ui.text),new LinearLayout.LayoutParams(0,-2,1));r.addView(ui.type(right,14,20,600,0,rightColor));r.setPadding(0,ui.dp(3),0,ui.dp(3));return r;}
    static String kg(double v){return v==Math.rint(v)?String.valueOf((long)v):String.format(Locale.ROOT,"%.1f",v);}
    static String clock(long seconds){seconds=Math.max(0,seconds);long h=seconds/3600,m=seconds/60%60,s=seconds%60;return h>0?String.format(Locale.ROOT,"%d:%02d:%02d",h,m,s):String.format(Locale.ROOT,"%d:%02d",m,s);}
    static View row(AppUi ui,String title,String note,Runnable action){LinearLayout r=ui.row();r.setMinimumHeight(ui.dp(56));r.setPadding(ui.dp(14),ui.dp(8),ui.dp(10),ui.dp(8));r.setBackground(ui.pressable(ui.outline(ui.surface,16,ui.stroke,1),16));LinearLayout w=ui.column();w.addView(ui.type(title,15,20,600,0,ui.text));if(note!=null&&!note.isEmpty())w.addView(ui.type(note,12.5f,17,400,0,ui.muted));r.addView(w,new LinearLayout.LayoutParams(0,-2,1));r.addView(MainParts.icon(ui,"arrow",ui.muted),new LinearLayout.LayoutParams(ui.dp(18),ui.dp(18)));r.setOnClickListener(v->action.run());AppUi.press(r);return r;}
}
