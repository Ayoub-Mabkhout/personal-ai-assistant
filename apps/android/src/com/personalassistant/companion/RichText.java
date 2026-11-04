package com.personalassistant.companion;

import android.graphics.*;
import android.text.*;
import android.text.style.*;
import android.view.View;
import java.util.List;

/**
 * Markdown chat answers as one Spanned for a single TextView, in the app's type and colours; Markdown decides the structure.
 * Show with setText(RichText.render(ui,answer)) and LinkMovementMethod so links open; safe to re-render on every streamed chunk.
 */
final class RichText {
    private RichText(){}
    private static final Typeface MONO=Typeface.MONOSPACE,MONO_BOLD=Typeface.create(Typeface.MONOSPACE,Typeface.BOLD);
    private static final float[] HEADINGS={1.3f,1.18f,1.06f};

    static CharSequence render(AppUi ui,String markdown){
        SpannableStringBuilder out=new SpannableStringBuilder();
        try{blocks(ui,out,Markdown.parse(markdown));return out;}catch(RuntimeException unexpected){return markdown==null?"":markdown;}
    }

    private static void blocks(AppUi ui,SpannableStringBuilder out,List<Markdown.Block> list){
        String[] markers={"-","-"};
        for(int i=0;i<list.size();i++){Markdown.Block b=list.get(i);
            if(i>0){out.append('\n');if(b.kind!=Markdown.ITEM||list.get(i-1).kind!=Markdown.ITEM){int at=out.length();out.append('\n');out.setSpan(new Gap(ui.dp(7)),at,at+1,Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);}}
            int start=out.length();
            switch(b.kind){
                case Markdown.HEADING:runs(ui,out,b.text,Markdown.BOLD);if(out.length()>start)out.setSpan(new RelativeSizeSpan(HEADINGS[b.level-1]),start,out.length(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);break;
                case Markdown.CODE:out.append(b.text.isEmpty()?"​":b.text);span(out,start,new Face(Markdown.MONO),new RelativeSizeSpan(.9f),new Code(ui));break;
                case Markdown.ITEM:{
                    if(!b.marker.isEmpty())markers[b.level]=b.marker;String marker=markers[b.level];runs(ui,out,b.text,0);
                    String glyph=b.marker.isEmpty()?"":b.ordered()?b.marker.substring(0,b.marker.length()-1)+".":b.level==0?"•":"◦";
                    zero(out,start);out.setSpan(new Hang(ui,b.level,glyph,marker),start,out.length(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);break;}
                case Markdown.QUOTE:blocks(ui,out,b.children);zero(out,start);span(out,start,new Bar(ui),new ForegroundColorSpan(ui.muted));break;
                case Markdown.RULE:out.append('​');span(out,start,new Rule(ui));break;
                case Markdown.TABLE:
                    for(int r=0;r<b.rows.size();r++){if(r>0)out.append('\n');String[] cells=b.rows.get(r);
                        for(int c=0;c<cells.length;c++){if(c>0){int at=out.length();out.append("  ·  ");span(out,at,new ForegroundColorSpan(ui.muted));}runs(ui,out,cells[c].isEmpty()?"–":cells[c],r==0?Markdown.BOLD:0);}}
                    break;
                default:runs(ui,out,b.text,0);
            }
            zero(out,start);
        }
    }
    /** Empty blocks keep a zero-width character so their paragraph spans still have a range. */
    private static void zero(SpannableStringBuilder out,int start){if(out.length()==start)out.append('​');}
    private static void span(SpannableStringBuilder out,int start,Object... spans){for(Object span:spans)out.setSpan(span,start,out.length(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);}
    private static void runs(AppUi ui,SpannableStringBuilder out,String text,int base){
        for(Markdown.Run run:Markdown.inline(text)){int start=out.length(),style=run.style|base;out.append(run.text);
            if(style!=0)span(out,start,new Face(style));
            if((style&Markdown.MONO)!=0)span(out,start,new BackgroundColorSpan(AppUi.alpha(ui.text,ui.dark?.14f:.08f)),new RelativeSizeSpan(.92f));
            if(run.url!=null)span(out,start,new Link(run.url,ui.accent));}
    }

    /** Onest bold from AppUi, monospace for code, and a slant for italic since the app font has no italic. */
    static final class Face extends MetricAffectingSpan {
        final int style;
        Face(int style){this.style=style;}
        @Override public void updateMeasureState(TextPaint p){apply(p);}
        @Override public void updateDrawState(TextPaint p){apply(p);}
        private void apply(TextPaint p){boolean bold=(style&Markdown.BOLD)!=0;
            if((style&Markdown.MONO)!=0)p.setTypeface(bold?MONO_BOLD:MONO);else if(bold)p.setTypeface(AppUi.face(700));
            if((style&Markdown.ITALIC)!=0)p.setTextSkewX(-.2f);}
    }
    /** Accent, underlined; a missing handler for the scheme is ignored rather than crashing the page. */
    static final class Link extends URLSpan {
        final int color;
        Link(String url,int color){super(url);this.color=color;}
        @Override public void updateDrawState(TextPaint p){p.setColor(color);p.setUnderlineText(true);}
        @Override public void onClick(View view){try{super.onClick(view);}catch(RuntimeException unavailable){}}
    }
    /** Shrinks the blank line between blocks to a fixed gap. */
    static final class Gap implements LineHeightSpan {
        final int height;
        Gap(int height){this.height=height;}
        @Override public void chooseHeight(CharSequence text,int start,int end,int spanstartv,int v,Paint.FontMetricsInt fm){fm.top=fm.ascent=-height;fm.bottom=fm.descent=0;}
    }
    /** Hanging indent with the bullet or number in the gutter, so wrapped lines align with the first; an empty glyph continues the item. */
    static final class Hang implements LeadingMarginSpan {
        final int indent,width,color;final String glyph;
        Hang(AppUi ui,int depth,String glyph,String marker){this.glyph=glyph;color=ui.muted;indent=ui.dp(depth*18);width=Character.isDigit(marker.charAt(0))?Math.max(ui.dp(22),ui.dp(6+marker.length()*8)):ui.dp(18);}
        @Override public int getLeadingMargin(boolean first){return indent+width;}
        @Override public void drawLeadingMargin(Canvas c,Paint p,int x,int dir,int top,int baseline,int bottom,CharSequence text,int start,int end,boolean first,Layout layout){
            if(glyph.isEmpty()||!first||!(text instanceof Spanned)||((Spanned)text).getSpanStart(this)!=start)return;
            int was=p.getColor();p.setColor(color);c.drawText(glyph,dir>0?x+indent:x-indent-p.measureText(glyph),baseline,p);p.setColor(was);
        }
    }
    /** Quote bar in the accent colour. */
    static final class Bar implements LeadingMarginSpan {
        final int color,stripe,gap;
        Bar(AppUi ui){color=AppUi.alpha(ui.accent,.7f);stripe=ui.dp(3);gap=ui.dp(11);}
        @Override public int getLeadingMargin(boolean first){return stripe+gap;}
        @Override public void drawLeadingMargin(Canvas c,Paint p,int x,int dir,int top,int baseline,int bottom,CharSequence text,int start,int end,boolean first,Layout layout){
            Paint.Style style=p.getStyle();int was=p.getColor();p.setStyle(Paint.Style.FILL);p.setColor(color);c.drawRect(Math.min(x,x+dir*stripe),top,Math.max(x,x+dir*stripe),bottom,p);p.setStyle(style);p.setColor(was);
        }
    }
    /** Full-width rounded panel behind a fenced block; it spills a few pixels into the gaps above and below. */
    static final class Code implements LeadingMarginSpan,LineBackgroundSpan {
        final int color,pad,radius;
        Code(AppUi ui){color=AppUi.mix(ui.surface,ui.text,ui.dark?.1f:.06f);pad=ui.dp(10);radius=ui.dp(8);}
        @Override public int getLeadingMargin(boolean first){return pad;}
        @Override public void drawLeadingMargin(Canvas c,Paint p,int x,int dir,int top,int baseline,int bottom,CharSequence text,int start,int end,boolean first,Layout layout){}
        @Override public void drawBackground(Canvas c,Paint p,int left,int right,int top,int baseline,int bottom,CharSequence text,int start,int end,int line){
            Spanned s=(Spanned)text;boolean head=start<=s.getSpanStart(this),tail=end>=s.getSpanEnd(this);int was=p.getColor();Paint.Style style=p.getStyle();p.setStyle(Paint.Style.FILL);p.setColor(color);
            float t=head?top-pad/3f:top,b=tail?bottom+pad/3f:bottom;c.drawRoundRect(new RectF(left,t,right,tail?b:b+radius),radius,radius,p);if(!head)c.drawRect(left,t,right,Math.min(b,t+radius),p);
            p.setColor(was);p.setStyle(style);
        }
    }
    /** A hairline across the line that holds the rule. */
    static final class Rule implements LineBackgroundSpan {
        final int color,thick;
        Rule(AppUi ui){color=ui.stroke;thick=Math.max(1,ui.dp(1));}
        @Override public void drawBackground(Canvas c,Paint p,int left,int right,int top,int baseline,int bottom,CharSequence text,int start,int end,int line){
            int was=p.getColor();Paint.Style style=p.getStyle();p.setStyle(Paint.Style.FILL);p.setColor(color);float mid=(top+bottom)/2f;c.drawRect(left,mid-thick/2f,right,mid+thick/2f,p);p.setColor(was);p.setStyle(style);
        }
    }
}
