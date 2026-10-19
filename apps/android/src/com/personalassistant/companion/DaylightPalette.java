package com.personalassistant.companion;

/**
 * Meridian: one continuous Dusk Aurora palette that follows the sun. Every token is interpolated in OKLab between keyframes
 * anchored to solar elevation (NOAA solar position, no network): night, blue-hour/ember twilight, rose dawn or amber golden
 * hour, and day. Morning and evening keyframes are weighted by the hour angle, so polar days and nights stay continuous.
 * Surfaces remain continuous through sunrise and sunset. Foreground polarity changes only where both black and white
 * can meet AA contrast; foreground colours are corrected against the actual interpolated surfaces. An optional weather level (0 clear to 1 storm)
 * desaturates and dims a little. No Android dependencies, so the JVM tests compile it directly.
 */
final class DaylightPalette {
    private DaylightPalette(){}
    static final int BACKGROUND=0,SURFACE=1,SURFACE_ALT=2,TEXT=3,MUTED=4,ACCENT=5,ON_ACCENT=6,ACCENT_SOFT=7,STROKE=8,STROKE_STRONG=9,
        SUCCESS=10,SUCCESS_SOFT=11,WARNING=12,WARNING_SOFT=13,DANGER=14,DANGER_SOFT=15,INFO=16,INFO_SOFT=17,GLOW=18,AURORA=19,COUNT=22;
    /** Solar elevations in degrees: night below NIGHT, day plateau above DAY, polarity flip at HANDOFF. */
    static final double NIGHT=-12,HANDOFF=-0.833,DAY=10;
    /** A displayed palette is repainted when any token moved this far in OKLab, or when the polarity flips. */
    static final double REPAINT=0.015;
    static final long TICK=60000L;

    // Token order: background surface surfaceAlt text muted accent onAccent accentSoft stroke strokeStrong success successSoft
    // warning warningSoft danger dangerSoft info infoSoft glow aurora0 aurora1 aurora2. DAY and NIGHT are the Light and Dark modes.
    static final int[] DAY_KEY=rgb(0xFAF5EC,0xFFFEFB,0xF3ECE4,0x231A2E,0x675C73,0x5B35D5,0xFFFFFF,0xECE5FF,0xE7DDD3,0x8E829E,0x17784A,0xE0F2E7,0x965800,0xFFEFCF,0xB3263E,0xFCE3E7,0x3D52CC,0xE3E8FF,0x8EA2FF,0x5B35D5,0xA23BC6,0xCC3F78);
    static final int[] DAWN_KEY=rgb(0xF8EEEE,0xFFFBFA,0xF1E3E6,0x271A2C,0x6A5A6E,0x5833CF,0xFFFFFF,0xEEE2FA,0xE8D8DC,0x908096,0x17754A,0xE1F0E6,0x935500,0xFDEBD3,0xB02443,0xFADFE5,0x3C4FC6,0xE5E4FA,0xF5A6C8,0x5B35D5,0xA83BBF,0xD6497A);
    static final int[] GOLDEN_KEY=rgb(0xF7EADB,0xFFF8EF,0xF0DFCC,0x2A1B22,0x6E5560,0x5A2FC0,0xFFFFFF,0xF0E0F5,0xE6D2BE,0x937A86,0x17734A,0xE3EFDB,0x8F5200,0xFBE6C4,0xAD2440,0xF9DCDC,0x3B4CC0,0xE6E3F7,0xFFB38E,0x5B35D5,0xB8399F,0xD9535E);
    static final int[] NIGHT_KEY=rgb(0x130E1C,0x1D1729,0x281F38,0xF5F0FB,0xADA3BF,0xB39CFF,0x1B1230,0x2E2357,0x322849,0x8479A3,0x74DFA5,0x173A2A,0xFFC766,0x3E2D10,0xFF8FA0,0x44192A,0xA4B5FF,0x232B5C,0x8FA8FF,0x8E6BFF,0xC46CF0,0xF08FC4);
    static final int[] BLUE_HOUR_KEY=rgb(0x141428,0x1E1D35,0x292844,0xF2F1FC,0xA9A8C6,0xAFA4FF,0x18143A,0x2C2A5E,0x34345A,0x8282AE,0x78DDB0,0x163A33,0xFFC978,0x3C2F18,0xFF93AE,0x431C33,0xA0BBFF,0x222E62,0x9FB4FF,0x7F70FF,0xB56EF0,0xF28FC0);
    static final int[] EMBER_KEY=rgb(0x1E1220,0x2A1B2C,0x36233A,0xFBF0F3,0xC0A8B6,0xC4A2FF,0x1F1228,0x3A2450,0x433048,0x9A7F99,0x7FDDA6,0x1D3A2A,0xFFC46E,0x45301A,0xFF96A2,0x4B1B2C,0xAEB6FF,0x2A2A5A,0xFF9E8A,0x9A6BFF,0xD46BD8,0xFF9A8A);
    private static final double[][] DAY_LAB=lab(DAY_KEY),DAWN_LAB=lab(DAWN_KEY),GOLDEN_LAB=lab(GOLDEN_KEY),NIGHT_LAB=lab(NIGHT_KEY),BLUE_LAB=lab(BLUE_HOUR_KEY),EMBER_LAB=lab(EMBER_KEY);
    private static final boolean[] SURFACES=new boolean[COUNT];
    static{SURFACES[BACKGROUND]=SURFACES[SURFACE]=SURFACES[SURFACE_ALT]=SURFACES[STROKE]=true;}

    private static int[] rgb(int... values){int[] out=new int[values.length];for(int i=0;i<values.length;i++)out[i]=0xFF000000|values[i];return out;}
    static int[] fixed(boolean dark){return (dark?NIGHT_KEY:DAY_KEY).clone();}

    /** Solar elevation in degrees and hour angle in radians (negative before solar noon), NOAA solar position equations. */
    static double[] sun(long at,double latitude,double longitude){
        double r=Math.PI/180,jd=at/86400000d+2440587.5,t=(jd-2451545)/36525;
        double l0=((280.46646+t*(36000.76983+t*0.0003032))%360+360)%360,m=357.52911+t*(35999.05029-0.0001537*t),e=0.016708634-t*(0.000042037+0.0000001267*t);
        double c=Math.sin(m*r)*(1.914602-t*(0.004817+0.000014*t))+Math.sin(2*m*r)*(0.019993-0.000101*t)+Math.sin(3*m*r)*0.000289;
        double omega=125.04-1934.136*t,lambda=l0+c-0.00569-0.00478*Math.sin(omega*r);
        double epsilon=23+(26+(21.448-t*(46.815+t*(0.00059-t*0.001813)))/60)/60+0.00256*Math.cos(omega*r);
        double declination=Math.asin(Math.sin(epsilon*r)*Math.sin(lambda*r)),y=Math.pow(Math.tan(epsilon*r/2),2);
        double equation=4/r*(y*Math.sin(2*l0*r)-2*e*Math.sin(m*r)+4*e*y*Math.sin(m*r)*Math.cos(2*l0*r)-0.5*y*y*Math.sin(4*l0*r)-1.25*e*e*Math.sin(2*m*r));
        double minutes=((at%86400000L)+86400000L)%86400000L/60000d,hour=((minutes+equation+4*longitude)/4-180)%360;
        if(hour<-180)hour+=360;if(hour>=180)hour-=360;
        double phi=latitude*r,cos=Math.sin(phi)*Math.sin(declination)+Math.cos(phi)*Math.cos(declination)*Math.cos(hour*r);
        return new double[]{90-Math.acos(Math.max(-1,Math.min(1,cos)))/r,hour*r};
    }

    /** The palette for a moment and place; weather 0 keeps the clear-sky colours. */
    static int[] at(long at,double latitude,double longitude,double weather){
        if(!DaylightTheme.valid(latitude,longitude))throw new IllegalArgumentException("Configured coordinates required");
        double[] s=sun(at,latitude,longitude);return blend(s[0],.5-.5*Math.sin(s[1]),weather);
    }

    /** Elevation in degrees, morning weight 0 (evening) to 1 (morning), weather 0 to 1. */
    static int[] blend(double elevation,double morning,double weather){
        double w=clamp(weather);morning=clamp(morning);
        double t=smooth((elevation-NIGHT)/(DAY-NIGHT));
        if(w==0&&t>=1)return fixed(false);if(w==0&&t<=0)return fixed(true);
        int[] out=new int[COUNT];
        double edgeWeight=1-Math.abs(2*t-1);
        for(int i=0;i<COUNT;i++){
            double[] twilight=mix(EMBER_LAB[i],BLUE_LAB[i],morning),warm=mix(GOLDEN_LAB[i],DAWN_LAB[i],morning);
            double[] p=mix(mix(NIGHT_LAB[i],twilight,smooth(Math.min(1,t*3))),mix(warm,DAY_LAB[i],smooth(Math.max(0,(t-.5)*2))),t);
            if(w>0){double f=1-.3*w;p=new double[]{p[0]-(SURFACES[i]?.025*w:0),p[1]*f,p[2]*f};}
            out[i]=fromLab(p);
        }
        protect(out);return out;
    }

    /** Keep surfaces continuous; collapse their tonal spread near the foreground crossover. */
    private static void protect(int[] out){
        double base=luminance(out[BACKGROUND]),spread=Math.pow(Math.min(1,Math.abs(base-.179)/.12),2);
        int[] backgrounds={BACKGROUND,SURFACE,SURFACE_ALT,ACCENT_SOFT,SUCCESS_SOFT,WARNING_SOFT,DANGER_SOFT,INFO_SOFT};
        for(int i:backgrounds)if(i!=BACKGROUND)out[i]=fromLab(mix(lab(out[BACKGROUND]),lab(out[i]),spread));
        int end=base<.179?0xFFFFFFFF:0xFF000000;
        // Quantised sRGB and gamut clipping are included in the final contrast calculation.
        for(int i:backgrounds)if(contrast(end,out[i])<4.55)out[i]=readableSurface(out[i],out[BACKGROUND],end);
        for(int i:new int[]{TEXT,MUTED})out[i]=readable(out[i],end,out,backgrounds);
        out[ACCENT]=readable(out[ACCENT],end,out,new int[]{BACKGROUND,SURFACE,SURFACE_ALT,ACCENT_SOFT});
        for(int[] pair:new int[][]{{SUCCESS,SUCCESS_SOFT},{WARNING,WARNING_SOFT},{DANGER,DANGER_SOFT},{INFO,INFO_SOFT}})
            out[pair[0]]=readable(out[pair[0]],end,out,new int[]{BACKGROUND,SURFACE,SURFACE_ALT,pair[1]});
        int[] fills={ACCENT,AURORA,AURORA+1};
        int fillEnd=luminance(out[ACCENT])<.179?0xFFFFFFFF:0xFF000000;
        for(int i:fills)if(contrast(fillEnd,out[i])<4.55)out[i]=readableSurface(out[i],out[ACCENT],fillEnd);
        out[ON_ACCENT]=readable(out[ON_ACCENT],fillEnd,out,fills);
    }
    private static int readableSurface(int color,int anchor,int front){
        for(int n=1;n<=32;n++){int c=fromLab(mix(lab(color),lab(anchor),n/32d));if(contrast(front,c)>=4.55)return c;}
        return anchor;
    }
    private static int readable(int color,int end,int[] palette,int[] backgrounds){
        if(readable(color,palette,backgrounds))return color;
        double[] a=lab(color),b=lab(end);double lo=0,hi=1;
        for(int n=0;n<18;n++){double mid=(lo+hi)/2;int c=fromLab(mix(a,b,mid));if(readable(c,palette,backgrounds))hi=mid;else lo=mid;}
        return fromLab(mix(a,b,Math.min(1,hi+.002)));
    }
    private static boolean readable(int color,int[] palette,int[] backgrounds){for(int i:backgrounds)if(contrast(color,palette[i])<4.52)return false;return true;}

    /** WMO weather code and cloud cover (percent) as a 0..1 gloom level; negative codes mean unknown. */
    static double weatherLevel(int code,double cloud){
        double level=code<0?0:code<=0?0:code==1?.15:code==2?.35:code==3?.6:code==45||code==48?.8:code>=51&&code<=57?.65:code>=61&&code<=67?.8:code>=71&&code<=77?.7:code>=80&&code<=82?.75:code==85||code==86?.7:code>=95&&code<=99?1:0;
        if(Double.isFinite(cloud))level=Math.max(level,.6*clamp(cloud/100));
        return level;
    }

    /** Light status/navigation bar icons go on a light page; WCAG relative luminance of the background decides. */
    static boolean dark(int[] palette){return luminance(palette[BACKGROUND])<.179;}
    static boolean differs(int[] shown,int[] wanted){
        if(shown==null||wanted==null||shown.length!=wanted.length)return true;if(dark(shown)!=dark(wanted))return true;
        for(int i=0;i<shown.length;i++)if(distance(shown[i],wanted[i])>REPAINT)return true;
        return false;
    }
    /** Repaints when the shown palette drifted; otherwise rechecks every minute while the host is in the foreground. */
    static DaylightTheme.Refresh refresh(int[] shown,int[] wanted,boolean ready){return differs(shown,wanted)?new DaylightTheme.Refresh(ready,ready?Long.MAX_VALUE:1000L):new DaylightTheme.Refresh(false,TICK);}

    static double luminance(int color){return .2126*linear((color>>16)&255)+.7152*linear((color>>8)&255)+.0722*linear(color&255);}
    static double contrast(int a,int b){double x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
    static double distance(int a,int b){double[] p=lab(a),q=lab(b);return Math.sqrt((p[0]-q[0])*(p[0]-q[0])+(p[1]-q[1])*(p[1]-q[1])+(p[2]-q[2])*(p[2]-q[2]));}

    private static double clamp(double v){return Double.isNaN(v)?0:Math.max(0,Math.min(1,v));}
    private static double smooth(double v){v=clamp(v);return v*v*(3-2*v);}
    private static double[] mix(double[] a,double[] b,double t){return new double[]{a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t,a[2]+(b[2]-a[2])*t};}
    private static double linear(int c){double v=c/255d;return v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4);}
    private static int encode(double v){v=Math.max(0,Math.min(1,v));return (int)Math.round(255*(v<=.0031308?12.92*v:1.055*Math.pow(v,1/2.4)-.055));}
    private static double[][] lab(int[] colors){double[][] out=new double[colors.length][];for(int i=0;i<colors.length;i++)out[i]=lab(colors[i]);return out;}
    static double[] lab(int color){
        double r=linear((color>>16)&255),g=linear((color>>8)&255),b=linear(color&255);
        double l=Math.cbrt(.4122214708*r+.5363325363*g+.0514459929*b),m=Math.cbrt(.2119034982*r+.6806995451*g+.1073969566*b),s=Math.cbrt(.0883024619*r+.2817188376*g+.6299787005*b);
        return new double[]{.2104542553*l+.7936177850*m-.0040720468*s,1.9779984951*l-2.4285922050*m+.4505937099*s,.0259040371*l+.7827717662*m-.8086757660*s};
    }
    static int fromLab(double[] p){
        double l=Math.pow(p[0]+.3963377774*p[1]+.2158037573*p[2],3),m=Math.pow(p[0]-.1055613458*p[1]-.0638541728*p[2],3),s=Math.pow(p[0]-.0894841775*p[1]-1.2914855480*p[2],3);
        return 0xFF000000|encode(4.0767416621*l-3.3077115913*m+.2309699292*s)<<16|encode(-1.2684380046*l+2.6097574011*m-.3413193965*s)<<8|encode(-.0041960863*l-.7034186147*m+1.7076147010*s);
    }
}
