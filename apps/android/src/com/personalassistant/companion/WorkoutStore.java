package com.personalassistant.companion;

import android.content.Context;
import android.util.AtomicFile;
import org.json.*;
import java.io.*;
import java.time.*;
import java.util.*;

/**
 * Offline workout records. The relay owns accepted revisions; this keeps a cache of every entity, an ordered outbox written
 * before any network call, and the live session draft in its own small file so a ticked set survives process death.
 * A rejected edit stays in the outbox, flagged, until the owner keeps or discards it.
 */
final class WorkoutStore {
    private WorkoutStore(){}
    private static JSONObject cache;private static JSONArray outbox;private static final Object syncing=new Object();

    private static File file(Context c,String name){File dir=new File(c.getFilesDir(),"workout");dir.mkdirs();return new File(dir,name);}
    private static JSONObject read(Context c,String name,String fallback){try{return new JSONObject(new String(new AtomicFile(file(c,name)).readFully(),"UTF-8"));}catch(Exception e){try{return new JSONObject(fallback);}catch(JSONException x){throw new IllegalStateException(x);}}}
    private static void write(Context c,String name,JSONObject value){AtomicFile f=new AtomicFile(file(c,name));FileOutputStream out=null;try{out=f.startWrite();out.write(value.toString().getBytes("UTF-8"));f.finishWrite(out);}catch(IOException e){if(out!=null)f.failWrite(out);throw new IllegalStateException("Couldn't save workout data on this phone",e);}}
    private static synchronized JSONObject cache(Context c){if(cache==null)cache=read(c,"cache.json","{\"cursor\":0,\"entities\":{},\"overview\":{}}");return cache;}
    private static synchronized JSONArray outbox(Context c){if(outbox==null)outbox=read(c,"outbox.json","{\"items\":[]}").optJSONArray("items");return outbox;}
    private static void saveOutbox(Context c){try{write(c,"outbox.json",new JSONObject().put("items",outbox));}catch(JSONException e){throw new IllegalStateException(e);}}
    private static void saveCache(Context c){write(c,"cache.json",cache);}
    static String id(){return "c"+UUID.randomUUID().toString().replace("-","");}

    /** Live rows of one kind as {id,revision,data}. */
    static synchronized List<JSONObject> rows(Context c,String kind){ArrayList<JSONObject> out=new ArrayList<>();JSONObject all=cache(c).optJSONObject("entities"),group=all==null?null:all.optJSONObject(kind);if(group==null)return out;for(Iterator<String> i=group.keys();i.hasNext();){String id=i.next();JSONObject row=group.optJSONObject(id);if(row!=null&&!row.optBoolean("deleted")){try{out.add(new JSONObject().put("id",id).put("revision",row.optInt("revision")).put("data",row.optJSONObject("data")));}catch(JSONException ignored){}}}return out;}
    static synchronized JSONObject data(Context c,String kind,String id){JSONObject all=cache(c).optJSONObject("entities"),group=all==null?null:all.optJSONObject(kind),row=group==null?null:group.optJSONObject(id);return row==null||row.optBoolean("deleted")?null:row.optJSONObject("data");}
    static synchronized JSONObject overview(Context c){JSONObject o=cache(c).optJSONObject("overview");return o==null?new JSONObject():o;}
    private static void apply(Context c,String kind,String id,int revision,boolean deleted,JSONObject data)throws JSONException{JSONObject all=cache(c).getJSONObject("entities"),group=all.optJSONObject(kind);if(group==null)all.put(kind,group=new JSONObject());group.put(id,new JSONObject().put("revision",revision).put("deleted",deleted).put("data",data==null?new JSONObject():data));}

    /** Saves an edit locally and queues it; the same mutation ID is reused for every retry. */
    static synchronized void put(Context c,String kind,String id,JSONObject data){queue(c,kind,id,data,false,null);}
    static synchronized void finishWithProof(Context c,String id,JSONObject data,byte[] photo,boolean share){
        try{queue(c,"workout",id,data,false,proof(photo,share));}
        catch(JSONException e){throw new IllegalStateException(e);}
    }

    private static JSONObject proof(byte[] photo,boolean share)throws JSONException{
        if(photo==null||photo.length==0||photo.length>WorkoutProofCamera.MAX_JPEG)throw new IllegalStateException("Invalid workout photo");
        return new JSONObject().put("photo_base64",android.util.Base64.encodeToString(photo,android.util.Base64.NO_WRAP))
                .put("share",share);
    }

    /** Upgrade a rejected pre-camera outbox entry without losing any of its workout data. */
    static synchronized void addMissingProof(Context c,String mutation,byte[] photo,boolean share)throws JSONException{
        JSONArray queued=outbox(c);
        for(int i=0;i<queued.length();i++){
            JSONObject row=queued.optJSONObject(i);
            if(!mutation.equals(row.optString("mutation_id"))||!row.optBoolean("needs_photo"))continue;
            JSONObject replacement=new JSONObject(row.toString());
            replacement.put("mutation_id",id()).put("workout_proof",proof(photo,share));
            replacement.remove("sent");
            replacement.remove("conflict");
            replacement.remove("needs_photo");
            queued.put(i,replacement);
            try{saveOutbox(c);}catch(IllegalStateException error){queued.put(i,row);throw error;}
            return;
        }
        throw new IllegalStateException("Workout is no longer waiting for a photo");
    }
    static synchronized void delete(Context c,String kind,String id){queue(c,kind,id,data(c,kind,id),true,null);}
    private static void queue(Context c,String kind,String id,JSONObject data,boolean deleted,JSONObject proof){try{JSONObject group=cache(c).getJSONObject("entities").optJSONObject(kind),row=group==null?null:group.optJSONObject(id);int revision=row==null?0:row.optInt("revision");
        JSONObject operation=new JSONObject().put("mutation_id",id()).put("kind",kind).put("id",id)
                .put("base_revision",revision).put("deleted",deleted)
                .put("data",data==null?new JSONObject():new JSONObject(data.toString()));
        if(proof!=null)operation.put("workout_proof",proof);
        JSONArray queued=outbox(c);queued.put(operation);
        try{saveOutbox(c);}catch(IllegalStateException e){queued.remove(queued.length()-1);throw e;}
        apply(c,kind,id,revision,deleted,data);saveCache(c);}catch(JSONException e){throw new IllegalStateException(e);}}
    static synchronized int waiting(Context c){return outbox(c).length();}
    static synchronized List<JSONObject> conflicts(Context c){ArrayList<JSONObject> out=new ArrayList<>();JSONArray q=outbox(c);for(int i=0;i<q.length();i++)if(q.optJSONObject(i).optBoolean("conflict"))out.add(q.optJSONObject(i));return out;}
    /** The owner's choice on a rejected edit: keep it on top of the latest cloud revision, or drop it and take the cloud's. */
    static void resolve(Context c,String mutation,boolean keep)throws Exception{JSONObject op=null;synchronized(WorkoutStore.class){JSONArray q=outbox(c);for(int i=0;i<q.length();i++)if(mutation.equals(q.optJSONObject(i).optString("mutation_id")))op=q.optJSONObject(i);}if(op==null)return;
        JSONObject latest=(JSONObject)Cloud.call(c,"workout/entities/"+op.optString("kind")+"/"+op.optString("id"),null,true);
        synchronized(WorkoutStore.class){JSONArray q=outbox(c);for(int i=0;i<q.length();i++){JSONObject row=q.optJSONObject(i);if(!mutation.equals(row.optString("mutation_id")))continue;if(keep){row.remove("conflict");row.remove("sent");row.put("mutation_id",id()).put("base_revision",latest.optInt("revision"));}else{q.remove(i);apply(c,op.optString("kind"),op.optString("id"),latest.optInt("revision"),latest.optBoolean("deleted"),latest.optJSONObject("data"));saveCache(c);}break;}saveOutbox(c);}}

    /** Pushes the outbox in order, then pulls changes and the overview. Returns an owner-readable problem or "". */
    static String sync(Context c){synchronized(syncing){try{
            while(true){JSONObject op=null;synchronized(WorkoutStore.class){JSONArray q=outbox(c);for(int i=0;i<q.length();i++){JSONObject row=q.optJSONObject(i);if(!row.optBoolean("conflict")){op=row;break;}}if(op==null)break;op.put("sent",true);saveOutbox(c);}
                JSONObject wire=new JSONObject(op.toString());wire.remove("sent");wire.remove("conflict");wire.remove("needs_photo");
                JSONObject proof=wire.optJSONObject("workout_proof");wire.remove("workout_proof");
                try{JSONObject result=proof==null
                            ?(JSONObject)Cloud.call(c,"workout/sync",new JSONObject().put("operations",new JSONArray().put(wire)),true)
                            :(JSONObject)Cloud.call(c,"workout/workout-finish",new JSONObject(proof.toString()).put("operation",wire),true);JSONObject r=result.getJSONArray("results").getJSONObject(0);
                    synchronized(WorkoutStore.class){JSONArray q=outbox(c);for(int i=0;i<q.length();i++)if(op.optString("mutation_id").equals(q.optJSONObject(i).optString("mutation_id"))){q.remove(i);break;}for(int i=0;i<q.length();i++){JSONObject later=q.optJSONObject(i);if(later.optString("kind").equals(op.optString("kind"))&&later.optString("id").equals(op.optString("id")))later.put("base_revision",r.optInt("revision"));}saveOutbox(c);if(!pending(c,op.optString("kind"),op.optString("id"))){apply(c,r.optString("kind"),r.optString("id"),r.optInt("revision"),r.optBoolean("deleted"),r.optJSONObject("data"));saveCache(c);}}
                }catch(Cloud.HttpError e){if(e.status==409||e.status==422||e.status==428){synchronized(WorkoutStore.class){
                    op.put("conflict",true);
                    if(e.status==428)op.put("needs_photo",true);
                    saveOutbox(c);
                }}else throw e;}}
            int cursor=cache(c).optInt("cursor");while(true){JSONObject page=(JSONObject)Cloud.call(c,"workout/changes?after="+cursor+"&limit=100",null,true);JSONArray items=page.optJSONArray("items");
                synchronized(WorkoutStore.class){for(int i=0;items!=null&&i<items.length();i++){JSONObject row=items.getJSONObject(i);if(!pending(c,row.optString("kind"),row.optString("id")))apply(c,row.optString("kind"),row.optString("id"),row.optInt("revision"),row.optBoolean("deleted"),row.optJSONObject("data"));}cursor=page.optInt("cursor",cursor);cache.put("cursor",cursor);saveCache(c);}if(!page.optBoolean("has_more"))break;}
            JSONObject summary=(JSONObject)Cloud.call(c,"workout/overview",null,true);synchronized(WorkoutStore.class){cache.put("overview",summary);saveCache(c);}return "";
        }catch(Cloud.HttpError e){return e.status==404?"Your server doesn't have Train yet.":"Your server refused the update ("+e.status+"). Your entries stay on this phone.";}catch(Exception e){return "Offline. Your entries stay on this phone.";}}}
    private static boolean pending(Context c,String kind,String id){JSONArray q=outbox(c);for(int i=0;i<q.length();i++){JSONObject row=q.optJSONObject(i);if(kind.equals(row.optString("kind"))&&id.equals(row.optString("id")))return true;}return false;}

    static JSONObject draft(Context c){JSONObject d=read(c,"draft.json","{}");return d.length()==0?null:d;}
    static void saveDraft(Context c,JSONObject d){write(c,"draft.json",d);}
    static void clearDraft(Context c){file(c,"draft.json").delete();}

    static String exerciseName(Context c,String id){JSONObject e=data(c,"exercise",id);return e==null?id:e.optString("name",id);}
    static boolean cardio(Context c,String id){JSONObject e=data(c,"exercise",id);return e!=null&&"cardio".equals(e.optString("mode"));}
    /** Workouts newest first. */
    static List<JSONObject> workouts(Context c){List<JSONObject> out=rows(c,"workout");Collections.sort(out,(a,b)->b.optJSONObject("data").optString("started_at").compareTo(a.optJSONObject("data").optString("started_at")));return out;}
    /** The most recent completed sets of an exercise, for the Previous column. */
    static List<JSONObject> previous(Context c,String exercise){for(JSONObject w:workouts(c)){JSONObject d=w.optJSONObject("data");if(!"completed".equals(d.optString("status")))continue;ArrayList<JSONObject> found=new ArrayList<>();JSONArray sets=d.optJSONArray("sets");for(int i=0;sets!=null&&i<sets.length();i++){JSONObject s=sets.optJSONObject(i);if(exercise.equals(s.optString("exercise_id"))&&s.optBoolean("completed",true)&&!"note".equals(s.optString("kind")))found.add(s);}if(!found.isEmpty())return found;}return new ArrayList<>();}
    /** Epley estimate on 2–10 reps, matching the server; warm-ups and drop sets don't count. */
    static double e1rm(JSONObject s){String kind=s.optString("kind");if(!"working".equals(kind)&&!"failure".equals(kind))return 0;double w=s.optDouble("weight_kg",0);int r=s.optInt("reps",0);if(w<=0||r<1||r>10)return 0;return r==1?w:w*(1+r/30.0);}
    static LocalDate day(JSONObject workout){try{return OffsetDateTime.parse(workout.optString("started_at")).atZoneSameInstant(ZoneId.of(workout.optString("timezone","UTC"))).toLocalDate();}catch(Exception e){try{return LocalDateTime.parse(workout.optString("started_at")).toLocalDate();}catch(Exception x){return LocalDate.MIN;}}}

    /** The sprint running today, or the next planned one. */
    static JSONObject sprint(Context c){LocalDate today=LocalDate.now();JSONObject best=null;for(JSONObject row:rows(c,"sprint")){JSONObject d=row.optJSONObject("data");String status=d.optString("status");if("cancelled".equals(status)||"completed".equals(status))continue;if("active".equals(status))return row;if(LocalDate.parse(d.optString("end")).isBefore(today))continue;if(best==null||d.optString("start").compareTo(best.optJSONObject("data").optString("start"))<0)best=row;}return best;}
    /** Count cached accepted and queued owner edits; deleted rows are excluded by workouts(). */
    static int sprintCompleted(Context c,String sprintId){int count=0;for(JSONObject row:workouts(c)){JSONObject d=row.optJSONObject("data");if(sprintId.equals(d.optString("sprint_id"))&&"completed".equals(d.optString("status")))count++;}return count;}
    /** The first scheduled sprint session from today that hasn't been done or moved: {sprint,scheduled,template_id,date,index,total}. */
    static JSONObject next(Context c){JSONObject local=sprint(c);String finished="";if(local!=null){JSONObject d=local.optJSONObject("data");JSONArray cycle=d.optJSONArray("cycle");if(cycle!=null&&cycle.length()>0){int count=sprintCompleted(c,local.optString("id")),target=d.optInt("target_sessions",cycle.length());if(count>=target)finished=local.optString("id");else try{return new JSONObject().put("sprint",local).put("template_id",cycle.optString(count%cycle.length())).put("date",LocalDate.now().toString()).put("index",count+1).put("total",target);}catch(JSONException ignored){return null;}}}JSONObject planned=overview(c).optJSONObject("next_workout");if(planned!=null&&planned.has("template_id")&&!planned.isNull("template_id")&&!finished.equals(planned.optString("sprint_id"))){try{JSONObject out=new JSONObject().put("template_id",planned.optString("template_id")).put("date",planned.isNull("date")?LocalDate.now().toString():planned.optString("date")).put("index",planned.optInt("sequence_number",planned.optInt("position",1))).put("total",planned.optInt("target_sessions",0));String id=planned.optString("sprint_id");JSONObject d=id.isEmpty()?null:data(c,"sprint",id);if(d!=null)out.put("sprint",new JSONObject().put("id",id).put("data",d));return out;}catch(JSONException ignored){}}JSONObject sprint=sprint(c);if(sprint==null)return null;JSONObject d=sprint.optJSONObject("data");JSONArray plan=d.optJSONArray("scheduled");if(plan==null)return null;ArrayList<JSONObject> list=new ArrayList<>();for(int i=0;i<plan.length();i++)list.add(plan.optJSONObject(i));Collections.sort(list,(a,b)->a.optString("date").compareTo(b.optString("date")));
        HashSet<String> used=new HashSet<>();for(JSONObject w:workouts(c)){JSONObject x=w.optJSONObject("data");if(sprint.optString("id").equals(x.optString("sprint_id"))&&("completed".equals(x.optString("status"))||"skipped".equals(x.optString("status"))))used.add(scheduled(x));}
        LocalDate today=LocalDate.now();for(int i=0;i<list.size();i++){JSONObject s=list.get(i);if(used.contains(s.optString("date"))||LocalDate.parse(s.optString("date")).isBefore(today))continue;try{return new JSONObject().put("sprint",sprint).put("template_id",s.optString("template_id")).put("date",s.optString("date")).put("index",i+1).put("total",list.size());}catch(JSONException ignored){}}return null;}
    /** Which scheduled date a workout stands for, even when it was done on another day. */
    static String scheduled(JSONObject workout){JSONObject source=workout.optJSONObject("source"),mine=source==null?null:source.optJSONObject("companion");String date=mine==null?"":mine.optString("scheduled_date");return date.isEmpty()?day(workout).toString():date;}
}
