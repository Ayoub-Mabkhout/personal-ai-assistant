package com.personalassistant.companion;

/** Light by day, dark after sunset, computed on the phone from the sun's position for one fixed place. */
final class DaylightTheme {
    static final double LATITUDE=48.137,LONGITUDE=11.575;
    private static final double RAD=Math.PI/180,DAY=86400000d,J1970=2440588,J2000=2451545,J0=0.0009;
    private DaylightTheme(){}

    /** Sunrise and sunset in epoch milliseconds around the given instant; null when the sun never rises or never sets. */
    static long[] sunTimes(long at,double latitude,double longitude){double d=at/DAY-0.5+J1970-J2000,lw=-longitude*RAD,phi=latitude*RAD;long n=Math.round(d-J0-lw/(2*Math.PI));double ds=J0+lw/(2*Math.PI)+n,m=RAD*(357.5291+0.98560028*ds),c=RAD*(1.9148*Math.sin(m)+0.02*Math.sin(2*m)+0.0003*Math.sin(3*m)),l=m+c+RAD*102.9372+Math.PI,dec=Math.asin(Math.sin(l)*Math.sin(RAD*23.4397)),transit=J2000+ds+0.0053*Math.sin(m)-0.0069*Math.sin(2*l),cosW=(Math.sin(-0.833*RAD)-Math.sin(phi)*Math.sin(dec))/(Math.cos(phi)*Math.cos(dec));if(cosW>=1||cosW<=-1)return null;double set=J2000+J0+(Math.acos(cosW)+lw)/(2*Math.PI)+n+0.0053*Math.sin(m)-0.0069*Math.sin(2*l),rise=transit-(set-transit);return new long[]{Math.round((rise+0.5-J1970)*DAY),Math.round((set+0.5-J1970)*DAY)};}

    static boolean dark(long at){long[] today=sunTimes(at,LATITUDE,LONGITUDE);if(today==null)return polarNight(at);return at<today[0]||at>=today[1];}

    /** The next instant at which {@link #dark(long)} changes. */
    static long nextChange(long at){long[] today=sunTimes(at,LATITUDE,LONGITUDE);if(today==null)return at+3600000;if(at<today[0])return today[0];if(at<today[1])return today[1];long[] tomorrow=sunTimes(at+(long)DAY,LATITUDE,LONGITUDE);return tomorrow==null?at+3600000:tomorrow[0];}

    private static boolean polarNight(long at){double d=at/DAY-0.5+J1970-J2000,m=RAD*(357.5291+0.98560028*d),l=m+RAD*(1.9148*Math.sin(m))+RAD*102.9372+Math.PI,dec=Math.asin(Math.sin(l)*Math.sin(RAD*23.4397));return LATITUDE*dec<0;}
}
