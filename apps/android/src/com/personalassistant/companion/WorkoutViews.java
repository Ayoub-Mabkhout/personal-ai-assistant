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
    static final String[] TIERS={"Wood","Bronze","Silver","Gold","Platinum","Diamond","Champion","Titan","Olympian"};
    static final int[] FLOORS={0,200,300,400,500,600,700,800,900};
    private static final int[][] COLORS={{0xFFB98552,0xFF6B4326,0xFFE0B98C},{0xFFD98A4E,0xFF7E4318,0xFFF6C196},{0xFFC9D3E6,0xFF6F7C96,0xFFFFFFFF},{0xFFFFC233,0xFFB96D08,0xFFFFEC9C},{0xFF7DE3FF,0xFF2A7FB8,0xFFE2FAFF},{0xFF5B9BFF,0xFF2A3FC4,0xFFBFE0FF},{0xFFFF5FA2,0xFFA81A5E,0xFFFFC4DE},{0xFFB66DFF,0xFF5A1FB8,0xFFE7CCFF},{0xFFFFE27A,0xFFE0562E,0xFFFFFFFF}};
    static int tier(String name){for(int i=0;i<TIERS.length;i++)if(TIERS[i].equalsIgnoreCase(name))return i;return 0;}
    static int tierOf(int score){int t=0;for(int i=0;i<FLOORS.length;i++)if(score>=FLOORS[i])t=i;return t;}
    static int color(int tier,boolean dark){return dark||tier!=2?COLORS[tier][tier==3&&!dark?1:0]:COLORS[tier][1];}

    /** A nine-step heraldic crest on a 120×134 grid: a shield gains a crown, then wings, a star and a second pair of wings. */
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

    /** The nine camps up a dusk ridge; camps above the current rank are dimmed. */
    static final class Ridge extends View {
        static final float[][] CAMPS={{.08f,.84f},{.20f,.70f},{.30f,.78f},{.43f,.58f},{.53f,.64f},{.63f,.42f},{.71f,.48f},{.81f,.28f},{.91f,.14f}};
        final AppUi ui;final int current;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);final Bitmap[] marks=new Bitmap[9];
        Ridge(AppUi ui,int current){super(ui.context);this.ui=ui;this.current=current;}
        private void hill(Canvas c,int color,float... v){Path a=new Path();a.moveTo(0,getHeight());for(int i=0;i<v.length;i+=2)a.lineTo(v[i]*getWidth(),v[i+1]*getHeight());a.lineTo(getWidth(),getHeight());a.close();p.setColor(color);p.setShader(null);c.drawPath(a,p);}
        @Override protected void onDraw(Canvas c){int w=getWidth(),h=getHeight();p.setShader(new LinearGradient(0,0,0,h,new int[]{0xFF1A1248,0xFF5A2A9A,0xFFC95F8E},new float[]{0,.65f,1},Shader.TileMode.CLAMP));c.drawRect(0,0,w,h,p);p.setShader(null);
            hill(c,0xFF2A1460,0,.9f,.2f,.68f,.3f,.76f,.43f,.54f,.53f,.62f,.63f,.38f,.71f,.46f,.91f,.08f,1,.24f);hill(c,ui.dark?ui.background:0xFF1D1729,0,.98f,.3f,.88f,.6f,.94f,1,.78f);
            for(int i=0;i<9;i++){boolean here=i==current;int cw=ui.dp(here?36:20),ch=ui.dp(here?40:23);if(marks[i]==null){Crest crest=new Crest(getContext(),i,i>current);crest.layout(0,0,cw,ch);Bitmap b=Bitmap.createBitmap(cw,ch,Bitmap.Config.ARGB_8888);crest.draw(new Canvas(b));marks[i]=b;}c.drawBitmap(marks[i],CAMPS[i][0]*w-cw/2f,CAMPS[i][1]*h-ch/2f,null);}}
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

    /** Lines over a shared x axis. A gap wider than gap is drawn dashed, so a break is never read as measured data. */
    static final class Chart extends View {
        final AppUi ui;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);final ArrayList<double[][]> series=new ArrayList<>();final ArrayList<Integer> colors=new ArrayList<>(),widths=new ArrayList<>();double gap=1e18;Double reference;
        Chart(AppUi ui){super(ui.context);this.ui=ui;setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);}
        /** points[i]={x,y}; width 0 draws dots. */
        Chart line(double[][] points,int color,int width){series.add(points);colors.add(color);widths.add(width);return this;}
        @Override protected void onDraw(Canvas c){double x0=1e18,x1=-1e18,y0=1e18,y1=-1e18;for(double[][] s:series)for(double[] q:s){x0=Math.min(x0,q[0]);x1=Math.max(x1,q[0]);y0=Math.min(y0,q[1]);y1=Math.max(y1,q[1]);}if(reference!=null){y0=Math.min(y0,reference);y1=Math.max(y1,reference);}if(x1<x0)return;if(x1==x0)x1=x0+1;if(y1==y0){y0-=1;y1+=1;}
            float pad=ui.dpf(6),w=getWidth()-2*pad,h=getHeight()-2*pad;if(reference!=null){p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(ui.dpf(1));p.setColor(ui.strokeStrong);p.setPathEffect(new DashPathEffect(new float[]{ui.dpf(3),ui.dpf(4)},0));float y=(float)(pad+h-(reference-y0)/(y1-y0)*h);c.drawLine(pad,y,pad+w,y,p);p.setPathEffect(null);}
            for(int i=0;i<series.size();i++){double[][] s=series.get(i);p.setColor(colors.get(i));int wd=widths.get(i);p.setStrokeCap(Paint.Cap.ROUND);if(wd==0){p.setStyle(Paint.Style.FILL);for(double[] q:s)c.drawCircle((float)(pad+(q[0]-x0)/(x1-x0)*w),(float)(pad+h-(q[1]-y0)/(y1-y0)*h),ui.dpf(2.2f),p);continue;}
                p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(ui.dpf(wd));Path a=new Path(),missing=new Path();boolean open=false;double last=0;float px=0,py=0;for(double[] q:s){float x=(float)(pad+(q[0]-x0)/(x1-x0)*w),y=(float)(pad+h-(q[1]-y0)/(y1-y0)*h);if(!open){a.moveTo(x,y);a.lineTo(x,y);open=true;}else if(q[0]-last>gap){missing.moveTo(px,py);missing.lineTo(x,y);a.moveTo(x,y);a.lineTo(x,y);}else a.lineTo(x,y);last=q[0];px=x;py=y;}c.drawPath(a,p);p.setPathEffect(new DashPathEffect(new float[]{ui.dpf(3),ui.dpf(5)},0));p.setStrokeWidth(ui.dpf(1.5f));c.drawPath(missing,p);p.setPathEffect(null);}p.setStyle(Paint.Style.FILL);}
    }

    /** A row that slides left under the finger and deletes past a third of its width; vertical scrolling and taps pass through. */
    static final class SwipeRow extends LinearLayout {
        final Runnable remove;final int slop;float startX,startY;boolean dragging;
        SwipeRow(AppUi ui,Runnable remove){super(ui.context);this.remove=remove;slop=android.view.ViewConfiguration.get(ui.context).getScaledTouchSlop()*2;}
        @Override public boolean onInterceptTouchEvent(MotionEvent e){if(e.getAction()==MotionEvent.ACTION_DOWN){startX=e.getRawX();startY=e.getRawY();dragging=false;}else if(e.getAction()==MotionEvent.ACTION_MOVE&&startX-e.getRawX()>slop&&Math.abs(e.getRawY()-startY)<slop){dragging=true;getParent().requestDisallowInterceptTouchEvent(true);return true;}return false;}
        @Override public boolean onTouchEvent(MotionEvent e){if(!dragging)return e.getAction()==MotionEvent.ACTION_DOWN;if(e.getAction()==MotionEvent.ACTION_MOVE){setTranslationX(Math.min(0,e.getRawX()-startX));setAlpha(1+getTranslationX()/getWidth());}else if(e.getAction()==MotionEvent.ACTION_UP||e.getAction()==MotionEvent.ACTION_CANCEL){dragging=false;if(e.getAction()==MotionEvent.ACTION_UP&&-getTranslationX()>getWidth()/3f){performHapticFeedback(HapticFeedbackConstants.CONFIRM);remove.run();}else animate().translationX(0).alpha(1).setDuration(160).start();}return true;}
    }

    /** Full-height sheet with a back control. */
    static final class Sheet {
        final AppUi ui;final Dialog dialog;final LinearLayout root,body,bar;final ScrollView scroll;
        Sheet(AppUi ui,String heading){this.ui=ui;dialog=ui.sheet();root=ui.column();root.setBackgroundColor(ui.background);root.setFitsSystemWindows(true);bar=ui.row();bar.setPadding(ui.dp(8),ui.dp(8),ui.dp(12),ui.dp(4));bar.addView(ui.iconButton("back","Back",dialog::dismiss),new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));TextView h=ui.type(heading,20,26,700,0,ui.text);h.setMaxLines(2);bar.addView(h,MainParts.weighted(ui,1,4,0,0,0));root.addView(bar);
            scroll=new ScrollView(ui.context);body=ui.column();body.setPadding(ui.dp(16),ui.dp(8),ui.dp(16),ui.dp(28));scroll.addView(body);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));dialog.setContentView(root);}
        Sheet show(){dialog.show();Window w=dialog.getWindow();if(w!=null)w.setLayout(-1,-1);return this;}
    }
    static LinearLayout card(AppUi ui){LinearLayout box=ui.column();box.setPadding(ui.dp(14),ui.dp(12),ui.dp(14),ui.dp(12));box.setBackground(ui.outline(ui.surface,18,ui.stroke,1));return box;}
    static LinearLayout.LayoutParams gap(AppUi ui,int bottom){return MainParts.params(ui,-1,-2,0,0,0,bottom);}
    static View pair(AppUi ui,String left,String right,int rightColor){LinearLayout r=ui.row();r.addView(ui.type(left,14,20,400,0,ui.text),new LinearLayout.LayoutParams(0,-2,1));r.addView(ui.type(right,14,20,600,0,rightColor));r.setPadding(0,ui.dp(3),0,ui.dp(3));return r;}
    static String kg(double v){return v==Math.rint(v)?String.valueOf((long)v):String.format(Locale.ROOT,"%.1f",v);}
    static String clock(long seconds){seconds=Math.max(0,seconds);long h=seconds/3600,m=seconds/60%60,s=seconds%60;return h>0?String.format(Locale.ROOT,"%d:%02d:%02d",h,m,s):String.format(Locale.ROOT,"%d:%02d",m,s);}
    static View row(AppUi ui,String title,String note,Runnable action){LinearLayout r=ui.row();r.setMinimumHeight(ui.dp(56));r.setPadding(ui.dp(14),ui.dp(8),ui.dp(10),ui.dp(8));r.setBackground(ui.pressable(ui.outline(ui.surface,16,ui.stroke,1),16));LinearLayout w=ui.column();w.addView(ui.type(title,15,20,600,0,ui.text));if(note!=null&&!note.isEmpty())w.addView(ui.type(note,12.5f,17,400,0,ui.muted));r.addView(w,new LinearLayout.LayoutParams(0,-2,1));r.addView(MainParts.icon(ui,"arrow",ui.muted),new LinearLayout.LayoutParams(ui.dp(18),ui.dp(18)));r.setOnClickListener(v->action.run());AppUi.press(r);return r;}
}
