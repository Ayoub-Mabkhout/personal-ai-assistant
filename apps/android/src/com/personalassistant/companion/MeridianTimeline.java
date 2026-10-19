package com.personalassistant.companion;

import android.graphics.*;
import android.view.View;

/** Today from midnight to midnight: the daylight band from sunrise to sunset, a dot at now, and both times underneath. */
final class MeridianTimeline extends View {
    private final AppUi ui;private MeridianSky sky;
    private final Paint track=new Paint(Paint.ANTI_ALIAS_FLAG),band=new Paint(Paint.ANTI_ALIAS_FLAG),dot=new Paint(Paint.ANTI_ALIAS_FLAG),label=new Paint(Paint.ANTI_ALIAS_FLAG),glyph=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final java.text.DateFormat clock;
    private final Runnable tick=new Runnable(){@Override public void run(){update(MeridianSky.now(getContext()));postDelayed(this,60000);}};

    MeridianTimeline(android.content.Context context,AppUi ui){
        super(context);this.ui=ui;clock=android.text.format.DateFormat.getTimeFormat(context);
        track.setColor(ui.stroke);label.setColor(ui.muted);label.setTextSize(ui.dpf(11));label.setTypeface(AppUi.face(600));glyph.setColor(ui.muted);
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_YES);update(MeridianSky.now(context));
    }
    void update(MeridianSky value){
        sky=value;String described=sky.sunrise>0?"Sunrise "+clock.format(new java.util.Date(sky.sunrise))+", sunset "+clock.format(new java.util.Date(sky.sunset)):sky.sun?"The sun stays up today":"The sun stays down today";
        setContentDescription(described);invalidate();
    }
    @Override protected void onAttachedToWindow(){super.onAttachedToWindow();removeCallbacks(tick);postDelayed(tick,60000);}
    @Override protected void onDetachedFromWindow(){removeCallbacks(tick);super.onDetachedFromWindow();}
    @Override protected void onMeasure(int w,int h){setMeasuredDimension(MeasureSpec.getSize(w),ui.dp(34));}

    private float fraction(long at){java.util.Calendar c=java.util.Calendar.getInstance();c.setTimeInMillis(at);return (c.get(java.util.Calendar.HOUR_OF_DAY)*60+c.get(java.util.Calendar.MINUTE))/1440f;}
    @Override protected void onDraw(Canvas c){
        float w=getWidth(),y=ui.dpf(5),r=ui.dpf(1.5f);
        c.drawRoundRect(0,y-r,w,y+r,r,r,track);
        if(sky.sunrise>0&&sky.sunset>sky.sunrise){float a=fraction(sky.sunrise)*w,b=fraction(sky.sunset)*w;
            band.setShader(new LinearGradient(a,0,b,0,new int[]{0xFFF0A2B0,0xFFFFD9B0,0xFFF08A7A},null,Shader.TileMode.CLAMP));c.drawRoundRect(a,y-r,b,y+r,r,r,band);}
        else if(sky.sun){band.setShader(new LinearGradient(0,0,w,0,0xFFFFD9B0,0xFFF0A2B0,Shader.TileMode.CLAMP));c.drawRoundRect(0,y-r,w,y+r,r,r,band);}
        float x=Math.max(ui.dpf(5),Math.min(w-ui.dpf(5),fraction(sky.at)*w));
        dot.setColor(AppUi.alpha(ui.accent,.2f));c.drawCircle(x,y,ui.dpf(8),dot);dot.setColor(ui.accent);c.drawCircle(x,y,ui.dpf(5),dot);
        float base=ui.dpf(29),icon=ui.dpf(12);
        if(sky.sunrise>0){
            String rise=clock.format(new java.util.Date(sky.sunrise)),set=clock.format(new java.util.Date(sky.sunset));
            glyph(c,"weather-sun",0,base-icon+ui.dpf(1),icon);label.setTextAlign(Paint.Align.LEFT);c.drawText(rise,icon+ui.dpf(4),base,label);
            label.setTextAlign(Paint.Align.RIGHT);float tw=label.measureText(set);c.drawText(set,w,base,label);glyph(c,"weather-moon",w-tw-icon-ui.dpf(4),base-icon+ui.dpf(1),icon);
        }
        label.setTextAlign(Paint.Align.CENTER);c.drawText(clock.format(new java.util.Date(sky.at)),w/2,base,label);
    }
    private void glyph(Canvas c,String kind,float x,float y,float size){c.save();c.translate(x,y);c.scale(size/24f,size/24f);AppUi.Glyphs.draw(c,kind,glyph,AppUi.Glyphs.units(size,ui.density));c.restore();}
}
