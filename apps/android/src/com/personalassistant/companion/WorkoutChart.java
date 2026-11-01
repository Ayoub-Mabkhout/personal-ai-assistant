package com.personalassistant.companion;

import android.animation.ValueAnimator;
import android.graphics.*;
import android.view.*;
import android.widget.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.function.DoubleFunction;

/**
 * A dated chart to handle with one finger: it opens on recent months, drags sideways through older history, and a hold draws a line
 * that steps from measurement to measurement. A break longer than gap is dashed, so missing readings never look measured.
 */
final class WorkoutChart extends View {
    private static final class Series{double[][] points;int color,width;boolean dashed,gapsOnly;String name;}
    private static final DateTimeFormatter TIP=DateTimeFormatter.ofPattern("EEE d MMM yyyy"),DAY=DateTimeFormatter.ofPattern("d MMM"),MONTH=DateTimeFormatter.ofPattern("MMM");
    final AppUi ui;private final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG),t=new Paint(Paint.ANTI_ALIAS_FLAG);private final ArrayList<Series> series=new ArrayList<>();private final OverScroller fling;private final int slop;private final RectF plot=new RectF();
    DoubleFunction<String> format=WorkoutViews::kg;double gap=1e18;int window=183;Double reference;
    private double[][] events=new double[0][];private double first,last,end,span,low,high,step,flingFrom;private boolean placed,dragging,holding,moved;private float downX,downY,lastX;private int marker=-1;private VelocityTracker speed;
    private final Runnable hold=()->{holding=true;getParent().requestDisallowInterceptTouchEvent(true);performHapticFeedback(HapticFeedbackConstants.LONG_PRESS);snap(downX);};

    WorkoutChart(AppUi ui){super(ui.context);this.ui=ui;fling=new OverScroller(ui.context);slop=ViewConfiguration.get(ui.context).getScaledTouchSlop();t.setTypeface(AppUi.face(500));setFocusable(true);}
    private WorkoutChart add(double[][] points,int color,int width,boolean dashed,boolean gapsOnly,String name){Series s=new Series();s.points=points;s.color=color;s.width=width;s.dashed=dashed;s.gapsOnly=gapsOnly;s.name=name;series.add(s);if(events.length==0)events=points;for(double[] q:points){first=first==0?q[0]:Math.min(first,q[0]);last=Math.max(last,q[0]);}return this;}
    /** Separate measurements. */
    WorkoutChart dots(double[][] points,int color,String name){return add(points,color,0,false,false,name);}
    /** A line that bridges a gap with dashes. */
    WorkoutChart line(double[][] points,int color,int width,String name){return add(points,color,width,true,false,name);}
    /** A line that stops at a gap: a rolling average doesn't exist there. */
    WorkoutChart breaks(double[][] points,int color,int width,String name){return add(points,color,width,false,false,name);}
    /** Only the dashes across unmeasured spans. */
    WorkoutChart gaps(double[][] points,int color){return add(points,color,1,true,true,null);}

    /** The chart under a row of range chips. */
    static View framed(AppUi ui,WorkoutChart chart,int heightDp){LinearLayout box=ui.column();LinearLayout chips=ui.row();String[] names={"3M","6M","1Y","All"};int[] days={92,183,365,100000};TextView[] views=new TextView[names.length];Runnable[] paint=new Runnable[1];int[] on={1};paint[0]=()->{for(int i=0;i<views.length;i++){views[i].setTextColor(i==on[0]?ui.accent:ui.muted);views[i].setBackground(ui.outline(i==on[0]?ui.accentSoft:0,12,0,0));}};for(int i=0;i<names.length;i++){final int at=i;TextView c=ui.type(names[i],12.5f,17,700,0,ui.muted);c.setGravity(Gravity.CENTER);c.setPadding(ui.dp(12),ui.dp(6),ui.dp(12),ui.dp(6));c.setOnClickListener(v->{on[0]=at;paint[0].run();chart.spanTo(days[at]);});views[i]=c;chips.addView(c,MainParts.params(ui,-2,-2,0,0,4,0));}paint[0].run();box.addView(chips,MainParts.params(ui,-1,-2,0,0,0,6));box.addView(chart,new LinearLayout.LayoutParams(-1,ui.dp(heightDp)));return box;}

    private double total(){return Math.max(14,(last-first)*1.04);}
    private void place(){if(placed||plot.width()<=0)return;placed=true;span=Math.min(window,total());end=clamp(last+span*.03);}
    private double clamp(double value){return Math.max(first+span*.97,Math.min(last+span*.03,value));}
    private double perDay(){return plot.width()/span;}
    void spanTo(int days){marker=-1;double from=span,to=Math.min(days,total()),right=end;ValueAnimator a=ValueAnimator.ofFloat(0,1);a.setDuration(ValueAnimator.areAnimatorsEnabled()?220:0);a.addUpdateListener(x->{span=from+(to-from)*x.getAnimatedFraction();end=clamp(right);invalidate();});a.start();}
    private float x(double day){return (float)(plot.left+(day-(end-span))/span*plot.width());}
    private float y(double value){return (float)(plot.bottom-(value-low)/(high-low)*plot.height());}
    /** Whole steps over what's in view, with the points just outside so a line can leave the frame. */
    private void scale(){double min=1e18,max=-1e18,from=end-span;for(Series s:series){if(s.gapsOnly)continue;double[][] q=s.points;for(int i=0;i<q.length;i++){boolean in=q[i][0]>=from&&q[i][0]<=end||i+1<q.length&&q[i][0]<from&&q[i+1][0]>from||i>0&&q[i][0]>end&&q[i-1][0]<end;if(in){min=Math.min(min,q[i][1]);max=Math.max(max,q[i][1]);}}}if(reference!=null&&(max<-1e17||reference<=max*1.25)){min=Math.min(min,reference);max=Math.max(max,reference);}if(max<-1e17){min=0;max=1;}if(max==min){min-=1;max+=1;}double raw=(max-min)/3,power=Math.pow(10,Math.floor(Math.log10(raw))),unit=raw/power;step=(unit<=1?1:unit<=2?2:unit<=2.5?2.5:unit<=5?5:10)*power;low=Math.floor(min/step)*step;high=Math.ceil(max/step)*step;}

    @Override protected void onSizeChanged(int w,int h,int ow,int oh){plot.set(ui.dpf(4),ui.dpf(10),w-ui.dpf(52),h-ui.dpf(24));place();}
    @Override protected void onDraw(Canvas c){if(series.isEmpty()||span<=0)return;scale();p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(ui.dpf(1));p.setPathEffect(null);t.setTextSize(ui.dpf(11));t.setColor(ui.muted);t.setTextAlign(Paint.Align.RIGHT);for(double v=low;v<=high+step/2;v+=step){float at=y(v);p.setColor(ui.stroke);c.drawLine(plot.left,at,plot.right,at,p);c.drawText(format.apply(v),getWidth()-ui.dpf(2),at+ui.dpf(4),t);}dates(c);
        c.save();c.clipRect(plot.left-ui.dpf(4),0,plot.right+ui.dpf(4),plot.bottom+ui.dpf(4));if(reference!=null){p.setColor(ui.strokeStrong);p.setPathEffect(new DashPathEffect(new float[]{ui.dpf(3),ui.dpf(4)},0));c.drawLine(plot.left,y(reference),plot.right,y(reference),p);p.setPathEffect(null);}for(Series s:series)draw(c,s);if(marker>=0){float at=x(events[marker][0]);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(ui.dpf(1.5f));p.setColor(ui.text);c.drawLine(at,plot.top,at,plot.bottom,p);}c.restore();if(marker>=0)tip(c);}
    private void draw(Canvas c,Series s){p.setColor(s.color);p.setStrokeCap(Paint.Cap.ROUND);p.setStrokeJoin(Paint.Join.ROUND);if(s.width==0){p.setStyle(Paint.Style.FILL);float radius=ui.dpf(span>400?1.4f:2.2f);for(double[] q:s.points)if(q[0]>=end-span-2&&q[0]<=end+2)c.drawCircle(x(q[0]),y(q[1]),radius,p);return;}p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(ui.dpf(s.width));Path line=new Path(),missing=new Path();boolean open=false;double before=0;float px=0,py=0;for(double[] q:s.points){float a=x(q[0]),b=y(q[1]);if(!open){line.moveTo(a,b);line.lineTo(a,b);open=true;}else if(q[0]-before>gap){missing.moveTo(px,py);missing.lineTo(a,b);line.moveTo(a,b);line.lineTo(a,b);}else line.lineTo(a,b);before=q[0];px=a;py=b;}if(!s.gapsOnly)c.drawPath(line,p);if(s.dashed){p.setPathEffect(new DashPathEffect(new float[]{ui.dpf(4),ui.dpf(5)},0));p.setStrokeWidth(ui.dpf(1.5f));c.drawPath(missing,p);p.setPathEffect(null);}}
    /** Weeks up close, then months, then years; January names the year. */
    private void dates(Canvas c){double from=end-span;float base=getHeight()-ui.dpf(6);t.setTextAlign(Paint.Align.CENTER);t.setColor(ui.muted);LocalDate at=LocalDate.ofEpochDay((long)Math.floor(from));if(span<=62){int weeks=span<=31?1:2;for(LocalDate d=at.with(DayOfWeek.MONDAY);d.toEpochDay()<=end;d=d.plusWeeks(weeks))label(c,d,d.format(DAY),base);return;}int months=span<=240?1:span<=460?2:span<=1000?3:span<=2200?6:12;LocalDate d=at.withDayOfMonth(1);while((d.getMonthValue()-1)%months!=0)d=d.minusMonths(1);for(;d.toEpochDay()<=end;d=d.plusMonths(months))label(c,d,d.getMonthValue()==1?String.valueOf(d.getYear()):d.format(MONTH),base);}
    private void label(Canvas c,LocalDate d,String text,float base){float at=x(d.toEpochDay());if(at<plot.left+ui.dpf(12)||at>plot.right-ui.dpf(6))return;p.setColor(ui.stroke);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(ui.dpf(1));c.drawLine(at,plot.bottom,at,plot.bottom+ui.dpf(4),p);c.drawText(text,at,base,t);}
    /** The date and every series at the chosen measurement, kept inside the frame. */
    private void tip(Canvas c){double[] e=events[marker];String date=LocalDate.ofEpochDay((long)e[0]).format(TIP);ArrayList<Object[]> rows=new ArrayList<>();for(Series s:series){if(s.name==null)continue;for(double[] q:s.points)if(Math.abs(q[0]-e[0])<.5){rows.add(new Object[]{s.color,s.name+"  "+format.apply(q[1])});float yy=y(q[1]);p.setStyle(Paint.Style.FILL);p.setColor(ui.surface);c.drawCircle(x(e[0]),yy,ui.dpf(5),p);p.setColor(s.color);c.drawCircle(x(e[0]),yy,ui.dpf(3.5f),p);break;}}t.setTextAlign(Paint.Align.LEFT);t.setTextSize(ui.dpf(12));t.setTypeface(AppUi.face(700));float width=t.measureText(date);t.setTypeface(AppUi.face(500));for(Object[] r:rows)width=Math.max(width,t.measureText((String)r[1])+ui.dpf(14));float pad=ui.dpf(9),line=ui.dpf(17),w=width+2*pad,h=pad*2+line*(1+rows.size()),left=Math.max(0,Math.min(getWidth()-w,x(e[0])-w/2));RectF box=new RectF(left,0,left+w,h);p.setStyle(Paint.Style.FILL);p.setColor(ui.surfaceAlt);c.drawRoundRect(box,ui.dpf(12),ui.dpf(12),p);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(ui.dpf(1));p.setColor(ui.strokeStrong);c.drawRoundRect(box,ui.dpf(12),ui.dpf(12),p);float at=pad+ui.dpf(12);t.setColor(ui.text);t.setTypeface(AppUi.face(700));c.drawText(date,left+pad,at,t);t.setTypeface(AppUi.face(500));for(Object[] r:rows){at+=line;p.setStyle(Paint.Style.FILL);p.setColor((Integer)r[0]);c.drawCircle(left+pad+ui.dpf(4),at-ui.dpf(4),ui.dpf(4),p);c.drawText((String)r[1],left+pad+ui.dpf(14),at,t);}}

    private void snap(float at){double day=end-span+(at-plot.left)/perDay();int best=-1;double near=1e18;for(int i=0;i<events.length;i++){double[] e=events[i];if(e[0]<end-span||e[0]>end)continue;double d=Math.abs(e[0]-day);if(d<near){near=d;best=i;}}if(best>=0&&best!=marker){if(marker>=0)performHapticFeedback(HapticFeedbackConstants.CLOCK_TICK);marker=best;}invalidate();}
    @Override public boolean onTouchEvent(MotionEvent e){switch(e.getActionMasked()){
        case MotionEvent.ACTION_DOWN:fling.forceFinished(true);downX=lastX=e.getX();downY=e.getY();dragging=holding=moved=false;speed=VelocityTracker.obtain();speed.addMovement(e);postDelayed(hold,240);return true;
        case MotionEvent.ACTION_MOVE:if(speed!=null)speed.addMovement(e);if(holding){snap(e.getX());return true;}float dx=e.getX()-downX,dy=e.getY()-downY;if(!dragging&&Math.abs(dx)>slop&&Math.abs(dx)>Math.abs(dy)){removeCallbacks(hold);moved=true;if(span<total()){dragging=true;marker=-1;getParent().requestDisallowInterceptTouchEvent(true);}}else if(Math.abs(dy)>slop){removeCallbacks(hold);moved=true;}if(dragging){end=clamp(end-(e.getX()-lastX)/perDay());invalidate();}lastX=e.getX();return true;
        case MotionEvent.ACTION_UP:removeCallbacks(hold);if(dragging&&speed!=null){speed.computeCurrentVelocity(1000);flingFrom=end;fling.fling(0,0,(int)-speed.getXVelocity(),0,-10000000,10000000,0,0);postInvalidateOnAnimation();}else if(holding)marker=-1;else if(!moved){if(marker>=0)marker=-1;else snap(e.getX());}invalidate();release();return true;
        case MotionEvent.ACTION_CANCEL:removeCallbacks(hold);if(holding)marker=-1;invalidate();release();return true;
        default:return false;}}
    private void release(){dragging=holding=false;if(speed!=null){speed.recycle();speed=null;}}
    @Override public void computeScroll(){if(fling.computeScrollOffset()){double to=flingFrom+fling.getCurrX()/perDay(),held=clamp(to);end=held;if(held!=to)fling.forceFinished(true);postInvalidateOnAnimation();}}
    @Override protected void onDetachedFromWindow(){removeCallbacks(hold);fling.forceFinished(true);super.onDetachedFromWindow();}

    /** A small undecorated trend for a dashboard tile. */
    static final class Spark extends View {
        final AppUi ui;final double[] values;final int color;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);
        Spark(AppUi ui,double[] values,int color){super(ui.context);this.ui=ui;this.values=values;this.color=color;setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);}
        @Override protected void onDraw(Canvas c){if(values.length<2)return;double min=1e18,max=-1e18;for(double v:values){min=Math.min(min,v);max=Math.max(max,v);}if(max==min)max=min+1;float w=getWidth(),h=getHeight(),pad=ui.dpf(3);Path line=new Path();float px=0,py=0;for(int i=0;i<values.length;i++){px=i*(w-2*pad)/(values.length-1)+pad;py=(float)(h-pad-(values[i]-min)/(max-min)*(h-2*pad));if(i==0)line.moveTo(px,py);else line.lineTo(px,py);}Path fill=new Path(line);fill.lineTo(px,h);fill.lineTo(pad,h);fill.close();p.setStyle(Paint.Style.FILL);p.setShader(new LinearGradient(0,0,0,h,AppUi.alpha(color,.30f),AppUi.alpha(color,0f),Shader.TileMode.CLAMP));c.drawPath(fill,p);p.setShader(null);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(ui.dpf(2));p.setStrokeCap(Paint.Cap.ROUND);p.setStrokeJoin(Paint.Join.ROUND);p.setColor(color);c.drawPath(line,p);p.setStyle(Paint.Style.FILL);c.drawCircle(px,py,ui.dpf(3),p);}
    }
}
