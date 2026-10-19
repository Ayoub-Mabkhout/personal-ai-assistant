package com.personalassistant.companion;

import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationManager;
import android.os.Build;

/**
 * Daylight place from the phone's cached coarse location. Only last-known fixes are read (passive, network, fused, then any
 * cached GPS fix); nothing asks for location updates, so no radio or GPS is switched on. Runs while the app is in the
 * foreground, at most every 30 minutes, and only when location is enabled and approximate location was granted from
 * Settings. Coordinates are rounded to about a kilometre; that is plenty for sunrise and sunset.
 */
final class DaylightLocation {
    static final String PERMISSION="android.permission.ACCESS_COARSE_LOCATION";
    static final long INTERVAL=30*60000L;
    private DaylightLocation(){}

    static boolean granted(Context c){return c.checkSelfPermission(PERMISSION)==PackageManager.PERMISSION_GRANTED||c.checkSelfPermission("android.permission.ACCESS_FINE_LOCATION")==PackageManager.PERMISSION_GRANTED;}

    static void refresh(Context c,long now){
        SharedPreferences p=Cloud.prefs(c);long last=p.getLong("daylight_device_checked",0);
        if(!p.getBoolean("daylight_use_location",true)||!granted(c)||(last>0&&now>=last&&now-last<INTERVAL))return;
        LocationManager manager=c.getSystemService(LocationManager.class);if(manager==null)return;
        try{if(Build.VERSION.SDK_INT>=28&&!manager.isLocationEnabled())return;}catch(RuntimeException unavailable){return;}
        p.edit().putLong("daylight_device_checked",now).apply();
        Location best=null;
        for(String provider:new String[]{LocationManager.PASSIVE_PROVIDER,LocationManager.NETWORK_PROVIDER,"fused",LocationManager.GPS_PROVIDER}){
            try{Location fix=manager.getLastKnownLocation(provider);if(fix!=null&&(best==null||fix.getTime()>best.getTime()))best=fix;}catch(RuntimeException ignored){}
        }
        if(best==null||!DaylightTheme.valid(best.getLatitude(),best.getLongitude()))return;
        String latitude=Double.toString(Math.round(best.getLatitude()*100)/100d),longitude=Double.toString(Math.round(best.getLongitude()*100)/100d);
        if(latitude.equals(p.getString("daylight_device_latitude",""))&&longitude.equals(p.getString("daylight_device_longitude","")))return;
        p.edit().putString("daylight_device_latitude",latitude).putString("daylight_device_longitude",longitude).apply();
    }
}
