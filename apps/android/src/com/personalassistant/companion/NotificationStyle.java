package com.personalassistant.companion;
import android.app.*;
import android.content.Context;
import android.graphics.*;
import android.graphics.drawable.Icon;
import java.util.HashMap;
import java.util.Map;

/** Shared notification presentation: one channel group and aurora-glass medallions that echo the launcher orb. */
final class NotificationStyle {
    static final String GROUP="assistant";
    /** Medallion gradients, light stop first: brand, in progress, done, needs you, failed. */
    static final int[] BRAND={0xFFA98BFF,0xFF4F2BC4},PROGRESS={0xFF9DB0FF,0xFF5B35D5},DONE={0xFFC98BF5,0xFF6A3FE0},ATTENTION={0xFFF4A3D0,0xFFA23BC6},FAILED={0xFFFF9BB0,0xFFB3263E};
    private static final Map<String,Icon> icons=new HashMap<>();

    /** Creates or updates a channel inside the Assistant group. Android keeps the user's importance for existing channels. */
    static void channel(NotificationManager manager,String id,String name,int importance,String description){
        manager.createNotificationChannelGroup(new NotificationChannelGroup(GROUP,"Assistant"));
        NotificationChannel channel=new NotificationChannel(id,name,importance);channel.setDescription(description);channel.setGroup(GROUP);
        manager.createNotificationChannel(channel);
    }

    /** Large icon: a glass medallion in the given tone carrying a white glyph. Cached because voice status refreshes often. */
    static synchronized Icon icon(Context c,String glyph,int[] tone){
        String key=glyph+":"+tone[0]+":"+tone[1];Icon cached=icons.get(key);if(cached!=null)return cached;
        float density=c.getResources().getDisplayMetrics().density;int size=Math.round(48*density);float r=size/2f;
        Bitmap bitmap=Bitmap.createBitmap(size,size,Bitmap.Config.ARGB_8888);Canvas canvas=new Canvas(bitmap);Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);
        p.setShader(new LinearGradient(size*.18f,size*.1f,size*.85f,size*.95f,tone[0],tone[1],Shader.TileMode.CLAMP));canvas.drawCircle(r,r,r,p);
        // Soft window highlight and a faint rim, as on the launcher orb's glass.
        p.setShader(new RadialGradient(size*.34f,size*.27f,size*.52f,new int[]{0x80FFFFFF,0x1FFFFFFF,0x00FFFFFF},new float[]{0f,.45f,1f},Shader.TileMode.CLAMP));canvas.drawCircle(r,r,r,p);
        p.setShader(null);p.setStyle(Paint.Style.STROKE);float rim=Math.max(1f,size*.03f);p.setStrokeWidth(rim);p.setColor(0x47FFFFFF);canvas.drawCircle(r,r,r-rim/2f,p);
        float g=size*.5f;canvas.save();canvas.translate((size-g)/2f,(size-g)/2f);canvas.scale(g/24f,g/24f);p.setColor(Color.WHITE);AppUi.Glyphs.draw(canvas,glyph,p,AppUi.Glyphs.units(g,density));canvas.restore();
        cached=Icon.createWithBitmap(bitmap);icons.put(key,cached);return cached;
    }
}
