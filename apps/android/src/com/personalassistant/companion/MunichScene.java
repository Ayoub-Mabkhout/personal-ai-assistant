package com.personalassistant.companion;

import android.graphics.*;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.List;
import java.util.Locale;

/**
 * Munich's old town for the Meridian hero, drawn instead of the Alpine ridges while the Daylight place is Munich: the
 * Neues Rathaus with its Glockenspiel and Münchner Kindl on the left; the Frauenkirche, its nave and Alter Peter on the
 * right; and behind the orb the Theatinerkirche, gabled Altstadt houses, a maypole, the Mariensäule and the square.
 * Everything is lit by the hero's own sky: lit and shaded faces turned to the sun's side, distance haze, floodlights and
 * lit windows after dark, snow on roofs and ledges, and wet paving that mirrors the city. The season changes the trees,
 * window boxes and the square (café umbrellas, fallen leaves, the Christkindlmarkt in Advent).
 *
 * <p>The scene is designed in a 720 x 640 space. Buildings' bases sit at y 528, and the scale puts them 88.5% of the
 * way down the hero, with the towers reaching half the hero height above. It is rendered into a transparent bitmap off
 * the main thread whenever the light, weather or season changes; only Christmas lights and falling leaves or petals
 * are drawn every frame.
 */
final class MunichScene {
    static final int SPRING=0,SUMMER=1,AUTUMN=2,WINTER=3;
    private static final double LAT=48.1374,LON=11.5755;
    private static final int WHITE=0xFFFFFFFF,BLACK=0xFF000000;
    private static final RectF BIG=new RectF(-700,-500,1400,1300);
    /** Per landmark, its horizontal place in the hero layout (design units). */
    private static final float RATHAUS=51,OLYMP=51,THEATINER=230,FRAUEN=330,PETER=300,HOUSES=-66,MAIBAUM=130,MARIEN=230,SQUARE=250;
    private static final float[][] LAMPS={{96,578,28},{300,575,28},{524,578,28},{664,580,28}},TREES={{14,612,1.2f,91},{538,618,1f,93}};
    private static final float[][] HOUSE_ROW={{296,30,5,0xE9C47C,0,0x4F7A5A},{326,27,4,0xE6A797,1,-1},{353,33,5,0xCADBC6,2,0x3E6A55},{386,40,4,0xF0E3C8,0,0x7A5A3A},
        {426,30,5,0xE2B4A0,0,0x4F7A5A},{456,30,4,0xD6E0C4,1,-1},{486,30,5,0xF2D49A,2,0x3E6A55},{516,44,4,0xE6DCE8,0,0x6A5A7A}};

    /** Preview overrides from the launcher extras meridian_scene ("munich" or "alps") and meridian_season. */
    static volatile String previewScene,previewSeason;

    static boolean applies(MeridianSky sky){
        if(previewScene!=null)return "munich".equals(previewScene);
        String p=sky.place.toLowerCase(Locale.ROOT);
        if(p.contains("münchen")||p.contains("muenchen")||p.contains("munich"))return true;
        return sky.located&&distanceKm(sky.latitude,sky.longitude)<20;
    }
    static double distanceKm(double lat,double lon){
        double dLat=Math.toRadians(lat-LAT),dLon=Math.toRadians(lon-LON),a=Math.sin(dLat/2)*Math.sin(dLat/2)+Math.cos(Math.toRadians(LAT))*Math.cos(Math.toRadians(lat))*Math.sin(dLon/2)*Math.sin(dLon/2);
        return 6371*2*Math.atan2(Math.sqrt(a),Math.sqrt(1-a));
    }
    static int season(long at){
        String p=previewSeason;if(p!=null){switch(p){case "spring":return SPRING;case "summer":return SUMMER;case "autumn":return AUTUMN;case "winter":case "advent":return WINTER;default:}}
        Calendar c=Calendar.getInstance();c.setTimeInMillis(at);int m=c.get(Calendar.MONTH);return m<=Calendar.FEBRUARY||m==Calendar.DECEMBER?WINTER:m<=Calendar.MAY?SPRING:m<=Calendar.AUGUST?SUMMER:AUTUMN;
    }
    /** The Christkindlmarkt runs from late November to Christmas Eve. */
    static boolean advent(long at){
        if(previewSeason!=null)return "advent".equals(previewSeason);
        Calendar c=Calendar.getInstance();c.setTimeInMillis(at);int m=c.get(Calendar.MONTH),d=c.get(Calendar.DAY_OF_MONTH);return m==Calendar.NOVEMBER&&d>=24||m==Calendar.DECEMBER&&d<=24;
    }
    /** Changes whenever the drawing would: half-degree sun steps, weather, season, snow and size. */
    static String key(MeridianSky sky,int w,int h){
        int season=season(sky.at);return w+"x"+h+"|"+Math.round(sky.elevation*2)+"|"+sky.kind+"|"+Math.round(sky.cover*4)+"|"+season+"|"+advent(sky.at)+"|"+(sky.sunX<.5f)+"|"+snowCover(sky,season)+"|"+sky.morning;
    }
    private static float snowCover(MeridianSky sky,int season){return sky.kind==MeridianSky.SNOW?1:season==WINTER&&!Float.isNaN(sky.tempC)&&sky.tempC<=2?.72f:0;}

    /** A finished rendering: the transparent city bitmap and what animates over it. */
    static final class Rendered {
        final Bitmap city;final int w,h,season;final float s,ox,oy,glow;final float[][] lights,drift;final int[] driftColors;
        Rendered(Bitmap city,int w,int h,float s,float ox,float oy,float[][] lights,float[][] drift,int[] driftColors,int season,float glow){
            this.city=city;this.w=w;this.h=h;this.s=s;this.ox=ox;this.oy=oy;this.lights=lights;this.drift=drift;this.driftColors=driftColors;this.season=season;this.glow=glow;
        }
    }

    static Rendered render(MeridianSky sky,int w,int h){return new MunichScene(sky,w,h).draw();}

    /** Christmas lights twinkle in place; leaves or petals drift across the hero. Called every frame. */
    static void live(Canvas c,Rendered r,float time,Paint p){
        if(r==null)return;
        if(r.lights.length>0){c.save();c.translate(r.ox,r.oy);c.scale(r.s,r.s);
            for(float[] l:r.lights){float tw=.55f+.45f*(float)Math.sin(time*.0023f+l[2]*3);boolean star=l[3]>0;float a=star?1:(.5f+.5f*tw)*r.glow*l[4];
                if(r.glow>.5f){p.setShader(null);p.setColor(al(0xFFFFCE78,.3f*tw*Math.min(1,r.glow)));c.drawCircle(l[0],l[1],star?6:2.6f,p);}
                p.setColor(star?0xFFFFECAA:al(mx(0xFFFFC478,0xFFFFE6A8,l[2]%1),a));c.drawCircle(l[0],l[1],star?2.2f:.85f,p);}
            c.restore();}
        if(r.drift.length==0)return;
        float k=r.h/640f;
        for(float[] d:r.drift){float y=((d[1]*r.h+time*.001f*d[3]*k)%(r.h+20))-10,x=d[0]*r.w+(float)Math.sin(time*.0009f+d[2])*20*k+(r.season==AUTUMN?-1:1)*time*.008f*k;x=((x%r.w)+r.w)%r.w;
            c.save();c.translate(x,y);c.rotate((float)Math.toDegrees(time*.0015f+d[2]));
            if(r.season==AUTUMN)c.scale(1,Math.abs((float)Math.sin(time*.002f+d[2]))+.2f);
            p.setShader(null);p.setColor(r.season==AUTUMN?r.driftColors[(int)d[4]]:al(r.driftColors[0],.9f));
            float rx=(r.season==AUTUMN?2.6f:1.6f)*k,ry=(r.season==AUTUMN?1.3f:.9f)*k;c.drawOval(-rx,-ry,rx,ry,p);c.restore();}
    }

    // ------------------------------------------------------------------ environment

    private final MeridianSky sky;private final int w,h,season;private final boolean xmas,sunLeft,wet,clearish;
    private final float s,ox,oy,direct,haze,flood,snow,winLit,dayF,xmasGlow,kFront,kSide,kLeft;private final boolean lampsOn;
    private final int ambient,sunCol,horizon;private final int[] skyc;
    private Canvas c;private final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG),st=new Paint(Paint.ANTI_ALIAS_FLAG);private final List<float[]> lights=new ArrayList<>();

    private MunichScene(MeridianSky sky,int w,int h){
        this.sky=sky;this.w=w;this.h=h;season=season(sky.at);xmas=advent(sky.at)&&season==WINTER;
        double e=sky.elevation;skyc=sky.sky;horizon=skyc[2];sunLeft=sky.sunX<.5f;int kind=sky.kind;
        s=h*.5f/342;ox=w/2f-360*s;oy=h*.885f-528*s;
        float des=kind==MeridianSky.RAIN?.62f:kind==MeridianSky.SNOW?.45f:kind==MeridianSky.CLOUDY?Math.max(.3f,sky.desaturate):sky.desaturate;
        int aT=sky.morning?0xFFA28FCB:0xFFA986B8,sT=sky.morning?0xFFFFCDBF:0xFFFFB27A;float dT=sky.morning?.72f:1;
        ambient=MeridianSky.mix(twilight(e,0xFF2C2556,aT,0xFFD6CDF0),0xFFB2ACC0,des*.55f);sunCol=twilight(e,0xFF8A84CC,sT,0xFFFFF8EC);
        float dir=e>=12?.92f:e>=0?dT+(.92f-dT)*MeridianSky.smooth(0,12,e):.08f+(dT-.08f)*MeridianSky.smooth(-10,0,e);
        clearish=kind==MeridianSky.CLEAR;
        direct=dir*(kind==MeridianSky.CLEAR?1-.5f*Math.max(0,sky.cover-.3f):kind==MeridianSky.CLOUDY?.42f:kind==MeridianSky.RAIN?.16f:.3f);
        float dark=1-MeridianSky.smooth(-8,6,e);dayF=MeridianSky.smooth(-6,10,e);
        haze=(kind==MeridianSky.CLEAR?.5f:kind==MeridianSky.CLOUDY?.62f:kind==MeridianSky.RAIN?.8f:.74f)*(1-.4f*dark);
        flood=MeridianSky.smooth(-1,-7,e);wet=kind==MeridianSky.RAIN;snow=snowCover(sky,season);
        winLit=.52f*dark+(season==WINTER&&e<10?.18f*(1-dark*.5f):0)+((kind==MeridianSky.RAIN||kind==MeridianSky.SNOW)&&e<20?.08f:0);
        lampsOn=e<3||(kind!=MeridianSky.CLEAR&&e<8);xmasGlow=dark>.5f?1:e<8?.75f:.25f;
        kFront=sunLeft?.72f:.6f;kSide=sunLeft?.2f:1;kLeft=sunLeft?1:.3f;
        st.setStyle(Paint.Style.STROKE);st.setStrokeCap(Paint.Cap.ROUND);
    }
    private static int twilight(double e,int night,int twi,int day){if(e>=12)return day;if(e>=0)return MeridianSky.mix(twi,day,MeridianSky.smooth(0,12,e));if(e>=-10)return MeridianSky.mix(night,twi,MeridianSky.smooth(-10,0,e));return night;}

    private Rendered draw(){
        Bitmap bld=Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888);c=new Canvas(bld);c.translate(ox,oy);c.scale(s,s);
        olympiaturm();theatiner();frauenkirche();rathaus();alterPeter();
        Bitmap city=Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888);c=new Canvas(city);c.translate(ox,oy);c.scale(s,s);
        ground();
        Paint img=new Paint(Paint.FILTER_BITMAP_FLAG);
        if(wet){Bitmap small=Bitmap.createScaledBitmap(bld,Math.max(1,w/5),Math.max(1,h/5),true);float mirror=oy+529*s;
            c.save();c.clipRect(-700,530,1400,800);c.setMatrix(null);c.translate(0,2*mirror);c.scale(1,-1);img.setAlpha(82);c.drawBitmap(small,null,new Rect(0,0,w,h),img);c.restore();img.setAlpha(255);small.recycle();}
        c.save();c.setMatrix(null);c.drawBitmap(bld,0,0,img);c.restore();
        layer(HOUSES,0,0,0,640,this::houses);layer(MAIBAUM,0,0,0,640,this::maibaum);
        c.save();c.translate(MARIEN,0);mariensaeule();c.restore();
        c.save();c.translate(SQUARE,0);if(xmas)christmas();else if(season!=WINTER)umbrellas();c.restore();
        for(float[] l:lights)l[0]+=SQUARE;
        for(float[] l:LAMPS)lamp(l[0],l[1],l[2]);
        people();
        for(float[] t:TREES)tree(t[0],t[1],t[2],(long)t[3]);
        if(wet&&lampsOn)for(float[] l:LAMPS){p.setShader(new LinearGradient(0,l[1],0,l[1]+30,0x80FFC878,0x00FFC878,Shader.TileMode.CLAMP));c.drawRect(l[0]-2.5f,l[1],l[0]+2.5f,l[1]+30,p);p.setShader(null);}
        if(lampsOn)for(float[] l:LAMPS){c.save();c.translate(l[0],l[1]);c.scale(1,.32f);p.setShader(new RadialGradient(0,0,30,al(0xFFFFC878,snow>0?.5f:.36f),0x00FFC878,Shader.TileMode.CLAMP));c.drawRect(-30,-30,30,30,p);p.setShader(null);c.restore();lampGlow(l[0],l[1]-l[2]-5,22);}
        bld.recycle();
        float[][] drift=new float[0][];int[] colors={0};
        if(season==AUTUMN&&sky.kind!=MeridianSky.RAIN&&sky.kind!=MeridianSky.SNOW){Rng r=new Rng(101);drift=new float[16][];colors=new int[]{surf(0xFFD9822B,.9f),surf(0xFFE6A93A,.9f),surf(0xFFB8502A,.9f),surf(0xFFC9A23A,.9f)};for(int i=0;i<16;i++)drift[i]=new float[]{r.f(),r.f(),r.f()*6.28f,14+r.f()*20,i%4};}
        else if(season==SPRING&&sky.kind!=MeridianSky.RAIN&&sky.kind!=MeridianSky.SNOW){Rng r=new Rng(102);drift=new float[22][];colors=new int[]{surf(0xFFFBE4EA,1.1f)};for(int i=0;i<22;i++)drift[i]=new float[]{r.f(),r.f(),r.f()*6.28f,10+r.f()*14,0};}
        return new Rendered(city,w,h,s,ox,oy,lights.toArray(new float[0][]),drift,colors,season,xmasGlow);
    }

    // ------------------------------------------------------------------ colour and drawing helpers

    static int al(int c,float a){return Math.round(Math.max(0,Math.min(1,a))*255)<<24|(c&0xFFFFFF);}
    static int mx(int a,int b,float t){t=Math.max(0,Math.min(1,t));int r=Math.round(((a>>16)&255)+(((b>>16)&255)-((a>>16)&255))*t),g=Math.round(((a>>8)&255)+(((b>>8)&255)-((a>>8)&255))*t),bl=Math.round((a&255)+((b&255)-(a&255))*t);return 0xFF000000|r<<16|g<<8|bl;}
    private static int mul(int a,int b){return 0xFF000000|(((a>>16)&255)*((b>>16)&255)/255)<<16|(((a>>8)&255)*((b>>8)&255)/255)<<8|((a&255)*(b&255)/255);}
    private int surf(int b,float k){b|=0xFF000000;return mx(mul(b,ambient),mul(b,sunCol),Math.max(0,Math.min(1,k*direct)));}
    private static final class Rng{long s;Rng(long seed){s=seed%2147483647;if(s<=0)s+=2147483646;}float f(){s=s*16807%2147483647;return (float)(s/2147483647d);}}

    private void rect(float x,float y,float rw,float rh,int col){p.setShader(null);p.setColor(col);c.drawRect(x,y,x+rw,y+rh,p);}
    private void circle(float x,float y,float r,int col){p.setShader(null);p.setColor(col);c.drawCircle(x,y,r,p);}
    private void oval(float cx,float cy,float rx,float ry,int col){p.setShader(null);p.setColor(col);c.drawOval(cx-rx,cy-ry,cx+rx,cy+ry,p);}
    private void half(float cx,float cy,float rx,float ry,boolean upper,int col){p.setShader(null);p.setColor(col);c.drawArc(cx-rx,cy-ry,cx+rx,cy+ry,upper?180:0,180,true,p);}
    private void ovalRot(float cx,float cy,float rx,float ry,float rad,int col){c.save();c.translate(cx,cy);c.rotate((float)Math.toDegrees(rad));oval(0,0,rx,ry,col);c.restore();}
    private void fill(Path q,int col){p.setShader(null);p.setColor(col);c.drawPath(q,p);}
    private void fill(Path q,Shader sh){p.setShader(sh);c.drawPath(q,p);p.setShader(null);}
    private static Path poly(float... xy){Path q=new Path();q.moveTo(xy[0],xy[1]);for(int i=2;i<xy.length;i+=2)q.lineTo(xy[i],xy[i+1]);q.close();return q;}
    private static Path lancet(float x,float y,float lw,float lh){Path q=new Path();q.moveTo(x,y+lh);q.lineTo(x,y+lw*.75f);q.quadTo(x,y+lw*.12f,x+lw/2,y);q.quadTo(x+lw,y+lw*.12f,x+lw,y+lw*.75f);q.lineTo(x+lw,y+lh);q.close();return q;}
    private static Path roundTop(float x,float y,float rw,float rh){Path q=new Path();q.moveTo(x,y+rh);q.lineTo(x,y+rw/2);q.arcTo(new RectF(x,y,x+rw,y+rw),180,180,false);q.lineTo(x+rw,y+rh);q.close();return q;}
    private static Shader hgrad(float x0,float x1,int[] cols,float[] pos){return new LinearGradient(x0,0,x1,0,cols,pos,Shader.TileMode.CLAMP);}
    private void line(float x0,float y0,float x1,float y1,int col,float width){st.setShader(null);st.setColor(col);st.setStrokeWidth(width);c.drawLine(x0,y0,x1,y1,st);}

    /** One building in its own layer: drawn lit, then hazed by distance and, after dark, floodlit from below. */
    private void layer(float dx,float hz,float fl,float top,float bottom,Runnable draw){
        int save=c.saveLayer(null,null);c.save();c.translate(dx,0);draw.run();c.restore();
        Paint o=new Paint();o.setXfermode(new PorterDuffXfermode(PorterDuff.Mode.SRC_ATOP));
        if(fl>0&&flood>0){float k=fl*flood;o.setShader(new LinearGradient(0,bottom,0,top,new int[]{al(0xFFFFA85C,.62f*k),al(0xFFFFBA78,.34f*k),al(0xFFFFCD96,.12f*k)},new float[]{0,.55f,1},Shader.TileMode.CLAMP));c.drawRect(BIG,o);o.setShader(null);}
        if(hz>0){o.setColor(al(horizon,Math.min(.9f,hz*haze)));c.drawRect(BIG,o);}
        c.restoreToCount(save);
    }
    private void texture(float x,float y,float tw,float th,int col,Rng r,int kind){
        c.save();c.clipRect(x,y,x+tw,y+th);
        if(kind==0){p.setColor(al(mx(col,BLACK,.35f),.22f));for(float yy=y;yy<y+th;yy+=2.4f)c.drawRect(x,yy,x+tw,yy+.42f,p);
            for(int i=0,n=(int)(tw*th/10);i<n;i++){p.setColor(al(mx(col,r.f()<.5f?0xFFFFD6BE:BLACK,.14f),.55f));float px=x+r.f()*tw,py=y+r.f()*th;c.drawRect(px,py,px+1.7f,py+1,p);}}
        else if(kind==1){p.setColor(al(mx(col,BLACK,.32f),.2f));int row=0;for(float yy=y+4;yy<y+th;yy+=4,row++){c.drawRect(x,yy,x+tw,yy+.4f,p);for(float xx=x+(row%2)*5;xx<x+tw;xx+=10)c.drawRect(xx,yy-4,xx+.4f,yy,p);}
            for(int i=0,n=(int)(tw*th/22);i<n;i++){p.setColor(al(mx(col,r.f()<.5f?WHITE:BLACK,.1f),.5f));float px=x+r.f()*tw,py=y+r.f()*th;c.drawRect(px,py,px+1.2f,py+1.2f,p);}}
        else for(int i=0,n=(int)(tw*th/26);i<n;i++){p.setColor(al(mx(col,r.f()<.45f?WHITE:BLACK,.07f),.55f));float px=x+r.f()*tw,py=y+r.f()*th;c.drawRect(px,py,px+.8f,py+2+r.f()*7,p);}
        c.restore();
    }
    private int glass(float k,boolean lit,Rng r){
        if(lit)return mx(0xFFFFBF62,0xFFFFE3A6,r.f());
        return mx(surf(0xFF2B2742,k),skyc[1],.28f*dayF*(clearish?1:.6f));
    }
    private void snowLine(float x,float y,float lw,float t){if(snow<=0)return;rect(x,y-t,lw,t,al(surf(0xFFF6F4FF,1.1f),.92f*snow));}
    private void dial(float x,float y,float r){
        circle(x,y,r,surf(0xFF22305A,.8f));int gold=surf(0xFFE5BC5C,1.1f);
        st.setStrokeCap(Paint.Cap.BUTT);st.setColor(gold);st.setStrokeWidth(Math.max(.6f,r*.14f));c.drawCircle(x,y,r,st);
        p.setColor(gold);for(int i=0;i<12;i++){double a=i*Math.PI/6;float tx=x+(float)Math.cos(a)*r*.72f,ty=y+(float)Math.sin(a)*r*.72f;c.drawRect(tx-.3f,ty-.3f,tx+.3f,ty+.3f,p);}
        st.setStrokeCap(Paint.Cap.ROUND);line(x,y,x+r*.35f,y-r*.45f,gold,.6f);line(x,y,x-r*.1f,y+r*.65f,gold,.6f);
    }
    private void tiles(Path q,float x0,float y0,float x1,float y1,int col,float k,Rng r){
        fill(q,surf(col,k));c.save();c.clipPath(q);
        for(int i=0,n=(int)((x1-x0)*(y1-y0)/9);i<n;i++){p.setColor(al(surf(mx(col,r.f()<.5f?0xFFFFCEA0:0xFF461E14,.2f),k),.45f));float px=x0+r.f()*(x1-x0),py=y0+r.f()*(y1-y0);c.drawRect(px,py,px+2+r.f()*5,py+1.3f,p);}
        p.setColor(al(surf(mx(col,BLACK,.4f),k),.4f));for(float y=y0;y<y1;y+=2.3f)c.drawRect(x0,y,x1,y+.55f,p);
        if(snow>0){rect(x0,y0,x1-x0,y1-y0,al(surf(0xFFF5F3FF,k+.35f),.86f*snow));p.setColor(al(surf(mx(col,BLACK,.25f),k),.22f*snow));
            for(int i=0,n=(int)((x1-x0)*(y1-y0)/40);i<n;i++){float px=x0+r.f()*(x1-x0),py=y0+r.f()*(y1-y0);c.drawRect(px,py,px+1.5f+r.f()*3,py+.8f,p);}}
        if(wet){p.setShader(new LinearGradient(0,y0,0,y1,0x1FFFFFFF,0x00FFFFFF,Shader.TileMode.CLAMP));c.drawRect(x0,y0,x1,y1,p);p.setShader(null);}
        c.restore();
    }

    // ------------------------------------------------------------------ landmarks

    private void olympiaturm(){layer(OLYMP,.7f,.3f,320,530,()->{
        int col=surf(0xFFC9C4D8,kFront),d=surf(0xFF8F8AA6,kFront);
        fill(poly(21,530,23.2f,372,25.8f,372,28,530),col);
        for(float[] b:new float[][]{{372,9,3},{366,11,4},{361,10,3},{357,8,2.5f}}){rect(24.5f-b[1],b[0]-b[2],b[1]*2,b[2],d);rect(24.5f-b[1],b[0]-b[2],b[1]*2,.7f,al(col,.8f));}
        rect(23.8f,326,1.4f,30,col);for(int y=330;y<354;y+=6)rect(23.8f,y,1.4f,3,surf(0xFFD2553F,.8f));
    });}
    private void theatiner(){layer(THEATINER,.85f,.8f,358,528,()->{
        int o=0xFFE2AC4C,wt=0xFFF3E8D2,cu=0xFF6E9F89,B=528,win=surf(0xFF3A2E40,.5f);
        rect(168,384,20,24,surf(o,kFront));for(int i=0;i<3;i++)fill(roundTop(171+i*6,389,2.6f,7),win);
        p.setShader(hgrad(166,190,new int[]{surf(cu,kLeft),surf(cu,kSide)},null));c.drawArc(166,370,190,398,180,180,true,p);p.setShader(null);
        rect(176,366,4,5,surf(wt,.8f));half(178,366,3,2.4f,true,surf(cu,.8f));rect(177.6f,358,.8f,6,surf(cu,.8f));
        Path f=new Path();f.moveTo(160,B);f.lineTo(160,404);f.quadTo(166,404,170,397);f.quadTo(178,388,186,397);f.quadTo(190,404,196,404);f.lineTo(196,B);f.close();fill(f,surf(o,kFront));
        int trim=surf(wt,kFront);rect(160,412,36,1.4f,trim);rect(163,404,1.6f,124,trim);rect(192.4f,404,1.6f,124,trim);circle(178,404,3,win);
        for(float cx:new float[]{155,201}){
            rect(cx-6,392,12,B-392,surf(o,kFront));rect(cx+6,392,3,B-392,surf(o,kSide));rect(cx-6,392,12,1.6f,trim);rect(cx-6,418,12,1.2f,trim);
            fill(roundTop(cx-1.6f,398,3.2f,10),win);rect(cx-4,384,8,8,surf(o,kFront));circle(cx-4,388,2.2f,trim);circle(cx+4,388,2.2f,trim);
            Path hm=new Path();hm.moveTo(cx-5,384);hm.cubicTo(cx-6,377,cx-2,375,cx-1.2f,370);hm.lineTo(cx+1.2f,370);hm.cubicTo(cx+2,375,cx+6,377,cx+5,384);hm.close();
            fill(hm,hgrad(cx-6,cx+6,new int[]{surf(cu,kLeft),surf(cu,kSide)},null));circle(cx,368.5f,1.6f,surf(cu,.8f));rect(cx-.35f,362,.7f,6,surf(cu,.8f));
        }
    });}
    private void frauenkirche(){layer(FRAUEN,.12f,1,186,528,()->{
        int brick=0xFF8E4936,B=528;Rng rT=new Rng(11),rW=new Rng(12);int cF=surf(brick,kFront);
        rect(300,422,240,B-422,cF);texture(300,422,240,B-422,cF,rT,0);
        for(float x=318;x<540;x+=22){boolean lit=rW.f()<(flood>.5f?.85f:winLit*.5f);fill(lancet(x-1.2f,436,9.4f,70),mx(cF,BLACK,.3f));
            fill(lancet(x,438,7,66),lit?al(mx(0xFFFFB45E,0xFFFFD79A,rW.f()),.85f):glass(kFront,false,rW));
            int lead=al(mx(cF,BLACK,.5f),.7f);line(x+3.5f,446,x+3.5f,504,lead,.5f);for(float yy=452;yy<504;yy+=11)line(x,yy,x+7,yy,lead,.5f);}
        rect(300,422,240,3,0x40000000);
        tiles(poly(300,423,540,423,540,330,326,330),300,330,540,423,0xFFA4533A,kFront+.08f,rT);
        for(float[] row:new float[][]{{348,0},{372,10},{398,0}})for(float x=332+row[1]+(398-row[0])*.1f;x<536;x+=20){float yy=row[0];
            fill(poly(x,yy+5,x+3.5f,yy,x+7,yy+5),surf(0xFF7C3A2A,kFront));rect(x+2.6f,yy+2.4f,1.8f,2.6f,surf(0xFF2A2030,.4f));
            if(snow>0)fill(poly(x-.5f,yy+4.6f,x+3.5f,yy-.6f,x+7.5f,yy+4.6f,x+6,yy+4.6f,x+3.5f,yy+1.2f,x+1,yy+4.6f),al(surf(0xFFF5F3FF,1),.9f*snow));}
        rect(326,329,214,1.2f,al(surf(0xFFC9725A,1.2f),.8f));
        Path west=poly(248,B,248,378,264,364,280,378,280,B);fill(west,cF);texture(248,364,32,B-364,cF,rT,0);
        fill(lancet(256,388,16,88),mx(cF,BLACK,.3f));fill(lancet(258,391,12,84),glass(kFront,false,rW));
        int lead=al(mx(cF,BLACK,.45f),.8f);for(float lx:new float[]{261,264,267})line(lx,398,lx,475,lead,.55f);for(float yy=405;yy<475;yy+=9)line(258,yy,270,yy,lead,.55f);
        for(float cx:new float[]{234,294})fkTower(cx,rT,brick);
    });}
    private void fkTower(float cx,Rng rT,int brick){
        float fw=28,sw=9,x0=cx-fw/2,top=262,B=528;int cF=surf(brick,kFront),cS=surf(brick,kSide),cL=surf(brick,kLeft);
        rect(x0+fw,top,sw,B-top,cS);texture(x0+fw,top,sw,B-top,cS,rT,0);rect(x0,top,fw,B-top,cF);texture(x0,top,fw,B-top,cF,rT,0);
        rect(x0,top,4.5f,38,cL);rect(x0+fw-4.5f,top,4.5f,38,mx(cS,BLACK,.08f));
        int lis=mx(cF,0xFFFFE2CE,.08f);rect(x0,300,2.2f,B-300,lis);rect(x0+fw-2.2f,300,2.2f,B-300,lis);
        float[] bands={300,346,394,442,488};
        for(int i=0;i<bands.length;i++){float yb=bands[i];
            rect(x0-1.2f,yb,fw+sw+1.2f,2.4f,mx(cF,BLACK,.3f));rect(x0-1.2f,yb-.5f,fw+1.2f,.8f,mx(cF,0xFFFFE8D6,.2f));snowLine(x0-1.2f,yb,fw+sw+1.2f,1.4f);
            float a=yb+6,b=(i+1<bands.length?bands[i+1]:B)-5;if(b-a<12)continue;
            for(float nx:new float[]{x0+5,x0+fw-11}){fill(lancet(nx,a,6,b-a),mx(cF,BLACK,.34f));fill(lancet(nx+2.2f,a+5,1.6f,b-a-10),mx(cF,BLACK,.62f));}
            fill(lancet(x0+fw+3,a,3,b-a),mx(cS,BLACK,.3f));
        }
        dial(cx,287,6.2f);fill(lancet(cx-2,266,4,13),mx(cF,BLACK,.55f));
        rect(x0-2.4f,top-3,fw+sw+4.8f,3.2f,mx(cF,BLACK,.25f));rect(x0-2.4f,top-3.4f,fw+sw+4.8f,.8f,mx(cF,0xFFFFE8D6,.25f));
        haube(x0+(fw+sw)/2-1,top-3);
    }
    private static Path haubeProfile(float cx,float by,float f){Path q=new Path();q.moveTo(cx+17*f,by);q.cubicTo(cx+22*f,by-9,cx+21*f,by-24,cx+14*f,by-32);q.cubicTo(cx+8*f,by-39,cx+5*f,by-42,cx+4*f,by-48);return q;}
    /** The Frauenkirche's "Welsche Hauben": copper helmets with a lantern, a gilded ball and spike. */
    private void haube(float cx,float by){
        int cu=0xFF5B9A82;Path q=new Path();q.moveTo(cx-17,by);q.cubicTo(cx-22,by-9,cx-21,by-24,cx-14,by-32);q.cubicTo(cx-8,by-39,cx-5,by-42,cx-4,by-48);q.lineTo(cx+4,by-48);
        q.cubicTo(cx+5,by-42,cx+8,by-39,cx+14,by-32);q.cubicTo(cx+21,by-24,cx+22,by-9,cx+17,by);q.close();
        int sh=surf(cu,.12f),md=surf(cu,.62f),li=surf(cu,1.15f);
        fill(q,sunLeft?hgrad(cx-21,cx+21,new int[]{md,li,md,sh},new float[]{0,.18f,.5f,1}):hgrad(cx-21,cx+21,new int[]{sh,md,li,md},new float[]{0,.55f,.82f,1}));
        c.save();c.clipPath(q);
        p.setShader(new LinearGradient(0,by-48,0,by,new int[]{0x1AFFFFFF,0x00000000,0x47000000},new float[]{0,.65f,1},Shader.TileMode.CLAMP));c.drawRect(cx-25,by-50,cx+25,by+2,p);p.setShader(null);
        st.setStrokeCap(Paint.Cap.BUTT);st.setColor(0x4D10282A);st.setStrokeWidth(.55f);for(float f:new float[]{-.66f,-.33f,0,.33f,.66f})c.drawPath(haubeProfile(cx,by,f),st);st.setStrokeCap(Paint.Cap.ROUND);
        Rng r=new Rng(Math.round(cx));p.setColor(al(mx(li,0xFFC8F0DC,.5f),.25f));for(int i=0;i<40;i++){float px=cx-20+r.f()*40,py=by-46+r.f()*44;c.drawRect(px,py,px+1.2f,py+.8f,p);}
        ovalRot(sunLeft?cx-12:cx+11,by-18,2,12,sunLeft?.16f:-.16f,al(mx(li,WHITE,.45f),.12f+.4f*direct));
        if(snow>0)half(cx,by-33,13,2.2f,true,al(surf(0xFFF6F4FF,1),.75f*snow));
        c.restore();
        rect(cx-3.4f,by-57,6.8f,9.2f,surf(cu,.6f));rect(cx-1.2f,by-55,2.4f,6,surf(0xFF1C2828,.4f));
        oval(cx,by-58,4.6f,2.6f,surf(cu,.85f));Path cap=new Path();cap.moveTo(cx-2.6f,by-59);cap.quadTo(cx,by-68,cx+2.6f,by-59);cap.close();fill(cap,surf(cu,.85f));
        int gold=surf(0xFFE8BE5C,1.2f);circle(cx,by-68.5f,1.35f,gold);rect(cx-.35f,by-74,.7f,5,gold);
    }
    private void gable(float cx,float base,float gw,float gh,int col,Rng rW,Rng rT){
        float L=cx-gw/2,R=cx+gw/2,sh=base-gh*.3f,top=base-gh;int cF=surf(col,kFront);
        fill(poly(L,base,L,sh,cx,top,R,sh,R,base),cF);
        c.save();c.clipPath(poly(L,base,L,sh,cx,top,R,sh,R,base));texture(L,top,gw,gh,cF,rT,1);c.restore();
        int edge=al(surf(mx(col,WHITE,.3f),1.1f),.85f);if(sunLeft)line(L,sh,cx,top,edge,.9f);else line(cx,top,R,sh,edge,.9f);
        int orn=surf(mx(col,WHITE,.25f),1);
        for(float f=.12f;f<.95f;f+=.17f){float x1=L+(cx-L)*f,y1=sh+(top-sh)*f,x2=R-(R-cx)*f;fill(poly(x1-1.4f,y1,x1-.2f,y1-2.6f,x1+.8f,y1),orn);fill(poly(x2-.8f,y1,x2+.2f,y1-2.6f,x2+1.4f,y1),orn);}
        rect(cx-.5f,top-9,1,9,orn);fill(poly(cx-1.6f,top-5,cx,top-11,cx+1.6f,top-5),orn);
        for(float px:new float[]{L,R}){rect(px-.6f,sh-8,1.2f,8,orn);fill(poly(px-1.3f,sh-6,px,sh-11,px+1.3f,sh-6),orn);}
        float lw=Math.min(8,gw*.32f);fill(lancet(cx-lw/2-1,top+gh*.3f,lw+2,gh*.5f),mx(cF,BLACK,.35f));
        boolean on=rW.f()<winLit;fill(lancet(cx-lw/2,top+gh*.33f,lw,gh*.46f),glass(kFront,on,rW));
    }
    private void rathaus(){layer(RATHAUS,.05f,.9f,234,528,()->{
        int stn=0xFF8B7F6E,B=528;Rng rT=new Rng(21),rW=new Rng(22);int cF=surf(stn,kFront),cS=surf(stn,kSide),trim=surf(0xFFC9BFAE,kFront);
        tiles(poly(-74,406,156,406,150,382,-68,382),-74,382,156,406,0xFF4F5666,kFront+.1f,rT);
        for(float[] g:new float[][]{{-46,26,38},{-12,22,32},{16,24,40},{52,30,48},{126,26,42},{150,18,32}})gable(g[0],408,g[1],g[2],stn,rW,rT);
        rect(-74,406,230,B-406,cF);texture(-74,406,230,B-406,cF,rT,1);rect(-74,406,230,2.2f,mx(cF,BLACK,.3f));
        for(float x=-72;x<156;x+=8)fill(poly(x-1,406,x,399,x+1,406),trim);
        for(float yy:new float[]{431,456,481,506}){rect(-74,yy,230,1.1f,al(trim,.9f));snowLine(-74,yy,230,.9f);}
        for(float yy:new float[]{412,437,462,487})for(float x=-72.5f;x<154;x+=10.5f){if(x>70&&x<110)continue;boolean on=rW.f()<winLit;
            fill(lancet(x-.8f,yy-.8f,7.4f,16.6f),trim);fill(lancet(x,yy,5.8f,15),glass(kFront,on,rW));
            int mu=al(trim,.85f);line(x+2.9f,yy+2,x+2.9f,yy+15,mu,.45f);line(x,yy+8,x+5.8f,yy+8,mu,.45f);}
        for(float x=-72;x<156;x+=12){if(x>66&&x<112)continue;fill(lancet(x,511,8,17),mx(cF,BLACK,.55f));if(lampsOn)fill(lancet(x+1,513,6,15),0x80FFC478);}
        float cx=89,fw=24,sw=7,x0=cx-fw/2,top=302;
        rect(x0+fw,top,sw,B-top,cS);rect(x0,top,fw,B-top,cF);texture(x0,top,fw+sw,B-top,cF,rT,1);rect(x0,top,1.4f,B-top,trim);rect(x0+fw-1.4f,top,1.4f,B-top,trim);
        for(float yy:new float[]{408,446,486})for(float wx:new float[]{x0+5,x0+fw-11}){boolean on=rW.f()<winLit;fill(lancet(wx-.7f,yy-.7f,7.4f,26),trim);fill(lancet(wx,yy,6,24),glass(kFront,on,rW));}
        for(float wx:new float[]{x0+5,x0+fw-11})fill(lancet(wx,308,6,30),mx(cF,BLACK,.45f));
        dial(cx,348,5.4f);
        float ox2=x0-4,ow=fw+8;rect(ox2,358,ow,40,mx(cF,WHITE,.06f));rect(ox2+ow,358,4,40,cS);fill(poly(ox2,398,ox2+ow+4,398,cx+2,410),mx(cF,BLACK,.2f));
        int[] figs={0xFFD0453B,0xFF2F5DB5,0xFFF1E6D0,0xFFE3B44E,0xFF3C8C5A,0xFFD0453B,0xFF2F5DB5,0xFFE3B44E};
        for(float[] bal:new float[][]{{362,11},{380,13}}){float yy=bal[0],hh=bal[1];rect(ox2+2.5f,yy,ow-5,hh,surf(0xFF241C2A,.4f));if(flood>.5f)rect(ox2+2.5f,yy,ow-5,hh,0x66FFBE6E);
            for(int i=0;i<7;i++){float fx=ox2+5+i*(ow-10)/6;rect(fx-1,yy+hh-6.5f,2,5.5f,surf(figs[(i+(int)yy)%8],1));circle(fx,yy+hh-7.4f,1,surf(0xFFF0D2B4,1));}
            int gold=surf(0xFFD9B25A,1);rect(ox2+1.5f,yy+hh-1.2f,ow-3,1.4f,gold);for(float x=ox2+3;x<ox2+ow-2;x+=2.4f)rect(x,yy+hh-3,.5f,2,gold);}
        rect(ox2-1,356,ow+6,2.2f,trim);for(float x=ox2;x<=ox2+ow;x+=ow/4){rect(x-.5f,349,1,7,trim);fill(poly(x-1.3f,352,x,346,x+1.3f,352),trim);}
        rect(x0-2,top-2.5f,fw+sw+4,3,mx(cF,BLACK,.25f));snowLine(x0-2,top-2.5f,fw+sw+4,1.3f);
        for(float x=x0-1;x<x0+fw+sw+2;x+=2.2f)rect(x,top-6,.6f,3.5f,trim);rect(x0-2,top-6.6f,fw+sw+4,.9f,trim);
        for(float tx:new float[]{x0-1,x0+fw+sw-2}){rect(tx-1.5f,top-16,4,14,cF);fill(poly(tx-2,top-16,tx+.5f,top-26,tx+3,top-16),surf(0xFF4F5666,.9f));}
        float bx=cx-10;rect(bx,272,20,top-274,cF);rect(bx+20,272,4,top-274,cS);
        for(float ax:new float[]{bx+3,bx+11}){fill(lancet(ax,276,6,22),mx(cF,BLACK,.6f));if(flood>.5f)fill(lancet(ax+1,278,4,19),0x80FFC882);}
        rect(bx-1.5f,270,26,2.4f,trim);
        int cu=0xFF6F8E83;Path dome=new Path();dome.moveTo(cx-11,270);dome.cubicTo(cx-13,264,cx-6,260,cx-3,253);dome.lineTo(cx+5,253);dome.cubicTo(cx+8,260,cx+15,264,cx+13,270);dome.close();
        fill(dome,hgrad(cx-12,cx+14,new int[]{surf(cu,kLeft),surf(cu,kSide)},null));
        rect(cx-2,247,6,6,surf(cu,.7f));Path cap=new Path();cap.moveTo(cx-3,247.5f);cap.quadTo(cx+1,241,cx+5,247.5f);cap.close();fill(cap,surf(cu,.7f));
        int gold=surf(0xFFE3B850,1.2f);fill(poly(cx-.6f,243,cx+2.6f,243,cx+2,236.5f,cx,236.5f),surf(0xFF2A2228,.6f));circle(cx+1,235.4f,1.2f,gold);rect(cx-.4f,239,4.2f,.6f,gold);
    });}
    private void alterPeter(){layer(PETER,0,.65f,228,556,()->{
        int pl=0xFFEADFCA,tr=0xFFCBB596,cu=0xFF4E8B70;float B=556,cx=392,fw=26,sw=8,x0=cx-fw/2,top=318;Rng rT=new Rng(31),rW=new Rng(32);
        int cF=surf(pl,kFront),cS=surf(pl,kSide),cT=surf(tr,kFront);
        rect(x0+fw,top,sw,B-top,cS);rect(x0,top,fw,B-top,cF);texture(x0,top,fw+sw,B-top,cF,rT,2);rect(x0+fw,top,1,B-top,mx(cS,BLACK,.06f));
        int i=0;for(float y=top+2;y<B;y+=5,i++){float qw=i%2==1?3:4.5f;rect(x0,y,qw,4,cT);rect(x0+fw-qw,y,qw,4,cT);}
        for(float yy:new float[]{362,412,462,506}){rect(x0-1,yy,fw+sw+1,2,cT);rect(x0-1,yy+2,fw+sw+1,.8f,mx(cF,BLACK,.18f));snowLine(x0-1,yy,fw+sw+1,1.3f);}
        for(float[] wr:new float[][]{{378,1},{426,2},{474,2},{518,1}})for(int k=0;k<wr[1];k++){float wx=wr[1]==1?cx-2.5f:cx-7+k*9;boolean on=rW.f()<winLit*.6f;fill(roundTop(wx-1,wr[0]-1,7,16),cT);fill(roundTop(wx,wr[0],5,14),glass(kFront,on,rW));}
        dial(cx,341,7.6f);oval(x0+fw+sw/2,341,2.6f,7.2f,surf(0xFF22305A,.8f*kSide+.1f));
        st.setStrokeCap(Paint.Cap.BUTT);st.setColor(surf(0xFFE5BC5C,1));st.setStrokeWidth(.8f);c.drawOval(x0+fw+sw/2-2.6f,341-7.2f,x0+fw+sw/2+2.6f,341+7.2f,st);st.setStrokeCap(Paint.Cap.ROUND);
        rect(x0-4,top-2,fw+sw+8,3.2f,cT);rect(x0-4,top+1.2f,fw+sw+8,1,mx(cT,BLACK,.3f));
        for(float x=x0-3;x<x0+fw+sw+4;x+=2)rect(x,top-7.5f,.8f,5.5f,cF);rect(x0-4,top-8.4f,fw+sw+8,1.2f,cF);snowLine(x0-4,top-8.4f,fw+sw+8,1.3f);
        float gx=cx+sw/2;Shader gr=sunLeft?hgrad(gx-18,gx+18,new int[]{surf(cu,1.15f),surf(cu,.6f),surf(cu,.15f)},new float[]{0,.5f,1}):hgrad(gx-18,gx+18,new int[]{surf(cu,.15f),surf(cu,.6f),surf(cu,1.15f),surf(cu,.7f)},new float[]{0,.55f,.85f,1});
        Path b1=new Path();b1.moveTo(gx-15,top-8);b1.cubicTo(gx-19,top-16,gx-16,top-27,gx-6,top-34);b1.lineTo(gx+6,top-34);b1.cubicTo(gx+16,top-27,gx+19,top-16,gx+15,top-8);b1.close();fill(b1,gr);
        st.setStrokeCap(Paint.Cap.BUTT);st.setColor(0x4710282A);st.setStrokeWidth(.5f);for(float f:new float[]{-.5f,0,.5f}){Path rib=new Path();rib.moveTo(gx+15*f,top-8);rib.cubicTo(gx+19*f,top-16,gx+16*f,top-27,gx+6*f,top-34);c.drawPath(rib,st);}st.setStrokeCap(Paint.Cap.ROUND);
        for(float d:new float[]{-9,9}){fill(poly(gx+d-3,top-12,gx+d,top-19,gx+d+3,top-12),surf(cu,.9f));circle(gx+d,top-14,1.6f,surf(0xFF22305A,.8f));}
        rect(gx-6,top-49,12,15,surf(cu,.7f));for(float ax:new float[]{gx-4,gx+1})fill(roundTop(ax,top-46,3,10),surf(0xFF1C2626,.4f));
        if(flood>.5f)for(float ax:new float[]{gx-4,gx+1})fill(roundTop(ax+.5f,top-45,2,9),0x8CFFC478);
        rect(gx-7.5f,top-50,15,1.6f,surf(cu,.8f));
        Path b2=new Path();b2.moveTo(gx-7,top-50);b2.cubicTo(gx-9,top-55,gx-6,top-60,gx-2.5f,top-63);b2.lineTo(gx+2.5f,top-63);b2.cubicTo(gx+6,top-60,gx+9,top-55,gx+7,top-50);b2.close();fill(b2,gr);
        rect(gx-2.8f,top-70,5.6f,7,surf(cu,.7f));rect(gx-1,top-69,2,5,surf(0xFF1C2626,.4f));
        Path cap=new Path();cap.moveTo(gx-3.4f,top-70);cap.quadTo(gx,top-82,gx+3.4f,top-70);cap.close();fill(cap,surf(cu,.85f));
        int gold=surf(0xFFE8BE5C,1.2f);circle(gx,top-82,1.2f,gold);rect(gx-.35f,top-89,.7f,6,gold);rect(gx-1.8f,top-87,3.6f,.6f,gold);
    });}
    private void houses(){
        float B=574,fh=13.5f;Rng rT=new Rng(41),rW=new Rng(42);float flowers=season==SUMMER?1:season==SPRING?.6f:season==AUTUMN?.25f:0;int[] awn={0xFFB23A3A,0xFF2F5C8F,0xFF3C6E4B,0xFF7A4A8F};
        for(int hi=0;hi<HOUSE_ROW.length;hi++){float[] hs=HOUSE_ROW[hi];float hx=hs[0],hw=hs[1];int fl=(int)hs[2],base=0xFF000000|(int)hs[3],roof=(int)hs[4];int shut=hs[5]<0?0:0xFF000000|(int)hs[5];
            float eave=B-fl*fh-8;int col=surf(base,kFront),trim=surf(mx(base,WHITE,.55f),kFront+.1f);
            if(roof==0){tiles(poly(hx-1.5f,eave,hx+hw+1.5f,eave,hx+hw-4,eave-18,hx+4,eave-18),hx-1.5f,eave-18,hx+hw+1.5f,eave,0xFFB25B3E,kFront+.15f,rT);
                for(float dx=hx+7;dx<hx+hw-6;dx+=11){rect(dx,eave-12,6,8,col);fill(poly(dx-1,eave-12,dx+3,eave-16,dx+7,eave-12),surf(0xFF9E4E35,.8f));
                    rect(dx+1.4f,eave-10.5f,3.2f,5,glass(kFront,rW.f()<winLit,rW));snowLine(dx-1,eave-12.4f,8,1.3f);}
                rect(hx+hw-9,eave-26,3.5f,9,surf(0xFF5A4A48,.6f));}
            else{float top=eave-26,mid=hx+hw/2;
                if(roof==1){int n=4;float step=(mid-hx)/n;Path q=new Path();q.moveTo(hx,eave);for(int k=0;k<n;k++){float x=hx+step*k,y2=eave-(eave-top)*(k+1)/n;q.lineTo(x,y2);q.lineTo(x+step,y2);}
                    for(int k=n-1;k>=0;k--){float x=2*mid-hx-step*k,y2=eave-(eave-top)*(k+1)/n;q.lineTo(x-step,y2);q.lineTo(x,y2);}q.lineTo(hx+hw,eave);q.close();fill(q,col);
                    if(snow>0)for(int k=0;k<n;k++){float x=hx+step*k,y2=eave-(eave-top)*(k+1)/n;rect(x,y2-1.2f,step+.5f,1.3f,al(surf(0xFFF6F4FF,1.1f),.9f*snow));rect(2*mid-x-step-.5f,y2-1.2f,step+.5f,1.3f,al(surf(0xFFF6F4FF,1.1f),.9f*snow));}}
                else{Path q=new Path();q.moveTo(hx,eave);q.cubicTo(hx,eave-10,hx+8,eave-8,hx+8,eave-16);q.cubicTo(hx+8,top+2,mid-4,top+2,mid-3,top);q.lineTo(mid+3,top);q.cubicTo(mid+4,top+2,hx+hw-8,top+2,hx+hw-8,eave-16);q.cubicTo(hx+hw-8,eave-8,hx+hw,eave-10,hx+hw,eave);q.close();fill(q,col);
                    circle(hx+5,eave-6,2.4f,trim);circle(hx+hw-5,eave-6,2.4f,trim);rect(mid-4,top-1.4f,8,1.6f,trim);circle(mid,top-3.6f,1.6f,trim);snowLine(mid-4,top-1.4f,8,1.3f);}
                boolean on=rW.f()<winLit;rect(mid-3.6f,eave-17,7.2f,10,trim);rect(mid-2.6f,eave-16,5.2f,8,glass(kFront,on,rW));}
            rect(hx,eave,hw,B-eave,col);texture(hx,eave,hw,B-eave,col,rT,2);rect(hx,eave,1.4f,B-eave,0x38140A1E);
            rect(hx-1,eave,hw+2,2,trim);rect(hx-1,eave+2,hw+2,.8f,mx(col,BLACK,.25f));snowLine(hx-1,eave,hw+2,1.6f);
            int n=Math.max(2,(int)Math.floor((hw-4)/9));float gap=(hw-n*4.6f)/(n+1);
            for(int f=0;f<fl-1;f++){float yy=eave+5+f*fh;for(int i=0;i<n;i++){float wx=hx+gap+i*(4.6f+gap);boolean on=rW.f()<winLit;
                rect(wx-.8f,yy-.8f,6.2f,9.4f,trim);rect(wx,yy,4.6f,7.8f,glass(kFront,on,rW));rect(wx+2,yy,.6f,7.8f,al(trim,.9f));rect(wx,yy+3,4.6f,.5f,al(trim,.9f));
                if(shut!=0){int sc=surf(shut,kFront);rect(wx-2.6f,yy-.4f,1.8f,8.6f,sc);rect(wx+5.4f,yy-.4f,1.8f,8.6f,sc);}
                snowLine(wx-1,yy+8.8f,6.6f,1);
                if(flowers>0&&f<2&&rW.f()<flowers){rect(wx-1,yy+8,6.6f,1.6f,surf(0xFF6B4A3A,.6f));for(int k=0;k<4;k++)circle(wx-.2f+k*1.7f,yy+7.6f,.95f,surf(k%2==1?0xFF3E7A3E:season==AUTUMN?0xFFC76A2A:0xFFD9333F,1));}}}
            float sy=B-fh+1;rect(hx+3,sy+2,hw-6,fh-3,surf(0xFF2D2638,.5f));
            if(lampsOn||!sky.morning&&sky.elevation<12)rect(hx+4,sy+3,hw-8,fh-5,al(mx(0xFFFFC874,0xFFFFE2AA,.4f),lampsOn?.85f:.35f));
            int aw=surf(awn[hi%4],kFront+.2f),cream=surf(0xFFF3EEE6,kFront+.2f);for(float i=0;i<hw-4;i+=3)rect(hx+2+i,sy-1,3,3.4f,((int)i)%6!=0?cream:aw);
            for(float i=0;i<hw-4;i+=3){p.setColor(aw);c.drawArc(hx+2+i,sy+.9f,hx+5+i,sy+3.9f,0,180,true,p);}
        }
    }
    private void maibaum(){
        float x=342,top=338,B=574;
        c.save();c.clipPath(poly(x-2.2f,B,x-1.2f,top,x+1.2f,top,x+2.2f,B));rect(x-3,top,6,B-top,surf(0xFFF4F3F8,kFront+.25f));
        int blue=surf(0xFF2E6FC6,kFront+.3f);for(float y=top;y<B;y+=9)fill(poly(x-3,y,x+3,y-5,x+3,y-1,x-3,y+4),blue);rect(x+.6f,top,2,B-top,0x29000000);c.restore();
        int[] cols={0xFFC9483E,0xFF2E6FC6,0xFFE8BE5C,0xFF3C7A4A};float[][] boards={{372,-1},{394,1},{416,-1},{438,1},{460,-1},{482,1}};
        for(int i=0;i<boards.length;i++){float y=boards[i][0],d=boards[i][1],bx=x+d*3;rect(Math.min(x,bx+d*11),y-.4f,12,.8f,surf(0xFFE8E2D4,.8f));
            float sx=x+d*7,sw=8.5f,sh=6.5f;rect(sx-sw/2+d*2,y,sw,sh,surf(0xFFF4EEE2,kFront+.2f));st.setStrokeCap(Paint.Cap.BUTT);st.setColor(surf(0xFF2E6FC6,.8f));st.setStrokeWidth(.5f);c.drawRect(sx-sw/2+d*2,y,sx+sw/2+d*2,y+sh,st);st.setStrokeCap(Paint.Cap.ROUND);
            rect(sx-1.6f+d*2,y+1.4f,3.2f,3.8f,surf(cols[i%4],1));circle(sx+d*2,y+1.2f,1,surf(cols[i%4],1));}
        int green=surf(season==WINTER?0xFF4A6B52:0xFF3F7D45,.9f);oval(x,top+8,5,2.2f,green);oval(x,top+14,7,2.4f,green);
        st.setColor(surf(0xFF3F7D45,.8f));st.setStrokeWidth(.6f);st.setStyle(Paint.Style.STROKE);for(int sgn:new int[]{-1,1}){Path q=new Path();q.moveTo(x+sgn*7,top+14);q.quadTo(x+sgn*10,top+22,x+sgn*6,top+28);c.drawPath(q,st);}
        fill(poly(x-2.2f,top,x,top-12,x+2.2f,top),surf(0xFF3F7D45,1));
        if(snow>0)half(x,top+13,6,1,true,al(surf(0xFFF6F4FF,1.1f),.8f));
    }
    private void mariensaeule(){
        float x=150,B=572;int stn=surf(0xFFB7AEA2,kFront);rect(x-11,B-12,22,12,stn);rect(x-11,B-12,22,1.4f,mx(stn,BLACK,.2f));rect(x-6,B-26,12,14,stn);
        for(int i=0;i<7;i++)rect(x-10+i*3.3f,B-15,.6f,4,surf(0xFF3A3340,.6f));for(float dx:new float[]{-9,9})circle(x+dx,B-16,2,surf(0xFF3A3048,.7f));
        int sh=surf(0xFFA1786A,kFront+.1f);rect(x-1.8f,B-104,3.6f,78,sh);rect(x-1.2f,B-104,.8f,78,al(mx(sh,WHITE,.2f),.7f));rect(x-3.4f,B-108,6.8f,4,stn);
        int gold=surf(0xFFE9C05A,1.25f),gd=mx(gold,BLACK,.3f);
        if(flood>.5f){p.setShader(new RadialGradient(x,B-118,14,0x8CFFD682,0x00FFD682,Shader.TileMode.CLAMP));c.drawRect(x-14,B-132,x+14,B-104,p);p.setShader(null);}
        half(x,B-109,4,1.4f,false,gd);Path body=new Path();body.moveTo(x-2.6f,B-109);body.quadTo(x-3,B-118,x-1,B-122);body.lineTo(x+1.4f,B-122);body.quadTo(x+3,B-116,x+2.8f,B-109);body.close();fill(body,gold);
        circle(x+.2f,B-123.6f,1.6f,gold);rect(x-1.5f,B-117,3.6f,.8f,gd);
        st.setStrokeCap(Paint.Cap.BUTT);st.setColor(al(gold,.9f));st.setStrokeWidth(.5f);c.drawArc(x+.2f-3.2f,B-123.6f-3.2f,x+.2f+3.2f,B-123.6f+3.2f,189,162,false,st);st.setStrokeCap(Paint.Cap.ROUND);
        for(int i=0;i<9;i++){double a=Math.PI*(1.05+i*.1);circle(x+.2f+(float)Math.cos(a)*4.2f,B-123.6f+(float)Math.sin(a)*4.2f,.45f,gold);}
    }
    private void lamp(float x,float B,float lh){
        int post=surf(0xFF273330,.5f);rect(x-.8f,B-lh,1.6f,lh,post);rect(x-2.2f,B-2,4.4f,2,post);rect(x-1.6f,B-lh-1,3.2f,1.2f,post);
        fill(poly(x-2.6f,B-lh-1,x-1.8f,B-lh-8,x+1.8f,B-lh-8,x+2.6f,B-lh-1),lampsOn?0xFFFFE2A0:surf(0xFFD8D2C4,.8f));
        fill(poly(x-3.4f,B-lh-8,x,B-lh-11.5f,x+3.4f,B-lh-8),post);rect(x-.4f,B-lh-13.5f,.8f,2,post);
    }
    private void lampGlow(float x,float y,float r){p.setShader(new RadialGradient(x,y,r,new int[]{0xBFFFD68C,0x52FFBE6E,0x00FFAA5A},new float[]{0,.25f,1},Shader.TileMode.CLAMP));c.drawRect(x-r,y-r,x+r,y+r,p);p.setShader(null);}
    private void christmas(){
        float x=212,B=566;Rng r=new Rng(61);rect(x-1.5f,B-8,3,8,surf(0xFF4A3A30,.5f));
        for(int i=0;i<7;i++){float y=B-8-i*11,tw=26-i*3.3f;Path t=new Path();t.moveTo(x-tw,y);t.lineTo(x,y-20);t.lineTo(x+tw,y);t.quadTo(x,y+3,x-tw,y);t.close();fill(t,surf(0xFF1F4A33,kFront+.1f));
            Path lit=new Path();lit.moveTo(x,y-20);lit.lineTo(x+tw,y);lit.quadTo(x+tw*.5f,y+1.5f,x+2,y);lit.close();fill(lit,al(surf(0xFF2E6A48,sunLeft?.4f:1),.8f));
            if(snow>0){Path sn=new Path();sn.moveTo(x-tw,y);sn.quadTo(x,y-3,x+tw,y);sn.quadTo(x,y+1.6f,x-tw,y);sn.close();fill(sn,al(surf(0xFFF6F4FF,1.1f),.85f*snow));}}
        for(int i=0;i<70;i++){float t=r.f(),y=B-12-t*76,tw=(24-t*22)*(r.f()*2-1);lights.add(new float[]{x+tw,y,r.f()*6.28f,0,1});}
        lights.add(new float[]{x,B-92,0,1,1});
        for(float[] stall:new float[][]{{166,0xFFA6402F},{246,0xFF7A5236},{280,0xFFA6402F}}){float sx=stall[0],sy=B+2;rect(sx,sy-12,22,12,surf(0xFF6B4A33,kFront));
            rect(sx+2,sy-9,18,6,xmasGlow>.5f?0xE6FFC46E:surf(0xFF3A2A28,.5f));
            tiles(poly(sx-3,sy-12,sx+25,sy-12,sx+20,sy-19,sx+2,sy-19),sx-3,sy-19,sx+25,sy-12,0xFF000000|(int)stall[1],kFront+.2f,r);
            for(int k=0;k<6;k++)lights.add(new float[]{sx+1+k*4,sy-12.5f,r.f()*6.28f,0,.6f});}
    }
    private void umbrellas(){
        int n=season==SUMMER?4:season==SPRING?3:2;int[] cols={0xFFF3EBDD,0xFFE9E1F2,0xFFF3EBDD,0xFFDCE8E0};
        for(int i=0;i<n;i++){float x=180+i*30,B=568+(i%2)*4;rect(x-.5f,B-16,1,16,surf(0xFF3A3438,.5f));int wood=surf(0xFF6B5A4A,.6f);rect(x-5,B-6,10,1,wood);rect(x-4,B-6,.8f,6,wood);rect(x+3.2f,B-6,.8f,6,wood);
            Path u=new Path();u.moveTo(x-12,B-15);u.quadTo(x,B-24,x+12,B-15);u.close();fill(u,surf(cols[i],kFront+.25f));
            int edge=surf(mx(cols[i],BLACK,.12f),kFront);for(float k=-12;k<12;k+=4){p.setColor(edge);c.drawArc(x+k,B-17,x+k+4,B-13,0,180,true,p);}}
    }
    private void people(){
        Rng r=new Rng(71);float[][] spots={{60,584,1},{124,578,-1},{250,588,1},{338,582,-1},{430,594,1},{560,586,-1},{612,590,1},{700,584,-1}};
        boolean umbrella=sky.kind==MeridianSky.RAIN||sky.kind==MeridianSky.SNOW;
        int[] coats=season==WINTER?new int[]{0xFF3A3550,0xFF6B2E3A,0xFF2F4A5E,0xFF5A4A3A}:season==SUMMER?new int[]{0xFFE6D4B8,0xFF5A86B8,0xFFD86A5A,0xFFF2EEE6}:new int[]{0xFF7A5A3A,0xFF4A5A7A,0xFF8A3A3A,0xFF5A6B4A};
        for(float[] sp:spots){float x=sp[0],y=sp[1],d=sp[2],k=.85f+(y-575)/50;int coat=surf(coats[(int)(r.f()*4)],kFront+.15f),skin=surf(0xFFE6C2A4,kFront+.2f),dark=surf(0xFF2A2430,.4f);
            rect(x-1.3f*k,y-5*k,1*k,5*k,dark);rect(x+.3f*k,y-5*k,1*k,5*k,dark);fill(poly(x-2.2f*k,y-4.6f*k,x-1.8f*k,y-11*k,x+1.8f*k,y-11*k,x+2.2f*k,y-4.6f*k),coat);circle(x,y-12.6f*k,1.5f*k,skin);
            if(season==WINTER)rect(x-1.8f*k,y-11.2f*k,3.6f*k,1.2f*k,surf(new int[]{0xFFC9483E,0xFFE8BE5C,0xFF2E6FC6}[(int)(r.f()*3)],1));
            if(umbrella&&r.f()<.8f){int uc=surf(new int[]{0xFF2B2A3A,0xFFB23A3A,0xFF2F5C8F,0xFFE8BE5C}[(int)(r.f()*4)],kFront+.2f);rect(x+d*.5f*k,y-18*k,.5f*k,7*k,dark);
                Path u=new Path();u.moveTo(x-7*k,y-16*k);u.quadTo(x,y-23*k,x+7*k,y-16*k);u.close();fill(u,uc);}
            if(wet)rect(x-2*k,y+.5f,4*k,3,al(coat,.25f));}
    }
    private void tree(float x,float B,float sc,long seed){
        Rng r=new Rng(seed);List<float[]> tips=new ArrayList<>();int bark=surf(0xFF4C3B33,.5f);
        branch(r,tips,bark,x,B,(float)(-Math.PI/2+(r.f()-.5f)*.25f),30*sc,7*sc,0);
        float lx=sky.sunX>=.5f?1:-1;
        if(season==WINTER){if(lampsOn||xmasGlow>.5f)for(float[] t:tips)if(r.f()<.5f){circle(t[0],t[1],.8f,0xF2FFDE96);p.setShader(new RadialGradient(t[0],t[1],4,0x59FFD282,0x00FFD282,Shader.TileMode.CLAMP));c.drawRect(t[0]-4,t[1]-4,t[0]+4,t[1]+4,p);p.setShader(null);}return;}
        int[] pal=season==SPRING?new int[]{0xFF7FB86A,0xFF9CCB72,0xFF5E9A55}:season==SUMMER?new int[]{0xFF3F7A3E,0xFF4E8C46,0xFF2E5E33}:new int[]{0xFFD9822B,0xFFE6A93A,0xFFB8502A,0xFFC9A23A,0xFF8A6A2E};
        float dens=season==AUTUMN?.75f:1;
        for(int pass=0;pass<3;pass++)for(float[] t:tips){if(r.f()>dens)continue;for(int j=0;j<3;j++){float rad=(pass==0?4.6f:pass==1?3.2f:1.9f)*sc*(.7f+r.f()*.6f);int base=pal[(int)(r.f()*pal.length)];
            float k=pass==0?.1f:pass==1?.6f:1.2f,ox2=pass==0?-lx*2:pass==2?lx*2.2f:0,oy2=pass==0?2.6f:pass==2?-2.2f:0;circle(t[0]+ox2+(r.f()-.5f)*9,t[1]+oy2+(r.f()-.5f)*8,rad,al(surf(base,k),pass==2?.9f:1));}}
        if(season==SPRING)for(float[] t:tips)if(r.f()<.45f){oval(t[0]+(r.f()-.5f)*6,t[1]-3,1.4f*sc,3.6f*sc,surf(0xFFFBF4F2,1.1f));circle(t[0]+(r.f()-.5f)*4,t[1]-2,.9f*sc,al(surf(0xFFF2B8C4,1),.8f));}
        if(snow>0)for(int i=0;i<tips.size();i+=3){float[] t=tips.get(i);oval(t[0],t[1]-5*sc,4*sc,1.4f*sc,al(surf(0xFFF6F4FF,1.1f),.7f));}
    }
    private void branch(Rng r,List<float[]> tips,int bark,float x1,float y1,float a,float len,float bw,int d){
        float x2=x1+(float)Math.cos(a)*len,y2=y1+(float)Math.sin(a)*len;line(x1,y1,x2,y2,bark,bw);
        if(snow>0&&bw<5&&d>0)line(x1,y1-bw*.45f,x2,y2-bw*.45f,al(surf(0xFFF6F4FF,1.1f),.85f*snow),Math.max(.5f,bw*.45f));
        if(d>=6||len<3){tips.add(new float[]{x2,y2});return;}int n=r.f()<.4f?3:2;for(int i=0;i<n;i++)branch(r,tips,bark,x2,y2,a+(i-(n-1)/2f)*.62f+(r.f()-.5f)*.5f,len*(.7f+r.f()*.12f),bw*.66f,d+1);
    }
    private void ground(){
        float top=530;int base=season==WINTER||sky.kind==MeridianSky.SNOW?mx(0xFFC9C1B6,0xFFF2F0FA,snow):0xFFC3B8AB;if(wet)base=mx(base,0xFF3C3850,.45f);
        p.setShader(new LinearGradient(0,top,0,640,surf(mx(base,BLACK,.08f),.55f),surf(base,.75f),Shader.TileMode.CLAMP));c.drawRect(-700,top,1400,700,p);p.setShader(null);
        Rng r=new Rng(81);st.setStrokeCap(Paint.Cap.BUTT);st.setColor(al(surf(mx(base,BLACK,.25f),.6f),snow>.5f?.15f:.35f));st.setStrokeWidth(.45f);
        int i=0;for(float y=top+4;y<640;y+=2+i*.35f,i++){Path q=new Path();for(float x=-180;x<900;x+=4+i*.4f){q.moveTo(x,y);q.quadTo(x+2+i*.2f,y-1,x+4+i*.4f,y);}c.drawPath(q,st);}
        st.setStrokeCap(Paint.Cap.ROUND);
        if(season==AUTUMN&&snow<=0)for(int k=0;k<120;k++)ovalRot(-60+r.f()*840,top+20+r.f()*90,1.6f,.8f,r.f()*3,al(surf(new int[]{0xFFD9822B,0xFFE6A93A,0xFFB8502A}[k%3],.9f),.8f));
    }
}
