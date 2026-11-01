package com.personalassistant.companion;

import android.content.Context;
import android.graphics.*;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.util.Locale;

/**
 * Exercise illustrations: one geometric figure per movement, drawn on a 48-unit grid in the accent colour, with a small equipment
 * badge. Canvas only, so dozens of exercises share a handful of poses and add nothing to the APK.
 */
final class WorkoutArt {
    private WorkoutArt(){}
    /** Backend fields when present, otherwise read from the name so imported exercises are illustrated too. */
    static String movement(JSONObject e){String v=e==null?"":e.optString("movement");if(!v.isEmpty()&&!"other".equals(v))return v;String n=e==null?"":e.optString("name").toLowerCase(Locale.ROOT);String[][] words={{"run","run","treadmill","jog"},{"walk","walk","hike"},{"curl","curl"},{"extension","pushdown","skullcrusher","extension","triceps","dip"},{"raise","raise","fly"},{"squat","squat","leg press","hack"},{"lunge","lunge","split","step"},{"hinge","deadlift","romanian","hip thrust","good morning"},{"pull","pull-up","pull up","chin","pulldown"},{"row","row"},{"press","press","bench","push"},{"core","plank","crunch","sit-up","ab "}};for(String[] w:words)for(int i=1;i<w.length;i++)if(n.contains(w[i]))return w[0];return "other";}
    static String equipment(JSONObject e){String v=e==null?"":e.optString("equipment").toLowerCase(Locale.ROOT);String n=e==null?"":e.optString("name").toLowerCase(Locale.ROOT);String t=v+" "+n;if(t.contains("barbell")||t.contains("ez bar"))return "barbell";if(t.contains("dumbbell"))return "dumbbell";if(t.contains("cable"))return "cable";if(t.contains("machine")||t.contains("smith")||t.contains("treadmill")||t.contains("leg press"))return "machine";if(t.contains("bodyweight")||t.contains("pull-up")||t.contains("pull up")||t.contains("push-up"))return "person";return "";}
    /** The heading an exercise is grouped under. */
    static String group(JSONObject e){switch(movement(e)){case "press":case "raise":case "extension":return "Push";case "row":case "pull":case "curl":return "Pull";case "squat":case "lunge":case "hinge":return "Legs and hips";case "run":case "walk":return "Cardio";case "core":return "Core";default:return "Other";}}
    static View tile(AppUi ui,String exerciseId,int sizeDp){return new Tile(ui,WorkoutStore.data(ui.context,"exercise",exerciseId));}
    /** Line figure from joints: head, then limbs as polylines. Coordinates are x,y pairs on the 48-unit grid. */
    private static final Object[][] POSES={
        {"press",new float[]{24,14},new float[][]{{10,34,38,34},{24,18,24,34},{24,22,14,26,14,12},{24,22,34,26,34,12},{8,10,40,10}}},
        {"squat",new float[]{24,10},new float[][]{{24,14,22,26},{22,26,32,30,28,42},{22,26,14,32,18,42},{10,17,38,17},{24,17,24,17}}},
        {"hinge",new float[]{34,14},new float[][]{{30,18,16,24},{16,24,20,34,20,44},{28,20,28,34},{16,36,40,36}}},
        {"row",new float[]{32,12},new float[][]{{28,16,16,26},{16,26,20,36,18,44},{26,20,32,28,24,31},{14,33,34,33}}},
        {"pull",new float[]{24,16},new float[][]{{8,6,40,6},{24,20,24,32},{24,22,14,16,14,6},{24,22,34,16,34,6},{24,32,20,44},{24,32,28,44}}},
        {"curl",new float[]{24,8},new float[][]{{24,12,24,28},{24,16,18,24,12,16},{24,16,30,24,36,16},{24,28,20,44},{24,28,28,44},{8,15,16,15},{32,15,40,15}}},
        {"extension",new float[]{24,8},new float[][]{{24,12,24,28},{24,15,18,23,20,31},{24,15,30,23,28,31},{24,28,20,44},{24,28,28,44},{24,4,20,31},{24,4,28,31}}},
        {"raise",new float[]{24,8},new float[][]{{24,12,24,28},{24,16,8,16},{24,16,40,16},{24,28,20,44},{24,28,28,44},{6,12,6,20},{42,12,42,20}}},
        {"lunge",new float[]{24,8},new float[][]{{24,12,24,26},{24,26,34,30,34,42},{24,26,16,34,6,42},{24,16,20,26},{24,16,28,26}}},
        {"core",new float[]{36,24},new float[][]{{32,26,14,32},{14,32,6,40},{30,28,28,38,24,40}}},
        {"run",new float[]{30,9},new float[][]{{28,13,22,26},{22,26,32,31,28,42},{22,26,14,33,6,31},{27,16,36,20,38,14},{27,16,18,19,14,26}}},
        {"walk",new float[]{26,9},new float[][]{{26,13,24,27},{24,27,30,36,30,44},{24,27,18,36,14,44},{25,17,32,25},{25,17,18,25}}},
        {"other",new float[]{24,9},new float[][]{{24,13,24,28},{24,17,14,24},{24,17,34,24},{24,28,18,44},{24,28,30,44}}}};
    static final class Tile extends View {
        final AppUi ui;final String pose,gear;final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);
        Tile(AppUi ui,JSONObject exercise){super(ui.context);this.ui=ui;pose=movement(exercise);gear=equipment(exercise);setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);}
        @Override protected void onDraw(Canvas c){float size=Math.min(getWidth(),getHeight()),s=size/48f;p.setStyle(Paint.Style.FILL);p.setColor(ui.accentSoft);c.drawRoundRect(0,0,size,size,size*.26f,size*.26f,p);c.save();c.scale(s,s);Object[] pick=POSES[POSES.length-1];for(Object[] row:POSES)if(row[0].equals(pose))pick=row;p.setColor(ui.accent);float[] head=(float[])pick[1];c.drawCircle(head[0],head[1],3.8f,p);p.setStyle(Paint.Style.STROKE);p.setStrokeCap(Paint.Cap.ROUND);p.setStrokeJoin(Paint.Join.ROUND);p.setStrokeWidth(2.6f);for(float[] l:(float[][])pick[2]){if(l.length<4)continue;Path a=new Path();a.moveTo(l[0],l[1]);for(int i=2;i<l.length;i+=2)a.lineTo(l[i],l[i+1]);c.drawPath(a,p);}c.restore();
            if(!gear.isEmpty()){float d=size*.42f,x=size-d,y=size-d;p.setStyle(Paint.Style.FILL);p.setColor(ui.surface);c.drawCircle(x+d/2,y+d/2,d/2+s,p);c.save();c.translate(x+d*.12f,y+d*.12f);float g=d*.76f;c.scale(g/24f,g/24f);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(2.2f);p.setColor(ui.muted);AppUi.Glyphs.draw(c,gear,p,AppUi.Glyphs.units(Math.round(g),ui.density));c.restore();}}
    }
}
