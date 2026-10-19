package com.personalassistant.companion;

import android.content.Context;
import android.content.SharedPreferences;
import java.util.Calendar;
import java.util.TimeZone;

/**
 * What the Meridian sky shows at one moment: the sun's elevation for the Daylight place, the Aurora sky colours blended
 * between night, dawn or golden hour and day (in linear light), today's sunrise and sunset, and the current weather
 * from the last Open-Meteo reading. Pages keep the Dusk Aurora light and dark palettes; only the sky follows the sun.
 */
final class MeridianSky {
    static final int CLEAR=0,CLOUDY=1,RAIN=2,SNOW=3;
    // Top, middle and horizon of the sky, then the sun or moon light colour.
    static final int[] NIGHT={0xFF0B0716,0xFF1A1030,0xFF2B1B4C,0xFFE8E0FF},DAWN={0xFF2E2266,0xFF7E4AB2,0xFFF2A3B4,0xFFFFE6D8},
        DAY={0xFF6F55E6,0xFFA88AF0,0xFFF4D3E4,0xFFFFF8EC},GOLD={0xFF3E2478,0xFF9A3AC0,0xFFF2876F,0xFFFFD7A8};

    final long at;final double elevation;final boolean morning,sun,known;final int[] sky;
    final int kind;final float cover,threshold,opacity,darkness,desaturate;final String condition,icon,temperature,place;
    /** Sunrise and sunset today in epoch milliseconds, or -1 during polar day or night. */
    final long sunrise,sunset;final float sunX;

    private MeridianSky(long at,double[] place,int code,float cloud,float temp,boolean fresh,String locality){
        this.at=at;double[] s=DaylightPalette.sun(at,place[0],place[1]);elevation=s[0];morning=s[1]<0;sun=elevation>-3;
        long[] day=sunTimes(at,place[0],place[1]);sunrise=day[0];sunset=day[1];
        if(sunrise>0&&sunset>sunrise){float f=(float)(at-sunrise+3600000L)/(sunset-sunrise+7200000L);sunX=Math.max(.08f,Math.min(.92f,f));}else sunX=.5f;
        known=fresh&&code>=0;kind=!known?CLEAR:kindOf(code);
        float c=Float.isNaN(cloud)?(kind==CLEAR?(code==1?.25f:.1f):.9f):Math.max(0,Math.min(1,cloud/100f));if(!known)c=.25f;cover=c;
        if(kind==RAIN){threshold=.34f;opacity=.98f;darkness=.45f;desaturate=.45f;}
        else if(kind==SNOW){threshold=.38f;opacity=.93f;darkness=.05f;desaturate=.30f;}
        else{threshold=.74f-.34f*c;opacity=.75f+.20f*c;darkness=.15f*c*c;desaturate=c>.55f?.5f*(c-.55f)/.45f:0;}
        sky=tint(skyAt(elevation,morning),kind,desaturate);
        condition=known?label(code):"";icon=!known?"":kind==RAIN?"weather-rain":kind==SNOW?"weather-snow":code==45||code==48?"weather-fog":kind==CLOUDY||code==2?"weather-cloud":sun?"weather-sun":"weather-moon";
        temperature=known&&!Float.isNaN(temp)?Math.round(temp)+"°":"";this.place=locality==null?"":locality;
    }

    /** A look at another hour or weather, from the launcher intent extras meridian_minute and meridian_weather; cosmetic only. */
    private static volatile long previewShift;private static volatile int previewCode=-2;
    static void preview(int minute,int code){
        if(minute>=0){Calendar day=Calendar.getInstance();long now=day.getTimeInMillis();day.set(Calendar.HOUR_OF_DAY,minute/60);day.set(Calendar.MINUTE,minute%60);previewShift=day.getTimeInMillis()-now;}
        previewCode=code;
    }
    static long clock(long at){return at+previewShift;}

    static MeridianSky now(Context c){return at(c,clock(System.currentTimeMillis()));}
    static MeridianSky at(Context c,long at){
        SharedPreferences p=Cloud.prefs(c);
        if(previewCode>=-1){double[] place=AppUi.meridianPlace(c);int code=previewCode;return new MeridianSky(at,place,code,Float.NaN,code>=71&&code<=86?-1:code>=51?9:14,code>=0,p.getString("daylight_locality",""));}long when=p.getLong("daylight_weather_at",0);boolean fresh=DaylightWeather.enabled(c)&&when>0&&at>=when&&at-when<=DaylightWeather.STALE;
        double[] place=AppUi.meridianPlace(c);
        return new MeridianSky(at,place,fresh?p.getInt("daylight_weather_code",-1):-1,p.getFloat("daylight_weather_cover",Float.NaN),p.getFloat("daylight_weather_temp",Float.NaN),fresh,AppUi.daylightPlace(c)==null?"":p.getString("daylight_locality",""));
    }
    /** For previews and tests: a fixed place, weather code, cloud cover and temperature. */
    static MeridianSky of(long at,double latitude,double longitude,int code,float cloud,float temp,String locality){return new MeridianSky(at,new double[]{latitude,longitude},code,cloud,temp,code>=0,locality);}

    /** Pages switch between the Light and Dark palettes as the sun's upper limb crosses the horizon. */
    boolean darkPage(){return elevation<DaylightPalette.HANDOFF;}

    static int kindOf(int code){
        if(code>=71&&code<=77||code==85||code==86)return SNOW;
        if(code>=51&&code<=67||code>=80&&code<=82||code>=95)return RAIN;
        return code<=1?CLEAR:CLOUDY;
    }
    static String label(int code){
        switch(code){case 0:return "Clear";case 1:return "Mainly clear";case 2:return "Partly cloudy";case 3:return "Overcast";case 45:case 48:return "Fog";
            case 51:case 53:case 55:return "Drizzle";case 56:case 57:return "Freezing drizzle";case 61:case 63:return "Rain";case 65:return "Heavy rain";case 66:case 67:return "Freezing rain";
            case 71:case 73:return "Snow";case 75:return "Heavy snow";case 77:return "Snow grains";case 80:case 81:case 82:return "Showers";case 85:case 86:return "Snow showers";
            case 95:return "Thunderstorm";case 96:case 99:return "Thunderstorm, hail";default:return "";}
    }

    /** Aurora sky: day above 12 degrees, twilight (dawn before noon, golden hour after) blending to night by -10 degrees. */
    static int[] skyAt(double e,boolean morning){
        int[] twilight=morning?DAWN:GOLD;
        if(e>=12)return DAY.clone();if(e>=0)return mix(twilight,DAY,smooth(0,12,e));if(e>=-10)return mix(NIGHT,twilight,smooth(-10,0,e));return NIGHT.clone();
    }
    static int[] tint(int[] colors,int kind,float d){
        if(d<=0)return colors;int[] out=new int[colors.length];float lift=kind==SNOW?12:-16;
        for(int i=0;i<colors.length;i++){int c=colors[i];float r=(c>>16)&255,g=(c>>8)&255,b=c&255,grey=(r+g+b)/3;
            out[i]=0xFF000000|clamp(r+(grey-r)*d*.7f+lift*d)<<16|clamp(g+(grey-g)*d*.7f+lift*d)<<8|clamp(b+(grey-b)*d*.7f+lift*d);}
        return out;
    }
    private static int clamp(float v){return Math.max(0,Math.min(255,Math.round(v)));}
    static float smooth(double a,double b,double x){double t=Math.max(0,Math.min(1,(x-a)/(b-a)));return (float)(t*t*(3-2*t));}
    static int[] mix(int[] a,int[] b,float t){int[] out=new int[a.length];for(int i=0;i<a.length;i++)out[i]=mix(a[i],b[i],t);return out;}
    /** Mixes in linear light so twilight passes through luminous rose rather than muddy grey. */
    static int mix(int a,int b,float t){t=Math.max(0,Math.min(1,t));return 0xFF000000|ch(a>>16,b>>16,t)<<16|ch(a>>8,b>>8,t)<<8|ch(a,b,t);}
    private static int ch(int a,int b,float t){double x=lin(a&255),y=lin(b&255),v=x+(y-x)*t;return (int)Math.round(255*(v<=.0031308?12.92*v:1.055*Math.pow(v,1/2.4)-.055));}
    private static double lin(int c){double v=c/255d;return v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4);}

    /** Today's sunrise and sunset (upper limb at -0.833 degrees) found by stepping the local day in two-minute steps. */
    static long[] sunTimes(long at,double latitude,double longitude){
        Calendar day=Calendar.getInstance(TimeZone.getDefault());day.setTimeInMillis(at);day.set(Calendar.HOUR_OF_DAY,0);day.set(Calendar.MINUTE,0);day.set(Calendar.SECOND,0);day.set(Calendar.MILLISECOND,0);
        long start=day.getTimeInMillis(),rise=-1,set=-1;double previous=DaylightPalette.sun(start,latitude,longitude)[0]-DaylightPalette.HANDOFF;
        for(long t=start+120000L;t<=start+86400000L;t+=120000L){
            double now=DaylightPalette.sun(t,latitude,longitude)[0]-DaylightPalette.HANDOFF;
            if(previous<0&&now>=0&&rise<0)rise=t-Math.round(120000L*now/(now-previous));
            if(previous>=0&&now<0&&set<0)set=t-Math.round(120000L*now/(now-previous));
            previous=now;
        }
        return new long[]{rise,set};
    }
}
