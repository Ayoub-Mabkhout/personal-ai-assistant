package com.personalassistant.companion;

import org.json.*;
import java.time.*;
import java.util.*;

/** A historical editor draft, independent of the active session. Untouched source fields survive a correction. */
final class WorkoutEdit {
    private WorkoutEdit(){}
    static JSONObject copy(JSONObject value)throws JSONException{return new JSONObject(value.toString());}
    static JSONObject draft(String id,JSONObject original)throws JSONException{
        String zone=original.optString("timezone","UTC"),start=original.optString("started_at");long when;
        try{when=OffsetDateTime.parse(start).toInstant().toEpochMilli();}catch(Exception e){when=LocalDateTime.parse(start).atZone(ZoneId.of(zone)).toInstant().toEpochMilli();}
        JSONObject d=new JSONObject().put("workout_id",id).put("edit_original",copy(original)).put("name",original.optString("name"))
            .put("started_ms",when).put("timezone",zone).put("paused_ms",when+original.optLong("duration_seconds")*1000).put("paused_total",0)
            .put("template_id",original.opt("template_id")).put("sprint_id",original.opt("sprint_id")).put("notes",original.optString("notes"))
            .put("changes",original.optJSONArray("session_changes")==null?new JSONArray():new JSONArray(original.getJSONArray("session_changes").toString()));
        JSONObject source=original.optJSONObject("source"),companion=source==null?null:source.optJSONObject("companion"),extras=companion==null?null:companion.optJSONObject("exercises");
        d.put("scheduled_date",companion==null?"":companion.optString("scheduled_date"));
        LinkedHashMap<String,JSONObject> groups=new LinkedHashMap<>();JSONArray sets=original.optJSONArray("sets");
        for(int i=0;sets!=null&&i<sets.length();i++){
            JSONObject s=sets.getJSONObject(i);String eid=s.optString("exercise_id");JSONObject ex=groups.get(eid);
            if(ex==null){JSONObject saved=extras==null?null:extras.optJSONObject(eid);ex=new JSONObject().put("eid",eid).put("rest",saved==null?120:saved.optInt("rest",120))
                .put("note",saved==null?"":saved.optString("note")).put("group",saved==null?"":saved.optString("group"))
                .put("started_ms",0).put("ended_ms",0).put("planned",0).put("sets",new JSONArray());groups.put(eid,ex);}
            JSONObject row=new JSONObject().put("id",s.optString("id")).put("kind",s.optString("kind","working")).put("done",s.optBoolean("completed",true));
            for(String[] f:FIELDS)if(s.has(f[1])&&!s.isNull(f[1]))row.put(f[0],s.get(f[1]));
            ex.getJSONArray("sets").put(row);
        }
        JSONArray exercises=new JSONArray(),order=new JSONArray();for(JSONObject ex:groups.values()){exercises.put(ex);JSONArray rows=ex.getJSONArray("sets");for(int i=0;i<rows.length();i++)order.put(rows.getJSONObject(i).getString("id"));}
        return d.put("exercises",exercises).put("edit_order",order);
    }
    private static final String[][] FIELDS={{"weight","weight_kg"},{"reps","reps"},{"rir","rir"},{"distance","distance_m"},{"seconds","seconds"}};
    static JSONObject saved(JSONObject draft)throws JSONException{
        JSONObject original=draft.getJSONObject("edit_original"),out=copy(original);Map<String,JSONObject> old=new HashMap<>(),changed=new LinkedHashMap<>();
        Set<String> originallyShown=new HashSet<>();JSONArray originals=original.optJSONArray("sets");for(int i=0;originals!=null&&i<originals.length();i++){JSONObject s=originals.getJSONObject(i);old.put(s.getString("id"),s);originallyShown.add(s.getString("exercise_id"));}
        JSONArray flat=new JSONArray(),order=new JSONArray(),exercises=draft.getJSONArray("exercises");Set<String> kept=new HashSet<>();JSONObject extras=new JSONObject();
        JSONObject source=out.optJSONObject("source");if(source==null)source=new JSONObject();JSONObject companion=source.optJSONObject("companion");if(companion==null)companion=new JSONObject();JSONObject priorExtras=companion.optJSONObject("exercises");
        if(priorExtras!=null)extras=copy(priorExtras);
        for(int i=0;i<exercises.length();i++){
            JSONObject ex=exercises.getJSONObject(i);String eid=ex.getString("eid");kept.add(eid);JSONArray rows=ex.getJSONArray("sets");
            for(int k=0;k<rows.length();k++){
                JSONObject row=rows.getJSONObject(k);String id=row.getString("id");JSONObject s=old.containsKey(id)?copy(old.get(id)):new JSONObject();
                s.put("id",id).put("exercise_id",eid).put("kind",row.optString("kind","working")).put("completed",row.optBoolean("done"));
                for(String[] f:FIELDS){if(row.has(f[0])&&!row.isNull(f[0]))s.put(f[1],row.get(f[0]));else if(!s.isNull(f[1]))s.remove(f[1]);}
                flat.put(s);order.put(id);changed.put(id,s);
            }
            JSONObject extra=priorExtras!=null&&priorExtras.optJSONObject(eid)!=null?copy(priorExtras.getJSONObject(eid)):new JSONObject();
            extras.put(eid,extra.put("note",ex.optString("note")).put("rest",ex.optInt("rest",120)).put("group",ex.optString("group")));
        }
        // Preserve an imported superset's interleaved row order when only its values changed.
        if(same(order,draft.optJSONArray("edit_order"))){flat=new JSONArray();for(int i=0;originals!=null&&i<originals.length();i++)flat.put(changed.get(originals.getJSONObject(i).getString("id")));}
        for(String eid:originallyShown)if(!kept.contains(eid))extras.remove(eid);
        companion.put("exercises",extras);source.put("companion",companion);out.put("source",source);
        JSONArray blocks=original.optJSONArray("blocks"),retained=new JSONArray();for(int i=0;blocks!=null&&i<blocks.length();i++){JSONObject b=blocks.getJSONObject(i);if(b.isNull("exercise_id")||!b.has("exercise_id")||kept.contains(b.optString("exercise_id"))||!originallyShown.contains(b.optString("exercise_id")))retained.put(b);}
        return out.put("name",draft.optString("name")).put("notes",draft.optString("notes")).put("sets",flat).put("blocks",retained).put("session_changes",draft.optJSONArray("changes"));
    }
    static boolean same(Object a,Object b){
        if(a==b)return true;if(a==null||b==null)return false;
        if(a instanceof JSONObject&&b instanceof JSONObject){JSONObject x=(JSONObject)a,y=(JSONObject)b;if(x.length()!=y.length())return false;Iterator<String> keys=x.keys();while(keys.hasNext()){String k=keys.next();if(!y.has(k)||!same(x.opt(k),y.opt(k)))return false;}return true;}
        if(a instanceof JSONArray&&b instanceof JSONArray){JSONArray x=(JSONArray)a,y=(JSONArray)b;if(x.length()!=y.length())return false;for(int i=0;i<x.length();i++)if(!same(x.opt(i),y.opt(i)))return false;return true;}
        if(a instanceof Number&&b instanceof Number)return Double.compare(((Number)a).doubleValue(),((Number)b).doubleValue())==0;
        return a.equals(b);
    }
}
