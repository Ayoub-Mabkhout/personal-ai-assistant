package com.personalassistant.companion;

import android.content.Context;
import android.content.SharedPreferences;
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
    /** A session or month total: whole units with thousands separators. */
    static String total(Context c,double kg){return String.format(Locale.getDefault(),"%,d",Math.round(imperial(c)?kg/LB:kg))+" "+loadLabel(c);}
    static double loadValue(Context c,double kg){return imperial(c)?kg/LB:kg;}
    static double speedValue(Context c,double kmh){return imperial(c)?kmh*1000/MILE:kmh;}
    static String speedLabel(Context c){return imperial(c)?"mph":"km/h";}
    static double loadIn(Context c,double shown){return imperial(c)?shown*LB:shown;}
    static String distanceNumber(Context c,double metres){double v=imperial(c)?metres/MILE:metres/1000;return String.format(Locale.ROOT,"%.2f",v).replaceAll("\\.?0+$","");}
    static String distance(Context c,double metres){return distanceNumber(c,metres)+" "+distanceLabel(c);}
    static double distanceIn(Context c,double shown){return imperial(c)?shown*MILE:shown*1000;}
    static String speed(Context c,double kmh){return round(Math.round((imperial(c)?kmh*1000/MILE:kmh)*10)/10.0)+(imperial(c)?" mph":" km/h");}
    static String speedNumber(Context c,double kmh){return round(Math.round((imperial(c)?kmh*1000/MILE:kmh)*10)/10.0);}
    static double speedIn(Context c,double shown){return imperial(c)?shown*MILE/1000:shown;}
    /** Some kit is marked in the other system, so one exercise can be logged that way while everything else stays in the owner's units. */
    private static SharedPreferences swapped(Context c){return c.getSharedPreferences("train_units",0);}
    static void flip(Context c,String exercise){SharedPreferences p=swapped(c);p.edit().putBoolean(exercise,!p.getBoolean(exercise,false)).apply();}
    private static boolean imperial(Context c,String exercise){return imperial(c)!=swapped(c).getBoolean(exercise,false);}
    static String loadLabel(Context c,String exercise){return imperial(c,exercise)?"lb":"kg";}
    static String distanceLabel(Context c,String exercise){return imperial(c,exercise)?"mi":"km";}
    static String loadNumber(Context c,String exercise,double kg){return round(Math.round((imperial(c,exercise)?kg/LB:kg)*10)/10.0);}
    static double loadIn(Context c,String exercise,double shown){return imperial(c,exercise)?shown*LB:shown;}
    static String distanceNumber(Context c,String exercise,double metres){double v=imperial(c,exercise)?metres/MILE:metres/1000;return String.format(Locale.ROOT,"%.2f",v).replaceAll("\\.?0+$","");}
    static double distanceIn(Context c,String exercise,double shown){return imperial(c,exercise)?shown*MILE:shown*1000;}
    /** Minutes and seconds per kilometre or mile. */
    static String pace(Context c,double secondsPerKm){return WorkoutViews.clock(Math.round(imperial(c)?secondsPerKm*MILE/1000:secondsPerKm))+"/"+distanceLabel(c);}
}
