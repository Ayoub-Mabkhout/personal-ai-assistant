package com.personalassistant.companion;

import android.content.Context;
import android.content.SharedPreferences;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Locale;
import org.json.JSONObject;

/**
 * Weather for the Meridian sky (on by default, can be turned off in Meridian options). While the app is open, at most
 * hourly, the current conditions for the Daylight place (rounded to about 10 km) are read from the free, keyless Open-Meteo
 * forecast API, and the place name from the phone's own geocoder. Any failure keeps a fair-weather sky: a reading older
 * than three hours is not shown. Without a real place (only a time-zone estimate), no weather is requested.
 */
final class DaylightWeather {
    static final long INTERVAL=3600000L,STALE=3*3600000L;
    private static volatile boolean running;
    private DaylightWeather(){}

    static boolean enabled(Context c){return Cloud.prefs(c).getBoolean("daylight_weather",true);}

    static double level(Context c,long at){
        SharedPreferences p=Cloud.prefs(c);if(!enabled(c))return 0;long when=p.getLong("daylight_weather_at",0);
        if(when<=0||at<when||at-when>STALE)return 0;return Math.max(0,Math.min(1,p.getFloat("daylight_weather_level",0)));
    }

    static synchronized void refresh(Context c,long now){
        SharedPreferences p=Cloud.prefs(c);long last=p.getLong("daylight_weather_checked",0);
        if(running||!enabled(c)||(last>0&&now>=last&&now-last<(p.contains("daylight_weather_temp_c")?INTERVAL:300000L))||!VoiceOutbox.networkReady(c))return;
        final Context app=c.getApplicationContext();final double[] place=AppUi.daylightPlace(app);if(place==null)return;
        running=true;p.edit().putLong("daylight_weather_checked",now).apply();
        new Thread(()->{
            HttpURLConnection connection=null;boolean received=false;
            try{
                connection=(HttpURLConnection)new URL(String.format(Locale.ROOT,"https://api.open-meteo.com/v1/forecast?latitude=%.1f&longitude=%.1f&current=weather_code,cloud_cover,temperature_2m&temperature_unit=celsius",place[0],place[1])).openConnection();
                connection.setConnectTimeout(8000);connection.setReadTimeout(8000);connection.setUseCaches(false);
                if(connection.getResponseCode()!=200)return;
                ByteArrayOutputStream body=new ByteArrayOutputStream();
                try(InputStream in=connection.getInputStream()){byte[] buffer=new byte[4096];int n;while((n=in.read(buffer))>0){if(body.size()+n>65536)throw new java.io.IOException("Weather response too large");body.write(buffer,0,n);}}
                JSONObject current=new JSONObject(body.toString("UTF-8")).getJSONObject("current");
                double level=DaylightPalette.weatherLevel(current.optInt("weather_code",-1),current.optDouble("cloud_cover",Double.NaN));
                Cloud.prefs(app).edit().putFloat("daylight_weather_level",(float)level).putInt("daylight_weather_code",current.optInt("weather_code",-1))
                    .putFloat("daylight_weather_cover",(float)current.optDouble("cloud_cover",Double.NaN)).putFloat("daylight_weather_temp_c",(float)current.optDouble("temperature_2m",Double.NaN))
                    .putLong("daylight_weather_at",System.currentTimeMillis()).apply();received=true;
                locality(app,place);
            }catch(Exception ignored){
                // Offline or unexpected answer: the time-only palette stays.
            }finally{if(!received)Cloud.prefs(app).edit().remove("daylight_weather_at").apply();if(connection!=null)connection.disconnect();running=false;}
        },"daylight-weather").start();
    }
    /** The town for the weather pill, looked up again only when the place moves. Some phones have no geocoder; then it stays blank. */
    @SuppressWarnings("deprecation")
    private static void locality(Context c,double[] place){
        String key=String.format(Locale.ROOT,"%.2f,%.2f",place[0],place[1]);SharedPreferences p=Cloud.prefs(c);if(key.equals(p.getString("daylight_locality_for","")))return;
        try{if(!android.location.Geocoder.isPresent())return;java.util.List<android.location.Address> found=new android.location.Geocoder(c,Locale.getDefault()).getFromLocation(place[0],place[1],1);
            if(found==null||found.isEmpty())return;android.location.Address a=found.get(0);String name=a.getLocality()!=null?a.getLocality():a.getSubAdminArea()!=null?a.getSubAdminArea():a.getAdminArea();
            p.edit().putString("daylight_locality",name==null?"":name).putString("daylight_locality_for",key).apply();
        }catch(Exception ignored){}
    }
}
