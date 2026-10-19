package com.personalassistant.companion;

import android.graphics.*;
import android.graphics.drawable.Drawable;
import android.os.SystemClock;

/**
 * Meridian page background. Under the Voice home it paints the hero: the Aurora sky for the sun's elevation, sun bloom or
 * moon and stars, drifting volumetric clouds lit from the sun or moon, four Alpine ridges with snow, rim light, fog and
 * spruces, then rain or snow. Other tabs get a short sky strip; every page gets quiet weather in its gaps (beads of rain,
 * mist, drifting snow and frost, a warm glow or faint stars). It animates only while visible and motion is enabled, one
 * frame per display refresh. Each cloud layer is lit off the main thread as a seamless tile every 1.5 s and slid by
 * sub-pixel offsets on the GPU every frame, so the drift stays smooth at 60 to 120 Hz.
 */
final class MeridianBackdrop extends Drawable implements android.view.Choreographer.FrameCallback {
    private static final int BW=180,BH=104,FW=384,FH=112;private static final long RELIGHT=1500;
    /** Per layer: scale (screen widths per tile), drift in field widths per ms, field offset, opacity. */
    private static final float[][] LAYERS={{1f,.0000045f,0f,.85f},{1.7f,.0000105f,.37f,1f}};
    private static final java.util.concurrent.ExecutorService LIGHTING=java.util.concurrent.Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"meridian-lighting");t.setPriority(Thread.MIN_PRIORITY);return t;});
    /** The moon sits clear of the header chips and the orb. */
    private static final float MOON_X=.80f,MOON_Y=.30f;
    private static volatile float[] field;private static boolean building;
    private static float[][] ridges;private static float[][] trees,stars;

    private final AppUi ui;private final AppUi.Wash wash;private final float density;
    private MeridianSky sky;private long skyAt;
    private int heroPx,stripPx,offset;private boolean hero;
    private boolean running,visible=true;private long lastFrame;private float time;
    private volatile Bitmap[] tiles;private volatile boolean lighting;private long litAt=-1;private int[] litSky;
    private final Paint fill=new Paint(Paint.ANTI_ALIAS_FLAG),line=new Paint(Paint.ANTI_ALIAS_FLAG),image=new Paint(Paint.FILTER_BITMAP_FLAG),add=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final java.util.Random random=new java.util.Random(11);
    private final float[][] rain=new float[171][3],snow=new float[128][4],beads=new float[26][4],flakes=new float[18][3],mist=new float[3][3];
    private final java.util.ArrayList<float[]> splashes=new java.util.ArrayList<>();
    private final float[][] trails=new float[26][80];private final int[] trailLength=new int[26];
    // Cached geometry for the current size and sky.
    private int cachedW,cachedH;private int[] cachedSky;private Path[] ridgePaths,rimPaths;private Shader[] ridgeShaders,snowShaders,fogShaders,glowShaders;private float[][] ridgeTops;private Shader skyShader,fadeShader,stripShader,stripGlow,moonGlow,moonShader,rayShader;private Path rays;private int[] stripSky;private int stripH;
    private float sunX,sunY,stripX,stripY;
    // Page-gap shaders are built at the origin once per size and placed with a canvas translation.
    private int gapW=-1,gapH=-1;private Shader[] beadShaders;private Shader mistShader,frostShader,warmShader;private final Path trail=new Path();
    private Bitmap[] shaded;private BitmapShader[] tileShaders;private final Matrix tileMatrix=new Matrix();private final Paint tilePaint=new Paint(Paint.FILTER_BITMAP_FLAG);

    MeridianBackdrop(AppUi ui){
        this.ui=ui;wash=new AppUi.Wash(ui);density=ui.density;sky=MeridianSky.now(ui.context);skyAt=SystemClock.uptimeMillis();
        line.setStyle(Paint.Style.STROKE);line.setStrokeCap(Paint.Cap.ROUND);add.setXfermode(new PorterDuffXfermode(PorterDuff.Mode.ADD));
        for(int d=0,i=0;d<3;d++)for(int n=0;n<new int[]{90,55,26}[d];n++,i++)rain[i]=new float[]{random.nextFloat(),random.nextFloat(),d};
        for(int d=0,i=0;d<3;d++)for(int n=0;n<new int[]{70,40,18}[d];n++,i++)snow[i]=new float[]{random.nextFloat(),random.nextFloat(),random.nextFloat(),d};
        for(float[] b:beads){b[0]=random.nextFloat();b[1]=random.nextFloat();b[2]=1.2f+random.nextFloat()*2.2f;b[3]=0;}
        for(float[] f:flakes){f[0]=random.nextFloat();f[1]=random.nextFloat();f[2]=random.nextFloat();}
        for(int i=0;i<3;i++)mist[i]=new float[]{random.nextFloat(),.35f+i*.2f,.00004f+random.nextFloat()*.00005f};
        landscape();buildField();
    }

    /** Hero height under the Voice home, measured from the top of the window, or a short strip on other tabs. */
    void hero(int px){if(hero&&heroPx==px)return;hero=true;heroPx=px;invalidateSelf();}
    void strip(int px){if(!hero&&stripPx==px)return;hero=false;stripPx=px;invalidateSelf();}
    void scroll(int y){y=Math.max(0,y);if(y==offset)return;offset=y;invalidateSelf();}
    MeridianSky sky(){return sky;}

    @Override public boolean setVisible(boolean visible,boolean restart){boolean changed=super.setVisible(visible,restart);this.visible=visible;if(visible)start();else stop();return changed;}
    private void start(){if(running||!visible||!AppUi.motion())return;running=true;lastFrame=0;android.view.Choreographer.getInstance().postFrameCallback(this);}
    private void stop(){running=false;android.view.Choreographer.getInstance().removeFrameCallback(this);}
    /** One step per display frame, timed by vsync; particle speeds are defined per 33 ms. */
    @Override public void doFrame(long nanos){
        if(!running)return;if(!AppUi.motion()){running=false;invalidateSelf();return;}
        float ms=lastFrame==0?16f:Math.min(100f,(nanos-lastFrame)/1e6f);lastFrame=nanos;time+=ms;
        step(ms/33f);invalidateSelf();android.view.Choreographer.getInstance().postFrameCallback(this);
    }

    @Override protected void onBoundsChange(Rect b){wash.setBounds(b);}
    @Override public void draw(Canvas c){
        Rect b=getBounds();if(b.isEmpty())return;long now=SystemClock.uptimeMillis();
        if(now-skyAt>60000){skyAt=now;sky=MeridianSky.now(ui.context);cachedSky=null;}
        if(!running&&visible&&AppUi.motion())start();
        wash.draw(c);details(c,b.width(),b.height());
        if(hero&&heroPx>0){int h=heroPx;if(offset<h){c.save();c.translate(b.left,b.top-offset);c.clipRect(0,0,b.width(),h);paintHero(c,b.width(),h);c.restore();}}
        else if(!hero&&stripPx>0){int h=stripPx;if(offset<h){c.save();c.translate(b.left,b.top-offset);c.clipRect(0,0,b.width(),h);paintStrip(c,b.width(),h);c.restore();}}
    }
    @Override public void setAlpha(int a){}@Override public void setColorFilter(ColorFilter f){}@Override public int getOpacity(){return PixelFormat.OPAQUE;}

    // ---------------------------------------------------------------- hero

    private void geometry(int w,int h){
        if(w==cachedW&&h==cachedH&&cachedSky==sky.sky)return;cachedW=w;cachedH=h;cachedSky=sky.sky;int[] s=sky.sky;
        skyShader=new LinearGradient(0,0,0,h*.8f,new int[]{s[0],s[1],s[2]},new float[]{0,.45f,1},Shader.TileMode.CLAMP);
        // A high sun stays below the header so the white title and weather pill keep their contrast.
        double e=sky.elevation;float low=1-MeridianSky.smooth(4,22,Math.abs(e)),glowK=(sky.kind==MeridianSky.CLEAR&&sky.cover<.5f?1:.55f)*(.55f+.45f*low);
        sunX=sky.sunX*w;sunY=(float)Math.max(.27,.62-e*.0125)*h;float[][] glow={{.9f,.10f},{.45f,.16f},{.2f,.28f},{.07f,.6f}};glowShaders=new Shader[4];
        for(int i=0;i<4;i++)glowShaders[i]=new RadialGradient(sunX,sunY,Math.max(1,w*glow[i][0]),AppUi.alpha(s[3],glow[i][1]*glowK),s[3]&0x00FFFFFF,Shader.TileMode.CLAMP);
        rayShader=new LinearGradient(0,0,w*.7f,0,AppUi.alpha(s[3],.16f*low),s[3]&0x00FFFFFF,Shader.TileMode.CLAMP);rays=new Path();
        for(int i=0;i<12;i++){double a=Math.toRadians(30*(i+1)),cs=Math.cos(a),sn=Math.sin(a);float r=w*.7f,hw=w*.035f;rays.moveTo(0,0);rays.lineTo((float)(r*cs+hw*sn),(float)(r*sn-hw*cs));rays.lineTo((float)(r*cs-hw*sn),(float)(r*sn+hw*cs));rays.close();}
        float mx=w*MOON_X,my=h*MOON_Y,mr=11*density;moonGlow=new RadialGradient(mx,my,66*density,0x47E1D7FF,0x00E1D7FF,Shader.TileMode.CLAMP);moonShader=new RadialGradient(mx-mr*.35f,my-mr*.35f,mr*1.35f,0xFFFFFBF2,0xFFCFC4EE,Shader.TileMode.CLAMP);
        fadeShader=new LinearGradient(0,h*.84f,0,h,ui.background&0x00FFFFFF,ui.background,Shader.TileMode.CLAMP);
        float day=MeridianSky.smooth(-6,8,sky.elevation);int near=MeridianSky.mix(0xFF1E1238,0xFF5E4C92,day),horizon=s[2];
        ridgePaths=new Path[4];rimPaths=new Path[4];ridgeShaders=new Shader[4];snowShaders=new Shader[4];fogShaders=new Shader[4];ridgeTops=new float[4][];
        float[][] layer={{.60f,.20f,0},{.67f,.12f,.33f},{.75f,.07f,.66f},{.83f,.045f,1}};
        for(int li=0;li<4;li++){
            float base=layer[li][0],amp=layer[li][1],d=layer[li][2];float[] r=ridges[li];int steps=Math.max(2,w/Math.max(1,Math.round(2*density)));float[] top=new float[steps+1];
            Path p=new Path();p.moveTo(0,h);for(int k=0;k<=steps;k++){float x=w*k/(float)steps;top[k]=h*(base-r[Math.min(256,Math.round(x/w*256))]*amp);p.lineTo(x,top[k]);}p.lineTo(w,h);p.close();
            if(li==3){for(float[] t:trees){float x=t[0]*w,y=top[Math.min(steps,Math.round(t[0]*steps))],th=t[1]*14*density,tw=th*.32f;p.moveTo(x,y-th);p.lineTo(x-tw,y+2*density);p.lineTo(x+tw,y+2*density);p.close();}}
            ridgePaths[li]=p;ridgeTops[li]=top;Path rim=new Path();for(int k=0;k<=steps;k++){float x=w*k/(float)steps;if(k==0)rim.moveTo(x,top[k]);else rim.lineTo(x,top[k]);}rimPaths[li]=rim;
            int col=MeridianSky.mix(horizon,near,.25f+d*.75f),colB=MeridianSky.mix(col,0xFF120A22,.25f+d*.25f);
            ridgeShaders[li]=new LinearGradient(0,h*(base-amp),0,h,col,colB,Shader.TileMode.CLAMP);
            if(li==0)snowShaders[li]=new LinearGradient(0,h*(base-amp),0,h*(base-amp*.45f),AppUi.alpha(MeridianSky.mix(0xFFFFFFFF,s[3],.3f),sky.kind==MeridianSky.SNOW?.95f:.75f),0x00FFFFFF,Shader.TileMode.CLAMP);
            if(li<3){float fy=h*(base+.02f),fa=.10f+sky.desaturate*.22f+(sky.kind==MeridianSky.SNOW?.08f:0);int fog=MeridianSky.mix(horizon,0xFFFFFFFF,.15f);
                fogShaders[li]=new LinearGradient(0,fy-h*.05f,0,fy+h*.05f,new int[]{horizon&0x00FFFFFF,AppUi.alpha(fog,Math.min(1,fa)),horizon&0x00FFFFFF},null,Shader.TileMode.CLAMP);}
        }
    }

    private void paintHero(Canvas c,int w,int h){
        geometry(w,h);int[] s=sky.sky;double e=sky.elevation;boolean sun=sky.sun,clear=sky.kind==MeridianSky.CLEAR&&sky.cover<.5f;float low=1-MeridianSky.smooth(4,22,Math.abs(e));
        float sx=sunX,sy=sunY;
        fill.setShader(skyShader);c.drawRect(0,0,w,h,fill);fill.setShader(null);
        if(!sun){float fade=1-MeridianSky.smooth(-8,-2,e);for(float[] st:stars){float a=(.25f+.55f*(.5f+.5f*(float)Math.sin(time*.002+st[3])))*fade*(sky.kind==MeridianSky.CLEAR?1:.35f);fill.setColor(AppUi.alpha(0xFFFFFAFF,a));c.drawCircle(st[0]*w,st[1]*h,(.5f+st[2]*1.1f)*density,fill);}}
        if(sun){for(Shader g:glowShaders){add.setShader(g);c.drawRect(0,0,w,h,add);}add.setShader(null);
            if(clear&&low>.05f){c.save();c.translate(sx,sy);c.rotate(time*.0034f);fill.setShader(rayShader);c.drawPath(rays,fill);fill.setShader(null);c.restore();}
            fill.setColor(s[3]);c.drawCircle(sx,sy,(9+low*4)*density,fill);
        }else{add.setShader(moonGlow);c.drawRect(0,0,w,h,add);add.setShader(null);
            fill.setShader(moonShader);c.drawCircle(w*MOON_X,h*MOON_Y,11*density,fill);fill.setShader(null);}
        clouds(c,w,h*.62f,1,sx/w,sy/(h*.62f));
        for(int li=0;li<4;li++){
            fill.setShader(ridgeShaders[li]);c.drawPath(ridgePaths[li],fill);fill.setShader(null);
            if(snowShaders[li]!=null){c.save();c.clipPath(ridgePaths[li]);fill.setShader(snowShaders[li]);c.drawRect(0,0,w,h,fill);fill.setShader(null);c.restore();}
            if(sun||li<3){float a=sun?(.18f+.35f*low)*(1-li*.2f)*(clear?1:.4f):.16f*(1-li*.3f)*(clear?1:.5f);line.setColor(AppUi.alpha(s[3],Math.min(1,a)));line.setStrokeWidth((1.3f-li*.2f)*density);c.drawPath(rimPaths[li],line);}
            if(fogShaders[li]!=null){float fy=h*(new float[]{.60f,.67f,.75f}[li]+.02f);fill.setShader(fogShaders[li]);c.drawRect(0,fy-h*.05f,w,fy+h*.05f,fill);fill.setShader(null);}
        }
        precipitation(c,w,h,1);
        fill.setShader(fadeShader);c.drawRect(0,h*.84f,w,h,fill);fill.setShader(null);
    }

    private void paintStrip(Canvas c,int w,int h){
        int[] s=sky.sky;double e=sky.elevation;
        if(stripShader==null||stripSky!=sky.sky||stripH!=h){stripSky=sky.sky;stripH=h;stripShader=new LinearGradient(0,0,0,h,new int[]{s[0],s[1],AppUi.alpha(MeridianSky.mix(s[2],ui.background,.55f),.55f),ui.background&0x00FFFFFF},new float[]{0,.38f,.66f,1},Shader.TileMode.CLAMP);
            stripX=(sky.sun?sky.sunX:MOON_X)*w;stripY=Math.max(10*density,Math.min(h*.45f,(float)(h*.42f-e*.6*density)));stripGlow=new RadialGradient(stripX,stripY,22*density,AppUi.alpha(s[3],.45f),s[3]&0x00FFFFFF,Shader.TileMode.CLAMP);}
        fill.setShader(stripShader);c.drawRect(0,0,w,h,fill);fill.setShader(null);
        if(!sky.sun){for(float[] st:stars){if(st[1]>.45f)continue;float a=(.35f+.3f*(float)Math.sin(time*.002+st[3]))*.6f*(sky.kind==MeridianSky.CLEAR?1:.4f);fill.setColor(AppUi.alpha(0xFFFFF8FF,Math.max(0,a)));c.drawCircle(st[0]*w,st[1]*h,.7f*density,fill);}}
        float x=stripX,y=stripY;
        add.setShader(stripGlow);c.drawCircle(x,y,22*density,add);add.setShader(null);
        fill.setColor(AppUi.alpha(s[3],sky.kind==MeridianSky.CLEAR||sky.kind==MeridianSky.SNOW?1:.6f));c.drawCircle(x,y,4.5f*density,fill);
        clouds(c,w,h*.62f,.55f,x/w,y/(h*.62f));
        precipitation(c,w,h,.6f);
    }

    /** Volumetric clouds: a tileable domain-warped fBm field, two parallax layers, lit by marching towards the light. */
    private void clouds(Canvas c,float w,float h,float alpha,float lx,float ly){
        if(field==null)return;long now=SystemClock.uptimeMillis();Bitmap[] layers=tiles;
        if(layers==null){tiles=layers=light(field,sky,time,lx,ly);litAt=now;litSky=sky.sky;}
        else if(!lighting&&(litSky!=sky.sky||AppUi.motion()&&now-litAt>RELIGHT)){
            lighting=true;litAt=now;litSky=sky.sky;final float[] f=field;final MeridianSky at=sky;final float t=time+RELIGHT/2f,x=lx,y=ly;
            LIGHTING.execute(()->{try{tiles=light(f,at,t,x,y);}finally{lighting=false;}});
        }
        if(shaded!=layers){shaded=layers;tileShaders=new BitmapShader[layers.length];for(int i=0;i<layers.length;i++)tileShaders[i]=new BitmapShader(layers[i],Shader.TileMode.REPEAT,Shader.TileMode.CLAMP);}
        tilePaint.setAlpha(Math.round(255*alpha));
        for(int i=0;i<layers.length;i++){
            // Tile column n shows field position n/width; the field drifts by time*speed, so the repeating tile slides left by that fraction.
            float[] L=LAYERS[i];float span=w*L[0],shift=time*L[1]+L[2];shift-=(float)Math.floor(shift);
            tileMatrix.setScale(span/layers[i].getWidth(),h/BH);tileMatrix.postTranslate(-shift*span,0);tileShaders[i].setLocalMatrix(tileMatrix);
            tilePaint.setShader(tileShaders[i]);c.drawRect(0,0,w,h,tilePaint);
        }
        tilePaint.setShader(null);
    }
    /** Lights each layer as a horizontally seamless tile that repeats with filtering across the wrap. Runs off the main thread. */
    private static Bitmap[] light(float[] f,MeridianSky sky,float t,float lx,float ly){
        int[] s=sky.sky;boolean sun=sky.sun;float thr=sky.threshold,op=sky.opacity,dark=sky.darkness;
        int lit=sun?MeridianSky.mix(s[3],0xFFFFFFFF,.35f):0xFFC9BCEB,shadow=MeridianSky.mix(MeridianSky.mix(s[1],0xFF24163F,.35f+dark*.4f),s[0],.2f),mid=MeridianSky.mix(s[2],0xFFFFFFFF,.25f);
        if(!sun){lx=MOON_X;ly=MOON_Y/.62f;}
        Bitmap[] out=new Bitmap[LAYERS.length];
        for(int li=0;li<LAYERS.length;li++){
            float[] L=LAYERS[li];int tw=Math.round(BW*L[0]),width=tw;int[] px=new int[width*BH];float shift=t*L[1]+L[2];
            for(int y=0;y<BH;y++){float v=y/(float)BH,mask=ss(0,.18f,v)*(1-ss(.7f,1,v));if(mask<=0)continue;float vv=v*.9f/L[0]+L[2]*.5f;
                for(int x=0;x<width;x++){float uu=x/(float)tw,d=ss(thr,thr+.22f,sample(f,uu,vv))*mask,dens=d*L[3];if(dens<=.002f)continue;
                    // Where this column sits on screen at time t, for the light direction and the silver lining.
                    float u=uu-shift;u=(u-(float)Math.floor(u))*L[0];
                    float dx=lx-u,dy=ly-v,len=(float)Math.hypot(dx,dy);if(len==0)len=1;float k=.035f/L[0],occ=0;
                    for(int s2=1;s2<=3;s2++)occ+=ss(thr,thr+.22f,sample(f,uu+dx/len*k*s2,vv+dy/len*k*s2*.9f));
                    float light=(float)Math.exp(-occ*.55f*(1+dark*1.4f));
                    float near=Math.max(0,1-(float)Math.hypot((u-lx)*1.4f,v-ly)*1.6f),edge=(1-dens)*near*(sun?1:.4f),l2=Math.min(1,light*.85f+edge*.9f),boost=(float)Math.pow(l2,1.6)*(sun?1:.45f),m=Math.min(1,light*1.2f);
                    int r=channel(shadow>>16,mid>>16,lit>>16,m,boost),g=channel(shadow>>8,mid>>8,lit>>8,m,boost),b=channel(shadow,mid,lit,m,boost);
                    int a=Math.max(0,Math.min(255,Math.round(255*Math.min(1,dens*op*(1.05f-edge*.3f)))));
                    px[y*width+x]=a<<24|r<<16|g<<8|b;
                }}
            out[li]=Bitmap.createBitmap(px,width,BH,Bitmap.Config.ARGB_8888);
        }
        return out;
    }
    private static int channel(int shadow,int mid,int lit,float m,float boost){float s=shadow&255,base=s+((mid&255)-s)*m;return Math.max(0,Math.min(255,Math.round(base+((lit&255)-base)*boost)));}
    private static float sample(float[] f,float u,float v){
        u=u-(float)Math.floor(u);v=Math.max(0,Math.min(.999f,v));float x=u*FW,y=v*(FH-1);int x0=(int)x,y0=(int)y;float fx=x-x0,fy=y-y0;int x1=(x0+1)%FW,y1=Math.min(FH-1,y0+1);x0%=FW;
        return f[y0*FW+x0]*(1-fx)*(1-fy)+f[y0*FW+x1]*fx*(1-fy)+f[y1*FW+x0]*(1-fx)*fy+f[y1*FW+x1]*fx*fy;
    }
    private static float ss(float a,float b,float x){float t=Math.max(0,Math.min(1,(x-a)/(b-a)));return t*t*(3-2*t);}

    private void precipitation(Canvas c,float w,float h,float k){
        if(sky.kind==MeridianSky.RAIN){
            float[] alpha={.14f,.22f,.36f},width={.6f,.9f,1.3f},length={6,11,18};
            for(float[] d:rain){int depth=(int)d[2];float len=length[depth]*density*(k<1?.6f:1);line.setColor(AppUi.alpha(0xFFF4ECFF,alpha[depth]*k));line.setStrokeWidth(width[depth]*density);c.drawLine(d[0]*w,d[1]*h,d[0]*w-len*.2f,d[1]*h-len,line);}
            if(k>=1){line.setStrokeWidth(.7f*density);for(float[] p:splashes){float a=.32f*(1-p[2]/(8*density));if(a<=0)continue;line.setColor(AppUi.alpha(0xFFFFF0FF,a));c.drawOval(p[0]*w-p[2],p[1]*h-p[2]*.3f,p[0]*w+p[2],p[1]*h+p[2]*.3f,line);}}
        }else if(sky.kind==MeridianSky.SNOW){
            float[] alpha={.45f,.65f,.9f},size={.8f,1.3f,2.1f};
            for(float[] d:snow){int depth=(int)d[3];fill.setColor(AppUi.alpha(0xFFFFFFFF,alpha[depth]*k));c.drawCircle(d[0]*w,d[1]*h,size[depth]*density*(k<1?.8f:1),fill);}
        }
    }

    // ---------------------------------------------------------------- page gaps

    private void details(Canvas c,int w,int h){
        boolean dark=ui.dark;int ink=dark?0xFFFFFAFF:0xFF5B35D5;
        if(w!=gapW||h!=gapH){gapW=w;gapH=h;int tone=dark?0xFFC8B9EB:0xFF9682BE;beadShaders=new Shader[beads.length];
            for(int i=0;i<beads.length;i++){float r=beads[i][2]*density;beadShaders[i]=new RadialGradient(-r*.3f,-r*.35f,r*1.3f,new int[]{AppUi.alpha(0xFFFFFFFF,dark?.22f:.55f),AppUi.alpha(ink,dark?.06f:.05f),AppUi.alpha(ink,dark?.10f:.08f)},new float[]{0,.6f,1},Shader.TileMode.CLAMP);}
            mistShader=new RadialGradient(0,0,w*.7f,AppUi.alpha(tone,dark?.06f:.07f),tone&0x00FFFFFF,Shader.TileMode.CLAMP);
            frostShader=new LinearGradient(0,h*.78f,0,h,0x00FFFFFF,AppUi.alpha(dark?0xFFE6E1FF:0xFFFFFFFF,dark?.10f:.55f),Shader.TileMode.CLAMP);
            warmShader=new RadialGradient(0,0,w*.6f,AppUi.alpha(0xFFFFD6AA,dark?.05f:.18f),0x00FFD6AA,Shader.TileMode.CLAMP);}
        if(sky.kind==MeridianSky.RAIN){
            for(int i=0;i<beads.length;i++){float[] b=beads[i];float r=b[2]*density,x=b[0]*w,y=b[1]*h;
                if(trailLength[i]>2){line.setColor(AppUi.alpha(ink,dark?.05f:.045f));line.setStrokeWidth(r*.9f);trail.rewind();float[] t=trails[i];trail.moveTo(t[0]*w,t[1]*h);for(int k=2;k<trailLength[i];k+=2)trail.lineTo(t[k]*w,t[k+1]*h);c.drawPath(trail,line);}
                fill.setShader(beadShaders[i]);c.save();c.translate(x,y);c.drawCircle(0,0,r,fill);c.restore();fill.setShader(null);}
        }
        if(sky.kind==MeridianSky.SNOW){
            for(float[] f:flakes){fill.setColor(AppUi.alpha(dark?0xFFFFFFFF:ink,dark?.18f:.12f));c.drawCircle(f[0]*w,f[1]*h,(1+f[2])*density,fill);}
            fill.setShader(frostShader);c.drawRect(0,h*.78f,w,h,fill);fill.setShader(null);
        }
        if(sky.kind==MeridianSky.RAIN||sky.kind==MeridianSky.CLOUDY&&sky.cover>.6f){
            fill.setShader(mistShader);
            for(float[] m:mist){float rx=w*.7f,ry=h*.08f;c.save();c.translate(m[0]*w,m[1]*h);c.scale(1,ry/rx);c.drawCircle(0,0,rx,fill);c.restore();}fill.setShader(null);
        }
        if(sky.kind==MeridianSky.CLEAR){
            if(sky.sun){float px=w*(.85f+(float)Math.sin(time*.0002)*.05f),py=h*.42f;fill.setShader(warmShader);c.save();c.translate(px,py);c.drawRect(-px,-py,w-px,h-py,fill);c.restore();fill.setShader(null);}
            else for(float[] st:stars){if(st[1]<.3f)continue;fill.setColor(AppUi.alpha(0xFFE6DCFF,Math.max(0,.12f+.1f*(float)Math.sin(time*.0015+st[3]))));c.drawCircle(st[0]*w,.2f*h+st[1]*h*.9f,.8f*density,fill);}
        }
    }

    // ---------------------------------------------------------------- motion

    private void step(float dt){
        if(sky.kind==MeridianSky.RAIN){
            float[] speed={.006f,.010f,.016f};
            for(float[] d:rain){int depth=(int)d[2];float sp=speed[depth]*dt*(hero?1:.55f);d[1]+=sp;d[0]+=sp*.2f;
                if(d[1]>1||depth==2&&hero&&d[1]>.82f&&random.nextFloat()<.04f*dt){if(depth==2&&hero&&splashes.size()<40)splashes.add(new float[]{d[0],.84f+random.nextFloat()*.06f,0});d[1]=-.05f;d[0]=random.nextFloat()*1.1f-.1f;}}
            for(int i=splashes.size()-1;i>=0;i--){float[] p=splashes.get(i);p[2]+=.32f*density*dt;if(p[2]>=8*density)splashes.remove(i);}
            for(int i=0;i<beads.length;i++){float[] b=beads[i];if(b[3]==0&&random.nextFloat()<.0008f*dt)b[3]=1;
                if(b[3]==1){float[] t=trails[i];if(trailLength[i]>=80){System.arraycopy(t,2,t,0,78);trailLength[i]=78;}t[trailLength[i]]=b[0];t[trailLength[i]+1]=b[1];trailLength[i]+=2;
                    b[1]+=.0012f*dt;b[0]+=(float)Math.sin(b[1]*40)*.0003f*dt;if(b[1]>1.02f){b[1]=random.nextFloat()*.3f;b[0]=random.nextFloat();b[3]=0;trailLength[i]=0;}}}
            for(float[] m:mist){m[0]+=m[2]*dt;if(m[0]>1.5f)m[0]=-.8f;}
        }else if(sky.kind==MeridianSky.SNOW){
            float[] speed={.0007f,.0012f,.0019f};
            for(float[] d:snow){int depth=(int)d[3];d[1]+=speed[depth]*dt*(hero?1:.6f);d[0]+=(float)Math.sin(d[1]*8+d[2]*6+time*.0008)*.0004f*(depth+1)*dt;if(d[1]>1.02f){d[1]=-.02f;d[0]=random.nextFloat();}}
            for(float[] f:flakes){f[1]+=.00045f*dt;f[0]+=(float)Math.sin(f[1]*10+f[2]*6)*.00025f*dt;if(f[1]>1){f[1]=0;f[0]=random.nextFloat();}}
        }else for(float[] m:mist){m[0]+=m[2]*dt;if(m[0]>1.5f)m[0]=-.8f;}
    }

    // ---------------------------------------------------------------- generated once

    /** The approved preview's landscape: the same Park-Miller sequence (seed 7) draws the ridges, spruces and stars. */
    private static synchronized void landscape(){
        if(ridges!=null)return;long[] seed={7};
        ridges=new float[][]{ridge(seed,256,.58,true),ridge(seed,256,.52,true),ridge(seed,256,.42,false),ridge(seed,256,.38,false)};
        trees=new float[70][];for(int i=0;i<70;i++)trees[i]=new float[]{(float)rand(seed),.6f+(float)rand(seed)*.8f};
        stars=new float[110][];for(int i=0;i<110;i++)stars[i]=new float[]{(float)rand(seed),(float)rand(seed)*.62f,(float)rand(seed),(float)rand(seed)*7};
    }
    private static double rand(long[] seed){seed[0]=seed[0]*16807%2147483647;return (seed[0]-1)/2147483646d;}
    private static float[] ridge(long[] seed,int n,double rough,boolean sharp){
        double[] a=new double[n+1];a[0]=rand(seed);a[n]=rand(seed);int step=n;double amp=1;
        while(step>1){int half=step/2;for(int i=half;i<n;i+=step)a[i]=(a[i-half]+a[i+half])/2+(rand(seed)-.5)*amp;amp*=rough;step=half;}
        double mn=a[0],mx=a[0];for(double v:a){mn=Math.min(mn,v);mx=Math.max(mx,v);}
        float[] out=new float[n+1];for(int i=0;i<=n;i++){double t=(a[i]-mn)/(mx-mn);out[i]=(float)(sharp?Math.pow(t,1.6):t);}return out;
    }
    /** The cloud field takes a moment to build, so it is made once per process off the main thread. */
    private static synchronized void buildField(){
        if(field!=null||building)return;building=true;
        new Thread(()->{
            java.util.HashMap<Long,Float> lattice=new java.util.HashMap<>();long[] seed={1234567};float[] out=new float[FW*FH];
            for(int y=0;y<FH;y++)for(int x=0;x<FW;x++){double u=x/(double)FW,v=y/(double)FH,wx=fbm(lattice,seed,u,v,10)-.5,wy=fbm(lattice,seed,u+.3,v,20)-.5;out[y*FW+x]=(float)fbm(lattice,seed,u+wx*.12,v+wy*.25,0);}
            float mn=1,mx=0;for(float v:out){mn=Math.min(mn,v);mx=Math.max(mx,v);}for(int i=0;i<out.length;i++)out[i]=(out[i]-mn)/(mx-mn);
            field=out;
        },"meridian-clouds").start();
    }
    private static double fbm(java.util.HashMap<Long,Float> lattice,long[] seed,double u,double v,int base){
        double s=0,amp=.5;int f=1;for(int o=0;o<6;o++){int per=6*f;s+=amp*noise(lattice,seed,u*per,v*per*.9+o*17,per,o+base);amp*=.5;f*=2;}return s;
    }
    private static double noise(java.util.HashMap<Long,Float> lattice,long[] seed,double x,double y,int per,int o){
        int x0=(int)Math.floor(x),y0=(int)Math.floor(y);double fx=x-x0,fy=y-y0,sx=fx*fx*(3-2*fx),sy=fy*fy*(3-2*fy);int X0=((x0%per)+per)%per,X1=(X0+1)%per;
        double a=hash(lattice,seed,X0,y0,o),b=hash(lattice,seed,X1,y0,o),c=hash(lattice,seed,X0,y0+1,o),d=hash(lattice,seed,X1,y0+1,o);
        return a+(b-a)*sx+(c-a)*sy+(a-b-c+d)*sx*sy;
    }
    private static float hash(java.util.HashMap<Long,Float> lattice,long[] seed,int x,int y,int o){
        long key=((long)x*100000L+y)*64L+o;Float hit=lattice.get(key);if(hit!=null)return hit;float v=(float)rand(seed);lattice.put(key,v);return v;
    }
}
