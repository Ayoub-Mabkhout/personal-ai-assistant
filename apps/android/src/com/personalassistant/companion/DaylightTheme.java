package com.personalassistant.companion;

/** Local sunrise/sunset calculation using explicitly configured, private coordinates. */
final class DaylightTheme {
    private static final double RAD=Math.PI/180,DAY=86400000d,J1970=2440588,J2000=2451545,J0=0.0009;
    private static final long POLAR_RECHECK=3600000L;
    private DaylightTheme(){}

    static boolean valid(double latitude,double longitude){return Double.isFinite(latitude)&&Double.isFinite(longitude)&&Math.abs(latitude)<=90&&Math.abs(longitude)<=180;}

    private static final class SolarDay {
        final long[] times;final boolean alwaysLight;
        SolarDay(long[] times,boolean alwaysLight){this.times=times;this.alwaysLight=alwaysLight;}
    }

    private static SolarDay cycle(long at,double latitude,double longitude){
        if(!valid(latitude,longitude))throw new IllegalArgumentException("Finite daylight coordinates within latitude/longitude bounds required");
        double d=at/DAY-0.5+J1970-J2000,lw=-longitude*RAD,phi=latitude*RAD;
        long n=Math.round(d-J0-lw/(2*Math.PI));
        double ds=J0+lw/(2*Math.PI)+n,m=RAD*(357.5291+0.98560028*ds),c=RAD*(1.9148*Math.sin(m)+0.02*Math.sin(2*m)+0.0003*Math.sin(3*m));
        double l=m+c+RAD*102.9372+Math.PI,dec=Math.asin(Math.sin(l)*Math.sin(RAD*23.4397));
        double transit=J2000+ds+0.0053*Math.sin(m)-0.0069*Math.sin(2*l);
        double cosW=(Math.sin(-0.833*RAD)-Math.sin(phi)*Math.sin(dec))/(Math.cos(phi)*Math.cos(dec));
        if(cosW>=1)return new SolarDay(null,false);
        if(cosW<=-1)return new SolarDay(null,true);
        double set=J2000+J0+(Math.acos(cosW)+lw)/(2*Math.PI)+n+0.0053*Math.sin(m)-0.0069*Math.sin(2*l),rise=transit-(set-transit);
        return new SolarDay(new long[]{Math.round((rise+0.5-J1970)*DAY),Math.round((set+0.5-J1970)*DAY)},false);
    }

    /** Events for the nearest solar-noon cycle; UTC dates can cross civil midnight. */
    static long[] sunTimes(long at,double latitude,double longitude){return cycle(at,latitude,longitude).times;}

    static boolean dark(long at,double latitude,double longitude){
        SolarDay today=cycle(at,latitude,longitude);
        // A nearest-cycle switch can happen before the previous cycle's sunset.
        for(int offset=-1;offset<=1;offset++){
            long[] times=cycle(at+offset*(long)DAY,latitude,longitude).times;
            if(times!=null&&at>=times[0]&&at<times[1])return false;
        }
        return today.times==null?!today.alwaysLight:true;
    }

    /** Earliest future transition, or an hourly polar reevaluation when no nearby event exists. */
    static long nextChange(long at,double latitude,double longitude){
        long next=Long.MAX_VALUE;
        for(int offset=-1;offset<=2;offset++){
            long[] times=cycle(at+offset*(long)DAY,latitude,longitude).times;
            if(times==null)continue;
            for(long event:times)if(event>at&&event<next&&dark(event-1,latitude,longitude)!=dark(event,latitude,longitude))next=event;
        }
        return next==Long.MAX_VALUE?at+POLAR_RECHECK:next;
    }

    /** Missing or invalid daylight configuration follows the phone's System theme. */
    static boolean resolve(String mode,boolean systemDark,long at,Double latitude,Double longitude){
        if("light".equals(mode))return false;
        if("dark".equals(mode))return true;
        if("sun".equals(mode)&&latitude!=null&&longitude!=null&&valid(latitude,longitude))return dark(at,latitude,longitude);
        return systemDark;
    }

    static final class Refresh {
        final boolean apply;final long delay;
        Refresh(boolean apply,long delay){this.apply=apply;this.delay=delay;}
    }

    /** A blocked boundary is retried while foreground; fixed/System themes require no solar timer. */
    static Refresh refresh(boolean displayedDark,boolean desiredDark,boolean ready,long at,long next){
        if(displayedDark!=desiredDark)return new Refresh(ready,ready?Long.MAX_VALUE:1000L);
        return new Refresh(false,next==Long.MAX_VALUE?Long.MAX_VALUE:Math.max(1,next-at));
    }
}
