package com.personalassistant.companion;

import android.content.Context;
import org.json.JSONObject;
import java.util.Locale;

/** Records are always metric. These turn them into the owner's units for display and back on entry. */
final class WorkoutUnits {
    private WorkoutUnits(){}
    static final double LB=0.45359237,MILE=1609.344;
    static boolean imperial(Context c){JSONObject p=WorkoutStore.data(c,"athlete","self");return p!=null&&"imperial".equals(p.optString("units"));}
    private static String round(double v){return v==Math.rint(v)?String.valueOf((long)v):String.format(Locale.ROOT,"%.1f",v);}
    static String loadLabel(Context c){return imperial(c)?"lb":"kg";}
    static String distanceLabel(Context c){return imperial(c)?"mi":"km";}
    static String loadNumber(Context c,double kg){return round(Math.round((imperial(c)?kg/LB:kg)*10)/10.0);}
    static String load(Context c,double kg){return loadNumber(c,kg)+" "+loadLabel(c);}
    static double loadIn(Context c,double shown){return imperial(c)?shown*LB:shown;}
    static String distanceNumber(Context c,double metres){double v=imperial(c)?metres/MILE:metres/1000;return String.format(Locale.ROOT,"%.2f",v).replaceAll("\\.?0+$","");}
    static String distance(Context c,double metres){return distanceNumber(c,metres)+" "+distanceLabel(c);}
    static double distanceIn(Context c,double shown){return imperial(c)?shown*MILE:shown*1000;}
    static String speed(Context c,double kmh){return round(Math.round((imperial(c)?kmh*1000/MILE:kmh)*10)/10.0)+(imperial(c)?" mph":" km/h");}
    /** Minutes and seconds per kilometre or mile. */
    static String pace(Context c,double secondsPerKm){return WorkoutViews.clock(Math.round(imperial(c)?secondsPerKm*MILE/1000:secondsPerKm))+"/"+distanceLabel(c);}
}
