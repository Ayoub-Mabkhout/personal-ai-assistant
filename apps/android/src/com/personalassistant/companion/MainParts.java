package com.personalassistant.companion;

import android.content.res.ColorStateList;
import android.graphics.*;
import android.graphics.drawable.*;
import android.view.*;
import android.widget.*;

/** Small pieces shared by the four main tabs. */
final class MainParts {
    private MainParts(){}

    static LinearLayout.LayoutParams params(AppUi ui,int width,int height,int left,int top,int right,int bottom){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(width,height);p.setMarginStart(ui.dp(left));p.topMargin=ui.dp(top);p.setMarginEnd(ui.dp(right));p.bottomMargin=ui.dp(bottom);return p;}
    static LinearLayout.LayoutParams weighted(AppUi ui,float weight,int left,int top,int right,int bottom){LinearLayout.LayoutParams p=params(ui,0,-2,left,top,right,bottom);p.weight=weight;return p;}

    /** Tonal chip: accent text on accent-soft, 48 dp touch area around a 36 dp face. */
    static AppUi.Pill tonalChip(AppUi ui,String label,String icon,Runnable action){
        AppUi.Pill chip=ui.chip(label,icon,action);chip.setTextColor(ui.accent);chip.setTypeface(AppUi.face(700));
        chip.setBackground(new RippleDrawable(ColorStateList.valueOf(AppUi.alpha(ui.accent,.2f)),ui.insetOf(ui.outline(ui.accentSoft,18,0,0),3,6,3,6),ui.insetOf(ui.pillMask(),3,6,3,6)));
        return chip.glyph(icon,ui.accent,18);
    }

    static AppUi.Icon icon(AppUi ui,String kind,int color){return new AppUi.Icon(ui.context,kind,color);}

    /** Rounded tinted panel with a glyph, a title and a detail line; the whole panel is the tap target. */
    static final class Banner extends LinearLayout {
        final TextView title,detail;final AppUi.Icon glyph;
        Banner(AppUi ui,String tone,String icon,String heading,String note,Runnable action){
            super(ui.context);int[] c=ui.toneColors(tone);setOrientation(HORIZONTAL);setGravity(Gravity.CENTER_VERTICAL);setMinimumHeight(ui.dp(56));setPadding(ui.dp(14),ui.dp(10),ui.dp(10),ui.dp(10));
            setBackground(ui.pressable(ui.outline(c[1],20,AppUi.alpha(c[0],.28f),1),20));
            glyph=icon(ui,icon,c[0]);addView(glyph,new LayoutParams(ui.dp(22),ui.dp(22)));
            LinearLayout words=ui.column();title=ui.type(heading,15,20,700,0,c[0]);words.addView(title);detail=ui.type(note,13,18,400,0,c[0]);words.addView(detail);
            addView(words,weighted(ui,1,12,0,8,0));
            if(action!=null){addView(icon(ui,"arrow",c[0]),new LayoutParams(ui.dp(20),ui.dp(20)));setOnClickListener(v->action.run());AppUi.press(this);}
        }
    }

    /** Vertical timeline rail with a ring node; the line is trimmed above the first and below the last node. */
    static final class Rail extends View {
        final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);final int color,line,fill;final boolean first,last;
        Rail(AppUi ui,int color,boolean first,boolean last){super(ui.context);this.color=color;line=ui.stroke;fill=ui.background;this.first=first;this.last=last;setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);}
        @Override protected void onDraw(Canvas c){
            float d=getResources().getDisplayMetrics().density,x=getWidth()/2f,y=21*d;p.setStyle(Paint.Style.STROKE);p.setStrokeCap(Paint.Cap.ROUND);p.setColor(line);p.setStrokeWidth(2*d);c.drawLine(x,first?y:0,x,last?y:getHeight(),p);
            p.setStyle(Paint.Style.FILL);p.setColor(fill);c.drawCircle(x,y,9*d,p);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(3.6f*d);p.setColor(color);c.drawCircle(x,y,7.2f*d,p);
        }
    }

    /** Surface card with a thin aurora outline and soft glows in two corners. */
    static final class HeroFace extends Drawable {
        final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);final int surface,glowA,glowB;final int[] ring;final float radius,edge;final RectF outer=new RectF(),inner=new RectF();final Path clip=new Path();Shader edgeShader,warm,cool;
        HeroFace(AppUi ui,float radiusDp){surface=ui.surface;radius=ui.dpf(radiusDp);edge=ui.dpf(1.25f);ring=new int[]{AppUi.alpha(ui.aurora[0],.62f),AppUi.alpha(ui.aurora[1],.42f),AppUi.alpha(ui.aurora[2],.62f)};glowA=AppUi.alpha(ui.aurora[1],ui.dark?.2f:.2f);glowB=AppUi.alpha(ui.glow,ui.dark?.2f:.26f);}
        @Override protected void onBoundsChange(Rect b){
            outer.set(b);inner.set(b);inner.inset(edge,edge);clip.reset();clip.addRoundRect(inner,radius-edge,radius-edge,Path.Direction.CW);
            edgeShader=new LinearGradient(b.left,b.top,b.right,b.bottom,ring,null,Shader.TileMode.CLAMP);
            warm=new RadialGradient(b.right,b.top,Math.max(1,b.width()*.55f),glowA,glowA&0x00FFFFFF,Shader.TileMode.CLAMP);cool=new RadialGradient(b.left,b.bottom,Math.max(1,b.width()*.5f),glowB,glowB&0x00FFFFFF,Shader.TileMode.CLAMP);
        }
        @Override public void draw(Canvas c){
            p.setStyle(Paint.Style.FILL);p.setShader(edgeShader);c.drawRoundRect(outer,radius,radius,p);p.setShader(null);p.setColor(surface);c.drawRoundRect(inner,radius-edge,radius-edge,p);
            c.save();c.clipPath(clip);p.setShader(warm);c.drawRect(inner,p);p.setShader(cool);c.drawRect(inner,p);p.setShader(null);c.restore();
        }
        @Override public void getOutline(Outline o){o.setRoundRect(getBounds(),radius);}
        @Override public void setAlpha(int a){}@Override public void setColorFilter(ColorFilter f){}@Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
    }
}
