package com.personalassistant.companion;

import android.graphics.*;
import android.view.*;
import java.time.*;
import java.time.format.TextStyle;
import java.util.*;
import java.util.function.Consumer;
import java.util.function.IntConsumer;

/** One month of training at a glance: a day holds a circle in its workout's colour, an outline for a rest day. Swipe for other months. */
final class WorkoutCalendar extends View {
    private static final String[] WEEK={"M","T","W","T","F","S","S"};
    final AppUi ui;private final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG),t=new Paint(Paint.ANTI_ALIAS_FLAG);private final int slop;
    /** A stretch of days behind the workout circles. */
    static final class Band{final LocalDate from,to;final int color;Band(LocalDate from,LocalDate to,int color){this.from=from;this.to=to;this.color=color;}}
    List<Band> bands=new ArrayList<>();YearMonth month=YearMonth.now();Map<LocalDate,int[]> days=new HashMap<>();Consumer<LocalDate> tap;IntConsumer swipe;private float downX,downY;
    WorkoutCalendar(AppUi ui){super(ui.context);this.ui=ui;t.setTextAlign(Paint.Align.CENTER);slop=ViewConfiguration.get(ui.context).getScaledTouchSlop()*3;}
    private int lead(){return month.atDay(1).getDayOfWeek().getValue()-1;}
    private int rows(){return (int)Math.ceil((lead()+month.lengthOfMonth())/7.0);}
    private float cell(){return getWidth()/7f;}
    private float head(){return ui.dpf(26);}
    @Override protected void onMeasure(int w,int h){int width=MeasureSpec.getSize(w);setMeasuredDimension(width,Math.round(ui.dpf(26)+rows()*Math.min(width/7f,ui.dpf(48))));}
    @Override protected void onDraw(Canvas c){float size=cell(),tall=(getHeight()-head())/rows();t.setTypeface(AppUi.face(600));t.setTextSize(ui.dpf(11.5f));t.setColor(ui.muted);for(int i=0;i<7;i++)c.drawText(WEEK[i],size*(i+.5f),ui.dpf(15),t);drawBands(c,size,tall);LocalDate today=LocalDate.now();t.setTextSize(ui.dpf(14));for(int d=1;d<=month.lengthOfMonth();d++){int at=lead()+d-1;float x=size*(at%7+.5f),y=head()+tall*(at/7+.5f),r=Math.min(size,tall)*.42f;LocalDate day=month.atDay(d);int[] hues=days.get(day);boolean filled=hues!=null&&hues[0]!=0;if(filled){RectF box=new RectF(x-r,y-r,x+r,y+r);p.setStyle(Paint.Style.FILL);if(hues.length==1)c.drawCircle(x,y,r,fill(hues[0]));else{c.drawArc(box,90,180,true,fill(hues[0]));c.drawArc(box,270,180,true,fill(hues[1]));}}else if(hues!=null){p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(ui.dpf(1.5f));p.setColor(ui.strokeStrong);c.drawCircle(x,y,r-ui.dpf(1),p);}if(day.equals(today)){p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(ui.dpf(2));p.setColor(ui.text);c.drawCircle(x,y,r+ui.dpf(1.5f),p);}t.setTypeface(AppUi.face(filled?800:500));t.setColor(filled?0xFF17102A:day.isAfter(today)?ui.strokeStrong:ui.muted);c.drawText(String.valueOf(d),x,y+ui.dpf(5),t);}}
    /** A sprint is a quiet wash behind its days, one rounded strip per week, so the circles stay the loudest thing here. */
    private void drawBands(Canvas c,float size,float tall){p.setStyle(Paint.Style.FILL);LocalDate first=month.atDay(1),last=month.atEndOfMonth();for(Band b:bands){LocalDate from=b.from.isBefore(first)?first:b.from,to=b.to.isAfter(last)?last:b.to;if(from.isAfter(to))continue;p.setColor(AppUi.alpha(b.color,ui.dark?.10f:.13f));for(LocalDate d=from;!d.isAfter(to);){int at=lead()+d.getDayOfMonth()-1;LocalDate end=d.plusDays(6-at%7);if(end.isAfter(to))end=to;int stop=lead()+end.getDayOfMonth()-1;float top=head()+tall*(at/7)+tall*.04f,radius=tall*.46f;c.drawRoundRect(size*(at%7)+size*.02f,top,size*(stop%7+1)-size*.02f,top+tall*.92f,radius,radius,p);d=end.plusDays(1);}}}
    private Paint fill(int color){p.setStyle(Paint.Style.FILL);p.setColor(color);return p;}
    @Override public boolean onTouchEvent(MotionEvent e){if(e.getActionMasked()==MotionEvent.ACTION_DOWN){downX=e.getX();downY=e.getY();return true;}if(e.getActionMasked()==MotionEvent.ACTION_MOVE){if(Math.abs(e.getX()-downX)>slop&&Math.abs(e.getX()-downX)>Math.abs(e.getY()-downY))getParent().requestDisallowInterceptTouchEvent(true);return true;}if(e.getActionMasked()!=MotionEvent.ACTION_UP)return true;float dx=e.getX()-downX;if(Math.abs(dx)>slop*2){if(swipe!=null)swipe.accept(dx<0?1:-1);return true;}if(Math.abs(dx)>slop||e.getY()<head())return true;int column=(int)(e.getX()/cell()),row=(int)((e.getY()-head())/((getHeight()-head())/rows())),d=row*7+column-lead()+1;if(d>=1&&d<=month.lengthOfMonth()&&tap!=null&&days.containsKey(month.atDay(d))){performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY);tap.accept(month.atDay(d));}return true;}

    /** Every training month as a bar, so years of history read at a glance and any month is a tap away. */
    static final class Months extends View {
        final AppUi ui;final List<YearMonth> months;final Map<YearMonth,Integer> counts;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG),t=new Paint(Paint.ANTI_ALIAS_FLAG);YearMonth selected;Consumer<YearMonth> pick;private float downX;
        Months(AppUi ui,List<YearMonth> months,Map<YearMonth,Integer> counts){super(ui.context);this.ui=ui;this.months=months;this.counts=counts;t.setTextAlign(Paint.Align.CENTER);t.setTypeface(AppUi.face(600));}
        private float slot(){return ui.dpf(26);}
        @Override protected void onMeasure(int w,int h){int fit=Math.round(months.size()*slot()),room=MeasureSpec.getSize(w);setMeasuredDimension(Math.max(fit,MeasureSpec.getMode(w)==MeasureSpec.UNSPECIFIED?fit:room),ui.dp(76));}
        float at(YearMonth m){return (months.indexOf(m)+.5f)*slot();}
        @Override protected void onDraw(Canvas c){int top=1;for(int v:counts.values())top=Math.max(top,v);float bottom=getHeight()-ui.dpf(20),tall=bottom-ui.dpf(8);t.setTextSize(ui.dpf(10.5f));for(int i=0;i<months.size();i++){YearMonth m=months.get(i);int n=counts.getOrDefault(m,0);float x=(i+.5f)*slot(),h=n==0?ui.dpf(3):Math.max(ui.dpf(6),tall*n/top),half=ui.dpf(8);boolean on=m.equals(selected);p.setColor(on?ui.accent:n==0?ui.stroke:AppUi.alpha(ui.accent,.38f));c.drawRoundRect(x-half,bottom-h,x+half,bottom,ui.dpf(5),ui.dpf(5),p);t.setColor(on?ui.text:ui.muted);c.drawText(m.getMonthValue()==1?"'"+String.valueOf(m.getYear()).substring(2):m.getMonth().getDisplayName(TextStyle.NARROW,Locale.getDefault()),x,getHeight()-ui.dpf(4),t);}}
        @Override public boolean onTouchEvent(MotionEvent e){if(e.getActionMasked()==MotionEvent.ACTION_DOWN){downX=e.getX();return true;}if(e.getActionMasked()==MotionEvent.ACTION_UP&&Math.abs(e.getX()-downX)<ui.dpf(10)){int i=(int)(e.getX()/slot());if(i>=0&&i<months.size()&&pick!=null)pick.accept(months.get(i));}return true;}
    }
}
