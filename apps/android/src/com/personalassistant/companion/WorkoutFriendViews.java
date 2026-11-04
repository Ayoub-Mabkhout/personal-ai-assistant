package com.personalassistant.companion;

import android.graphics.*;
import android.graphics.drawable.*;
import android.text.*;
import android.text.style.ForegroundColorSpan;
import android.util.TypedValue;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.util.*;
import java.util.function.IntConsumer;

/**
 * Iron League as a league of athletes: tier-ringed monograms, the podium, your standing, athlete cards, a friend's hero and
 * head-to-head bars. Every colour is a tier colour or one of the app's own tokens, so light and dark both hold.
 */
final class WorkoutFriendViews {
    private WorkoutFriendViews(){}
    static final int NIGHT=0xFF1A1248,LILAC=0xFFE4D9FA,GOLD=0xFFFFD65C,PLUM=0xFF3A2470;
    interface Pick {void go(JSONObject member);}

    static String initials(String name){
        StringBuilder out=new StringBuilder();for(String word:(name==null?"":name).trim().split("\\s+")){if(out.length()>=2)break;if(!word.isEmpty())out.appendCodePoint(word.codePointAt(0));}
        return out.length()==0?"?":out.toString().toUpperCase(Locale.ROOT);
    }
    /** Lift names without the equipment suffix, so "Bench Press (Barbell)" and "Bench Press" are the same lift. */
    static String shortName(String name){return (name==null?"":name).replaceAll("(?i) \\((barbell|dumbbell|cable|machine)\\)","").trim();}
    static Integer score(JSONObject o,String key){return o==null||!o.has(key)||o.isNull(key)?null:o.optInt(key);}
    static String tierName(Integer s){return s==null?"Unranked":WorkoutViews.label(s);}
    static int hue(AppUi ui,Integer s){return s==null?ui.strokeStrong:WorkoutViews.color(WorkoutViews.tierOf(s),ui.dark);}
    static int ink(AppUi ui,Integer s){return s==null?ui.muted:WorkoutViews.ink(WorkoutViews.tierOf(s),ui.dark);}
    private static TextView single(TextView t){t.setSingleLine(true);t.setEllipsize(TextUtils.TruncateAt.END);return t;}
    /** Shrinks one line down to min sp so tier names fit a 320dp phone. Max lines rather than single line, which scrolls sideways and never shrinks; the view needs a fixed height. */
    private static TextView fit(TextView t,int min,int max){t.setSingleLine(false);t.setMaxLines(1);t.setEllipsize(TextUtils.TruncateAt.END);t.setAutoSizeTextTypeUniformWithConfiguration(min,max,1,TypedValue.COMPLEX_UNIT_SP);return t;}
    private static LinearLayout.LayoutParams at(AppUi ui,int w,int h,int start,int top){return MainParts.params(ui,w,h,start,top,0,0);}

    /** A monogram ringed in the athlete's tier colour with their crest pinned at the lower right; unranked athletes get a plain ring. */
    static final class Avatar extends View {
        final AppUi ui;final String letters;final int ring,face,ink;final float size;final WorkoutViews.Crest crest;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);
        Avatar(AppUi ui,String name,Integer score,int sizeDp,boolean onHero){
            super(ui.context);this.ui=ui;size=ui.dpf(sizeDp);letters=initials(name);
            ring=onHero&&score!=null?WorkoutViews.bright(WorkoutViews.tierOf(score)):hue(ui,score);
            face=onHero?AppUi.mix(NIGHT,ring,.3f):AppUi.mix(ui.surface,ring,.22f);ink=onHero?Color.WHITE:ui.text;
            crest=score==null?null:new WorkoutViews.Crest(ui.context,WorkoutViews.tierOf(score),false);
            if(crest!=null){int w=Math.round(size*.46f);crest.layout(0,0,w,Math.round(w*134f/120));}
            setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        }
        /** Room for the circle plus the crest that overhangs it. */
        LinearLayout.LayoutParams params(){return new LinearLayout.LayoutParams(Math.round(size*1.16f),Math.round(size*1.12f));}
        @Override protected void onDraw(Canvas c){
            float r=size/2,cx=getWidth()/2f,cy=r,pad=ui.dpf(size>ui.dpf(60)?3.5f:3);
            SweepGradient sweep=new SweepGradient(cx,cy,new int[]{ring,AppUi.alpha(ring,.35f),ring},null);Matrix turn=new Matrix();turn.setRotate(110,cx,cy);sweep.setLocalMatrix(turn);
            p.setShader(sweep);c.drawCircle(cx,cy,r,p);p.setShader(null);p.setColor(face);c.drawCircle(cx,cy,r-pad,p);
            p.setColor(ink);p.setTypeface(AppUi.face(800));p.setTextSize(size*.34f);p.setTextAlign(Paint.Align.CENTER);p.setLetterSpacing(-.02f);
            Paint.FontMetrics m=p.getFontMetrics();c.drawText(letters,cx,cy-(m.ascent+m.descent)/2,p);
            if(crest!=null){c.save();c.translate(cx+r*1.12f-crest.getWidth(),size*1.10f-crest.getHeight());crest.draw(c);c.restore();}
        }
    }

    /** The top three as a podium: second, first, third, each on a stepped block in their tier colour. */
    static View podium(AppUi ui,List<JSONObject> top,String me,Pick go){
        LinearLayout row=ui.row();row.setGravity(Gravity.BOTTOM);row.setPadding(0,ui.dp(8),0,0);int[] order={1,0,2};
        for(int k=0;k<3;k++){int i=order[k];LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(0,-2,1);if(k>0)lp.setMarginStart(ui.dp(8));
            row.addView(i<top.size()?step(ui,top.get(i),i+1,me,go):new View(ui.context),lp);}
        return row;
    }
    private static View step(AppUi ui,JSONObject m,int place,String me,Pick go){
        Integer s=score(m,"lifting_score");int tier=hue(ui,s);String name=m.optString("name");boolean mine=me.equals(m.optString("id"));
        LinearLayout slot=ui.column();slot.setGravity(Gravity.CENTER_HORIZONTAL);
        Avatar face=new Avatar(ui,name,s,place==1?64:50,false);slot.addView(face,face.params());
        TextView who=single(ui.type(name+(mine?" (you)":""),14,19,750,0,ui.text));who.setGravity(Gravity.CENTER_HORIZONTAL);slot.addView(who,at(ui,-1,-2,0,4));
        TextView level=single(ui.type(tierName(s),12,16,750,0,ink(ui,s)));level.setGravity(Gravity.CENTER_HORIZONTAL);slot.addView(level,at(ui,-1,-2,0,2));
        TextView block=ui.type(String.valueOf(place),22,26,850,0,Color.WHITE);block.setGravity(Gravity.TOP|Gravity.CENTER_HORIZONTAL);block.setPadding(0,ui.dp(8),0,0);
        GradientDrawable g=new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,new int[]{AppUi.mix(NIGHT,tier,.8f),AppUi.mix(NIGHT,tier,.3f)});
        float big=ui.dpf(14),small=ui.dpf(4);g.setCornerRadii(new float[]{big,big,big,big,small,small,small,small});block.setBackground(g);
        slot.addView(block,at(ui,-1,ui.dp(place==1?84:place==2?62:46),0,6));
        slot.setContentDescription(place+". "+name+(mine?", you":"")+", "+tierName(s));slot.setOnClickListener(v->go.go(m));AppUi.press(slot);
        return slot;
    }

    /** The app's aurora hero face. */
    static LinearLayout hero(AppUi ui){
        LinearLayout c=ui.column();c.setPadding(ui.dp(16),ui.dp(14),ui.dp(16),ui.dp(16));
        GradientDrawable g=new GradientDrawable(GradientDrawable.Orientation.TL_BR,new int[]{0xFF5631C4,0xFF29174E,0xFF9A347E});g.setCornerRadius(ui.dpf(24));c.setBackground(g);return c;
    }
    /** Your place, the next athlete to pass and how far, on a bar between the athletes either side of you. */
    static View standing(AppUi ui,List<JSONObject> order,int at){
        JSONObject you=order.get(at),above=at>0?order.get(at-1):null,below=at+1<order.size()?order.get(at+1):null;Integer s=score(you,"lifting_score");
        LinearLayout c=hero(ui);c.setTag("friends_standing");
        c.addView(ui.type("Your standing",12,16,600,0,LILAC));
        c.addView(single(ui.type(s==null?"Unranked":"#"+(at+1)+" of "+order.size(),30,36,850,-.02f,Color.WHITE)),at(ui,-1,-2,0,2));
        if(s==null){c.addView(line(ui,"Log a hard set on a main lift to join the standings.",null,""),at(ui,-1,-2,0,4));return c;}
        Integer up=score(above,"lifting_score"),down=score(below,"lifting_score");
        if(up!=null){int gap=up-s,lo=down!=null?down:Math.max(0,s-Math.max(gap,10)*2);
            c.addView(line(ui,gap>0?gap+" points to pass ":"Level with ",above.optString("name"),""),at(ui,-1,-2,0,4));
            float f=Math.max(.04f,Math.min(.96f,(s-lo)/(float)Math.max(1,up-lo)));
            LeagueBar bar=new LeagueBar(ui,f,initials(above.optString("name")));bar.setContentDescription(gap>0?gap+" points behind "+above.optString("name"):"Level with "+above.optString("name"));
            c.addView(bar,at(ui,-1,ui.dp(38),0,6));}
        else if(down!=null)c.addView(line(ui,"Top of the league, "+(s-down)+" points clear of ",below.optString("name"),"."),at(ui,-1,-2,0,4));
        else c.addView(line(ui,"Top of the league.",null,""),at(ui,-1,-2,0,4));
        return c;
    }
    private static TextView line(AppUi ui,String lead,String name,String tail){
        SpannableStringBuilder t=new SpannableStringBuilder(lead);
        if(name!=null){int from=t.length();t.append(name);t.setSpan(new ForegroundColorSpan(GOLD),from,t.length(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);t.setSpan(new RichText.Face(Markdown.BOLD),from,t.length(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);}
        t.append(tail);TextView v=ui.type("",14,20,400,0,0xFFF2ECFF);v.setText(t);return v;
    }
    /** A track between the athletes either side of you: the fill ends at your "You" pill, the one to pass sits at the far end. */
    static final class LeagueBar extends View {
        final AppUi ui;final float f;final String them;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);final RectF r=new RectF();
        LeagueBar(AppUi ui,float f,String them){super(ui.context);this.ui=ui;this.f=f;this.them=them;}
        @Override protected void onDraw(Canvas c){
            float w=getWidth(),h=getHeight(),bar=ui.dpf(10),top=h-bar,rad=bar/2;
            p.setShader(null);p.setColor(0x2EFFFFFF);r.set(0,top,w,h);c.drawRoundRect(r,rad,rad,p);
            p.setShader(new LinearGradient(0,0,w,0,0xFFB39CFF,GOLD,Shader.TileMode.CLAMP));r.set(0,top,Math.max(bar,f*w),h);c.drawRoundRect(r,rad,rad,p);p.setShader(null);
            p.setTypeface(AppUi.face(800));p.setTextSize(ui.dpf(10.5f));p.setTextAlign(Paint.Align.CENTER);
            float ph=ui.dpf(17),bottom=top-ui.dpf(4),tw=p.measureText(them)+ui.dpf(14);pill(c,w-tw/2,bottom,tw,ph,GOLD,them);
            float yw=p.measureText("You")+ui.dpf(14),x=Math.max(yw/2,Math.min(w-yw/2,f*w));pill(c,x,bottom,yw,ph,Color.WHITE,"You");
        }
        private void pill(Canvas c,float cx,float bottom,float w,float h,int fill,String text){
            p.setColor(fill);r.set(cx-w/2,bottom-h,cx+w/2,bottom);c.drawRoundRect(r,h/2,h/2,p);
            p.setColor(PLUM);Paint.FontMetrics m=p.getFontMetrics();c.drawText(text,cx,bottom-h/2-(m.ascent+m.descent)/2,p);
        }
    }

    /** One athlete: place, tier, running rank, sprint progress and how far they are from you. */
    static View athlete(AppUi ui,JSONObject m,int index,JSONObject you,String me,Pick go){
        boolean mine=me.equals(m.optString("id")),open=mine||m.optBoolean("share_progress");Integer s=score(m,"lifting_score");String name=m.optString("name");
        LinearLayout row=ui.row();row.setGravity(Gravity.CENTER_VERTICAL);row.setPadding(ui.dp(10),ui.dp(12),ui.dp(14),ui.dp(12));
        row.setBackground(ui.pressable(new AthleteFace(ui,hue(ui,s),mine?ui.accent:ui.stroke),18));
        TextView place=ui.type(String.valueOf(index+1),14,18,700,0,ui.muted);place.setFontFeatureSettings("tnum");place.setGravity(Gravity.CENTER);row.addView(place,new LinearLayout.LayoutParams(ui.dp(20),-2));
        Avatar face=new Avatar(ui,name,s,46,false);LinearLayout.LayoutParams fp=face.params();fp.setMarginStart(ui.dp(8));row.addView(face,fp);
        LinearLayout words=ui.column();
        LinearLayout head=ui.row();head.setGravity(Gravity.CENTER_VERTICAL);
        head.addView(single(ui.type(name,15.5f,20,750,0,ui.text)),new LinearLayout.LayoutParams(-2,-2,1));
        if(mine)head.addView(tag(ui,"You",true),at(ui,-2,-2,6,0));
        if(!open)head.addView(tag(ui,"Private",false),at(ui,-2,-2,6,0));
        words.addView(head,new LinearLayout.LayoutParams(-2,-2));
        SpannableStringBuilder meta=new SpannableStringBuilder(tierName(s));
        meta.setSpan(new ForegroundColorSpan(ink(ui,s)),0,meta.length(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);meta.setSpan(new RichText.Face(Markdown.BOLD),0,meta.length(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        meta.setSpan(new android.text.style.RelativeSizeSpan(1.125f),0,meta.length(),Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        Integer run=score(m,"running_score");if(run!=null)meta.append("   Running ").append(WorkoutViews.label(run));
        TextView metaView=ui.type("",12,18,400,0,ui.muted);metaView.setText(meta);words.addView(metaView,at(ui,-1,-2,0,2));
        JSONObject sprint=m.optJSONObject("current_sprint");
        if(sprint!=null){int target=sprint.optInt("target_sessions"),done=sprint.optInt("completed");
            words.addView(single(ui.type(sprint.optString("name")+" · "+done+(target>0?" of "+target:""),12,16,400,0,ui.muted)),at(ui,-1,-2,0,4));
            if(target>0)words.addView(progress(ui,done/(float)target),at(ui,-1,ui.dp(5),0,4));}
        row.addView(words,MainParts.weighted(ui,1,12,0,0,0));
        Integer yours=score(you,"lifting_score");String gap="";
        if(!mine&&s!=null&&yours!=null){int d=s-yours;row.addView(delta(ui,d),at(ui,-2,-2,10,0));gap=d>0?", "+d+" points ahead of you":d<0?", "+(-d)+" points behind you":", level with you";}
        if(!open)row.setAlpha(.72f);
        row.setContentDescription((index+1)+". "+name+(mine?", you":"")+", "+tierName(s)+gap+(open?"":", private"));
        row.setOnClickListener(v->go.go(m));AppUi.press(row);
        return row;
    }
    private static TextView tag(AppUi ui,String text,boolean accent){
        TextView t=ui.type(text,10.5f,15,750,0,accent?ui.onAccent:ui.muted);t.setPadding(ui.dp(7),ui.dp(2),ui.dp(7),ui.dp(2));t.setBackground(ui.outline(accent?ui.accent:ui.surfaceAlt,8,0,0));t.setSingleLine(true);return t;
    }
    /** How far an athlete is from you: ahead in warning colours, behind in success colours. */
    static TextView delta(AppUi ui,int d){
        int fg=d>0?ui.warning:d<0?ui.success:ui.muted,bg=d>0?ui.warningSoft:d<0?ui.successSoft:ui.surfaceAlt;
        TextView t=ui.type(d==0?"Level":(d>0?"+":"−")+Math.abs(d),13,17,800,0,fg);t.setFontFeatureSettings("tnum");t.setSingleLine(true);t.setPadding(ui.dp(8),ui.dp(4),ui.dp(8),ui.dp(4));t.setBackground(ui.outline(bg,10,0,0));return t;
    }
    static View progress(AppUi ui,float f){
        FrameLayout track=new FrameLayout(ui.context);track.setBackground(ui.outline(ui.stroke,4,0,0));track.setClipToOutline(true);
        View fill=new View(ui.context);fill.setBackground(ui.aurora(0,false));fill.setPivotX(0);fill.setScaleX(Math.max(0,Math.min(1,f)));track.addView(fill,new FrameLayout.LayoutParams(-1,-1));return track;
    }
    /** Card face washed with the athlete's tier from the left, with a tier stripe on the leading edge. */
    static final class AthleteFace extends Drawable {
        final AppUi ui;final int tier,edge;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);final Path path=new Path();final RectF r=new RectF();
        AthleteFace(AppUi ui,int tier,int edge){this.ui=ui;this.tier=tier;this.edge=edge;}
        @Override public void draw(Canvas c){
            Rect b=getBounds();float rad=ui.dpf(18),line=Math.max(1,ui.dpf(1));r.set(b);path.reset();path.addRoundRect(r,rad,rad,Path.Direction.CW);
            c.save();c.clipPath(path);p.setStyle(Paint.Style.FILL);
            p.setShader(new LinearGradient(b.left,0,b.right,0,new int[]{AppUi.mix(ui.surface,tier,.12f),ui.surface},new float[]{0,.46f},Shader.TileMode.CLAMP));c.drawRect(r,p);p.setShader(null);
            p.setColor(tier);c.drawRect(b.left,b.top,b.left+ui.dpf(3),b.bottom,p);c.restore();
            p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(line);p.setColor(edge);r.inset(line/2,line/2);c.drawRoundRect(r,rad,rad,p);
        }
        @Override public void setAlpha(int alpha){}
        @Override public void setColorFilter(ColorFilter filter){}
        @Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
        @Override public void getOutline(Outline outline){outline.setRoundRect(getBounds(),ui.dpf(18));}
    }

    /** A friend's hero: night gradient lit by their tier colour, their monogram, how strong they are and three headline stats. */
    static View athleteHero(AppUi ui,JSONObject d){
        JSONObject ranks=d.optJSONObject("ranks");Integer s=score(ranks,"lifting_score");int glow=s==null?AppUi.mix(NIGHT,Color.WHITE,.35f):WorkoutViews.bright(WorkoutViews.tierOf(s));
        LinearLayout h=ui.column();h.setPadding(ui.dp(16),ui.dp(18),ui.dp(16),ui.dp(14));h.setBackground(new HeroFace(ui,glow));h.setTag("friend_hero");
        LinearLayout top=ui.row();top.setGravity(Gravity.CENTER_VERTICAL);
        Avatar face=new Avatar(ui,d.optString("name"),s,72,true);top.addView(face,face.params());
        LinearLayout words=ui.column();TextView name=ui.type(d.optString("name"),24,30,850,-.02f,Color.WHITE);name.setMaxLines(2);name.setEllipsize(TextUtils.TruncateAt.END);words.addView(name);
        words.addView(single(ui.type(tierName(s),17,23,800,0,s==null?LILAC:AppUi.mix(glow,Color.WHITE,.15f))),at(ui,-1,-2,0,2));
        JSONArray lifts=ranks==null?null:ranks.optJSONArray("lifts");double sum=0;int n=0;
        for(int i=0;lifts!=null&&i<lifts.length();i++){JSONObject l=lifts.optJSONObject(i);if(l!=null&&l.has("percentile")&&!l.isNull("percentile")){sum+=l.optDouble("percentile");n++;}}
        if(n>0)words.addView(ui.type("Stronger than about "+Math.round(sum/n)+"% of lifters",12.5f,17,400,0,LILAC),at(ui,-1,-2,0,3));
        top.addView(words,MainParts.weighted(ui,1,12,0,0,0));h.addView(top);
        int done=0;JSONArray sprints=d.optJSONArray("sprints");for(int i=0;sprints!=null&&i<sprints.length();i++){JSONObject x=sprints.optJSONObject(i);if(x!=null&&"completed".equals(x.optString("status")))done++;}
        JSONObject running=ranks==null?null:ranks.optJSONObject("running");String runTier=running==null?"":running.optString("tier","");
        LinearLayout stats=ui.row();
        stats.addView(heroStat(ui,String.valueOf(d.optInt("completed_workouts")),"workouts"),new LinearLayout.LayoutParams(0,-2,1));
        stats.addView(heroStat(ui,String.valueOf(done),"sprints"),MainParts.weighted(ui,1,8,0,0,0));
        stats.addView(heroStat(ui,runTier.isEmpty()?"—":runTier,"running"),MainParts.weighted(ui,1,8,0,0,0));
        h.addView(stats,at(ui,-1,-2,0,14));
        return h;
    }
    private static View heroStat(AppUi ui,String value,String label){
        LinearLayout c=ui.column();c.setPadding(ui.dp(10),ui.dp(8),ui.dp(10),ui.dp(8));c.setBackground(ui.outline(0x1AFFFFFF,14,0,0));
        c.addView(fit(single(ui.type(value,17,0,800,0,Color.WHITE)),11,17),new LinearLayout.LayoutParams(-1,ui.dp(22)));c.addView(single(ui.type(label,11.5f,15,500,0,LILAC)));c.setContentDescription(value+" "+label);return c;
    }
    /** Night at 150°, warming to the tier colour, with a tier glow in the top corner. */
    static final class HeroFace extends Drawable {
        final AppUi ui;final int glow;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);final RectF r=new RectF();
        HeroFace(AppUi ui,int glow){this.ui=ui;this.glow=glow;}
        @Override public void draw(Canvas c){
            Rect b=getBounds();r.set(b);float rad=ui.dpf(24),w=b.width(),h=b.height(),cx=b.exactCenterX(),cy=b.exactCenterY(),dx=.5f,dy=.866f,half=Math.abs(w/2*dx)+Math.abs(h/2*dy);
            p.setShader(new LinearGradient(cx-dx*half,cy-dy*half,cx+dx*half,cy+dy*half,new int[]{0xFF2A1460,NIGHT,AppUi.mix(NIGHT,glow,.4f)},new float[]{0,.6f,1},Shader.TileMode.CLAMP));c.drawRoundRect(r,rad,rad,p);
            p.setShader(new RadialGradient(b.right,b.top,Math.max(1,w*.9f),new int[]{AppUi.alpha(glow,.55f),AppUi.alpha(glow,0)},new float[]{0,.7f},Shader.TileMode.CLAMP));c.drawRoundRect(r,rad,rad,p);p.setShader(null);
        }
        @Override public void setAlpha(int alpha){}
        @Override public void setColorFilter(ColorFilter filter){}
        @Override public int getOpacity(){return PixelFormat.TRANSLUCENT;}
        @Override public void getOutline(Outline outline){outline.setRoundRect(getBounds(),ui.dpf(24));}
    }

    /** Equal segments in a tray; the selected one is a raised surface. */
    static View tabs(AppUi ui,String[] labels,int selected,IntConsumer pick){
        LinearLayout row=ui.row();row.setPadding(ui.dp(3),ui.dp(3),ui.dp(3),ui.dp(3));row.setBackground(ui.outline(ui.surfaceAlt,14,0,0));
        for(int i=0;i<labels.length;i++){final int index=i;boolean on=i==selected;
            TextView t=single(ui.type(labels[i],13.5f,0,on?750:600,0,on?ui.text:ui.muted));t.setGravity(Gravity.CENTER);t.setPadding(ui.dp(4),0,ui.dp(4),0);
            fit(t,11,14);
            t.setBackground(on?ui.outline(ui.surface,11,ui.stroke,1):ui.pressable(null,11));t.setSelected(on);t.setContentDescription(labels[i]+" tab"+(on?", selected":""));
            t.setOnClickListener(v->{if(!on)pick.accept(index);});row.addView(t,new LinearLayout.LayoutParams(0,ui.dp(38),1));}
        return row;
    }

    /** The ridge with a label over it; `you` pins your own camp. */
    static View ridgeCard(AppUi ui,int current,int you,String kicker,String title){
        FrameLayout top=new FrameLayout(ui.context);top.addView(new WorkoutViews.Ridge(ui,current,you),new FrameLayout.LayoutParams(-1,-1));
        LinearLayout on=ui.column();on.setPadding(ui.dp(12),ui.dp(10),ui.dp(12),0);on.addView(single(ui.type(kicker,12,16,600,0,LILAC)));on.addView(single(ui.type(title,25,31,800,-.02f,GOLD)));top.addView(on,new FrameLayout.LayoutParams(-1,-2));
        top.setClipToOutline(true);top.setBackground(ui.outline(ui.surface,18,0,0));top.setContentDescription(kicker+" "+title);return top;
    }

    /** You against them: the ridge with both of you on it, then overall, running and each shared lift as a pair of bars. */
    static List<View> versus(AppUi ui,JSONObject d,JSONObject o){
        List<View> out=new ArrayList<>();JSONObject theirs=d.optJSONObject("ranks");if(theirs==null)theirs=new JSONObject();if(o==null)o=new JSONObject();
        Integer mine=score(o,"aggregate_score"),their=score(theirs,"lifting_score");String name=d.optString("name");int them=hue(ui,their);
        out.add(ridgeCard(ui,their==null?-1:WorkoutViews.tierOf(their),mine==null?-1:WorkoutViews.tierOf(mine),name+" climbs at",tierName(their)));
        List<Object[]> rows=new ArrayList<>();rows.add(new Object[]{"Overall",mine,their,null,null});
        JSONObject myRunning=o.optJSONObject("running"),myRun=myRunning==null?null:myRunning.optJSONObject("rank"),theirRun=theirs.optJSONObject("running");
        Integer ra=score(myRun,"score"),rb=score(theirRun,"score");
        if(ra!=null||rb!=null)rows.add(new Object[]{"Running",ra,rb,serverTier(myRun),serverTier(theirRun)});
        Map<String,JSONObject> mineBy=new HashMap<>();JSONArray myLifts=o.optJSONArray("lift_ranks");
        for(int i=0;myLifts!=null&&i<myLifts.length();i++){JSONObject r=myLifts.optJSONObject(i);if(r!=null&&"ranked".equals(r.optString("status")))mineBy.put(shortName(r.optString("exercise_name",r.optString("name"))).toLowerCase(Locale.ROOT),r);}
        JSONArray lifts=theirs.optJSONArray("lifts");
        for(int i=0;lifts!=null&&i<lifts.length();i++){JSONObject l=lifts.optJSONObject(i);if(l==null)continue;String lift=shortName(l.optString("exercise_name",l.optString("name")));JSONObject m=mineBy.get(lift.toLowerCase(Locale.ROOT));
            rows.add(new Object[]{lift,score(m,"score"),score(l,"score"),serverTier(m),serverTier(l)});}
        int both=0,won=0,lost=0;for(int i=1;i<rows.size();i++){Integer a=(Integer)rows.get(i)[1],b=(Integer)rows.get(i)[2];if(a!=null&&b!=null){both++;if(a>b)won++;else if(a<b)lost++;}}
        String verdict=both==0?"Rank the same lifts to compare":won>lost?"You lead "+won+" of "+both:lost>won?name+" leads "+lost+" of "+both:"Dead even across "+both;
        LinearLayout card=WorkoutViews.card(ui);card.setTag("friend_versus");
        LinearLayout head=ui.row();head.setGravity(Gravity.CENTER_VERTICAL);
        head.addView(side(ui,"You",ui.accent,false),new LinearLayout.LayoutParams(-2,-2));
        TextView call=ui.type(verdict,16,21,850,-.01f,ui.text);call.setGravity(Gravity.CENTER);call.setMaxLines(3);call.setEllipsize(TextUtils.TruncateAt.END);head.addView(call,MainParts.weighted(ui,1,8,0,8,0));
        head.addView(side(ui,name,them,true),new LinearLayout.LayoutParams(-2,-2));card.addView(head,at(ui,-1,-2,0,0));
        for(Object[] r:rows)card.addView(vsRow(ui,(String)r[0],(Integer)r[1],(Integer)r[2],(String)r[3],(String)r[4],them,r==rows.get(0)));
        out.add(card);
        JSONObject sprint=d.optJSONObject("current_sprint");int target=sprint==null?0:sprint.optInt("target_sessions");
        if(target>0){LinearLayout c=WorkoutViews.card(ui);c.addView(ui.type("Their sprint",12.5f,17,600,0,ui.muted));c.addView(single(ui.type(sprint.optString("name"),16,22,750,0,ui.text)),at(ui,-1,-2,0,2));
            c.addView(ui.type(sprint.optInt("completed")+" of "+target+" workouts",12.5f,17,400,0,ui.muted),at(ui,-1,-2,0,2));c.addView(progress(ui,sprint.optInt("completed")/(float)target),at(ui,-1,ui.dp(6),0,8));out.add(c);}
        return out;
    }
    /** The server's tier name for a rank, or nothing when it has none. */
    private static String serverTier(JSONObject rank){if(rank==null||rank.isNull("tier"))return null;String t=rank.optString("tier","");return t.isEmpty()?null:t;}
    private static View side(AppUi ui,String label,int color,boolean trailing){
        LinearLayout s=ui.row();s.setGravity(Gravity.CENTER_VERTICAL);View swatch=new View(ui.context);swatch.setBackground(ui.outline(color,3,0,0));
        TextView t=single(ui.type(label,12,16,750,0,ui.muted));t.setMaxWidth(ui.dp(trailing?72:40));
        LinearLayout.LayoutParams sp=new LinearLayout.LayoutParams(ui.dp(10),ui.dp(10));
        if(trailing){s.addView(t);sp.setMarginStart(ui.dp(6));s.addView(swatch,sp);}else{s.addView(swatch,sp);LinearLayout.LayoutParams tp=new LinearLayout.LayoutParams(-2,-2);tp.setMarginStart(ui.dp(6));s.addView(t,tp);}
        return s;
    }
    private static View vsRow(AppUi ui,String name,Integer a,Integer b,String ta,String tb,int them,boolean lead){
        LinearLayout row=ui.column();
        View rule=new View(ui.context);rule.setBackgroundColor(ui.stroke);row.addView(rule,new LinearLayout.LayoutParams(-1,Math.max(1,ui.dp(1))));
        LinearLayout title=ui.row();title.setGravity(Gravity.BOTTOM);
        title.addView(single(ui.type(name,lead?15.5f:14,20,lead?750:700,0,ui.text)),new LinearLayout.LayoutParams(0,-2,1));
        Integer diff=a!=null&&b!=null?a-b:null;
        TextView tag=single(ui.type(diff==null?"Not both ranked":diff==0?"Level":(diff>0?"+":"−")+Math.abs(diff)+" pts",12,16,750,0,diff==null||diff==0?ui.muted:diff>0?ui.success:ui.warning));tag.setFontFeatureSettings("tnum");
        title.addView(tag,at(ui,-2,-2,8,0));row.addView(title,at(ui,-1,-2,0,9));
        int top=Math.max(a==null?0:a,b==null?0:b);if(top==0)top=1;int low=a!=null&&b!=null?Math.max(0,Math.min(a,b)-60):0;
        LinearLayout pair=ui.row();pair.setGravity(Gravity.CENTER_VERTICAL);
        TextView left=single(ui.type(a==null?"—":ta!=null?ta:WorkoutViews.label(a),11,0,500,0,ui.muted));left.setGravity(Gravity.CENTER_VERTICAL);pair.addView(fit(left,9,11),new LinearLayout.LayoutParams(ui.dp(64),ui.dp(15)));
        LinearLayout.LayoutParams mine=MainParts.weighted(ui,1,6,0,0,0),theirs=MainParts.weighted(ui,1,4,0,0,0);mine.height=theirs.height=ui.dp(10);
        pair.addView(new VsBar(ui,fraction(a,low,top),ui.accent,true),mine);pair.addView(new VsBar(ui,fraction(b,low,top),them,false),theirs);
        TextView right=single(ui.type(b==null?"—":tb!=null?tb:WorkoutViews.label(b),11,0,500,0,ui.muted));right.setGravity(Gravity.END|Gravity.CENTER_VERTICAL);pair.addView(fit(right,9,11),MainParts.params(ui,ui.dp(64),ui.dp(15),6,0,0,0));
        row.addView(pair,at(ui,-1,-2,0,6));row.setPadding(0,0,0,ui.dp(9));
        row.setContentDescription(name+": you "+(a==null?"unranked":ta!=null?ta:WorkoutViews.label(a))+", them "+(b==null?"unranked":tb!=null?tb:WorkoutViews.label(b))+", "+tag.getText());
        return row;
    }
    /** Bars start a little below the lower score, so a 20-point gap reads as a gap rather than two full bars. */
    private static float fraction(Integer v,int low,int top){return v==null?0:Math.max(.04f,Math.min(1,(v-low)/(float)Math.max(1,top-low)));}
    /** Half of a head-to-head pair: yours grows leftwards from the centre, theirs rightwards. */
    static final class VsBar extends View {
        final AppUi ui;final float f;final int color;final boolean fromRight;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);final RectF r=new RectF();
        VsBar(AppUi ui,float f,int color,boolean fromRight){super(ui.context);this.ui=ui;this.f=f;this.color=color;this.fromRight=fromRight;setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);}
        @Override protected void onDraw(Canvas c){
            float w=getWidth(),h=getHeight(),rad=h/2;p.setColor(ui.surfaceAlt);r.set(0,0,w,h);c.drawRoundRect(r,rad,rad,p);
            if(f<=0)return;float len=Math.max(h,f*w);p.setColor(color);if(fromRight)r.set(w-len,0,w,h);else r.set(0,0,len,h);c.drawRoundRect(r,rad,rad,p);
        }
    }
}
