package com.personalassistant.companion;

import android.content.*;
import org.json.*;
import java.net.URLEncoder;
import java.util.*;
import java.util.concurrent.*;

/** Shared features checklist: the last server list, a durable outbox with stable client IDs and ordered retries. Network never holds the local lock. */
final class Features {
    static final String ACTION="com.personalassistant.companion.FEATURE_STATE";
    static final ExecutorService network=Executors.newSingleThreadExecutor();
    private static final Object sendLock=new Object();
    private static String sending;
    private Features(){}

    static void changed(Context c){c.sendBroadcast(new Intent(ACTION).setPackage(c.getPackageName()));}
    private static String origin(Context c){return Cloud.prefs(c).getString("origin","");}
    /** The cached list belongs to the server it came from; after pairing elsewhere it is not shown. */
    static JSONObject cached(Context c){
        SharedPreferences p=Cloud.prefs(c);if(!p.getString("features_origin","").equals(origin(c)))return new JSONObject();
        try{return new JSONObject(p.getString("features_snapshot","{\"items\":[]}"));}catch(Exception e){return new JSONObject();}
    }
    static String signature(Context c){SharedPreferences p=Cloud.prefs(c);return p.getString("features_origin","")+p.getString("features_snapshot","")+p.getString("features_outbox","");}

    private static double number(JSONObject o,String key){Object v=o.opt(key);return v instanceof Number?((Number)v).doubleValue():0;}
    static FeatureBoard.Item item(JSONObject o){
        FeatureBoard.Item i=new FeatureBoard.Item();i.id=o.optString("id");i.title=o.optString("title");i.detail=o.isNull("detail")?"":o.optString("detail");i.area=FeatureBoard.area(o.optString("area"));
        i.done=o.optBoolean("done",false);i.doneAt=number(o,"done_at");i.created=number(o,"created");i.updated=number(o,"updated");return i;
    }
    static List<FeatureBoard.Item> items(JSONObject snapshot){
        List<FeatureBoard.Item> list=new ArrayList<>();JSONArray rows=snapshot.optJSONArray("items");
        for(int n=0;rows!=null&&n<rows.length();n++){JSONObject o=rows.optJSONObject(n);if(o!=null&&!o.optString("id").isEmpty())list.add(item(o));}return list;
    }
    private static FeatureBoard.Change change(JSONObject o){
        FeatureBoard.Change ch=new FeatureBoard.Change();ch.id=o.optString("id");ch.op=o.optString("op");ch.target=o.optString("target");ch.state=o.optString("state");ch.at=number(o,"at");
        ch.title=o.has("title")?o.optString("title"):null;ch.detail=o.has("detail")?o.optString("detail"):null;ch.area=o.has("area")?o.optString("area"):null;ch.done=o.has("done")?o.optBoolean("done"):null;
        ch.origin=o.optString("origin");ch.error=o.optString("error");return ch;
    }
    private static JSONObject json(FeatureBoard.Change ch)throws JSONException{
        JSONObject o=new JSONObject().put("id",ch.id).put("op",ch.op).put("target",ch.target).put("at",ch.at).put("origin",ch.origin);
        if(ch.title!=null)o.put("title",ch.title);if(ch.detail!=null)o.put("detail",ch.detail);if(ch.area!=null)o.put("area",ch.area);if(ch.done!=null)o.put("done",ch.done.booleanValue());
        if(!ch.state.isEmpty())o.put("state",ch.state);if(!ch.error.isEmpty())o.put("error",ch.error);return o;
    }
    static synchronized List<FeatureBoard.Change> changes(Context c){
        try{JSONArray rows=new JSONArray(Cloud.prefs(c).getString("features_outbox","[]"));List<FeatureBoard.Change> list=new ArrayList<>();for(int n=0;n<rows.length();n++)list.add(change(rows.getJSONObject(n)));return list;}
        catch(Exception e){throw new IllegalStateException("Saved feature changes need recovery",e);}
    }
    private static void store(Context c,List<FeatureBoard.Change> list)throws JSONException{
        JSONArray rows=new JSONArray();for(FeatureBoard.Change ch:list)rows.put(json(ch));
        if(!Cloud.prefs(c).edit().putString("features_outbox",rows.toString()).commit())throw new IllegalStateException("Phone storage failed");
    }

    /** Optimistic list: open first, finished after, with every saved change applied. */
    static synchronized List<FeatureBoard.Item> board(Context c){return FeatureBoard.replay(items(cached(c)),changes(c));}
    static synchronized int waiting(Context c){int n=0;for(FeatureBoard.Change ch:changes(c))if(ch.state.isEmpty())n++;return n;}
    static synchronized List<FeatureBoard.Change> review(Context c){List<FeatureBoard.Change> list=new ArrayList<>();for(FeatureBoard.Change ch:changes(c))if(!ch.state.isEmpty())list.add(ch);return list;}

    private static FeatureBoard.Change next(Context c,String op,String target){FeatureBoard.Change ch=new FeatureBoard.Change();ch.id=UUID.randomUUID().toString();ch.op=op;ch.target=target;ch.at=System.currentTimeMillis()/1000.0;ch.origin=origin(c);return ch;}
    private static void enqueue(Context c,FeatureBoard.Change ch)throws Exception{
        synchronized(Features.class){
            List<FeatureBoard.Change> list=changes(c);
            if("delete".equals(ch.op))FeatureBoard.dropUpdates(list,ch.target,sending);
            if(!FeatureBoard.fold(list,ch,sending))list.add(ch);
            store(c,list);
        }
        TaskSyncJob.schedule(c,false);changed(c);
    }
    /** Returns the new item's client ID, which the server keeps, so a repeated create after a lost reply is harmless. */
    static String create(Context c,String title,String detail,String area)throws Exception{
        String clean=FeatureBoard.title(title);if(clean==null)throw new IllegalArgumentException("Enter a feature name");
        FeatureBoard.Change ch=next(c,"create",UUID.randomUUID().toString());ch.title=clean;ch.detail=FeatureBoard.detail(detail);ch.area=FeatureBoard.area(area);enqueue(c,ch);return ch.target;
    }
    static void done(Context c,String id,boolean done)throws Exception{FeatureBoard.Change ch=next(c,"update",id);ch.done=done;enqueue(c,ch);}
    static void edit(Context c,String id,String title,String detail,String area)throws Exception{
        String clean=FeatureBoard.title(title);if(clean==null)throw new IllegalArgumentException("Enter a feature name");
        FeatureBoard.Change ch=next(c,"update",id);ch.title=clean;ch.detail=FeatureBoard.detail(detail);ch.area=FeatureBoard.area(area);enqueue(c,ch);
    }
    static void delete(Context c,String id)throws Exception{enqueue(c,next(c,"delete",id));}
    /** Rejected changes stay on the phone until the owner sends them again or discards them. */
    static void resolve(Context c,boolean retry)throws Exception{
        synchronized(Features.class){
            List<FeatureBoard.Change> list=changes(c);String here=origin(c);
            for(Iterator<FeatureBoard.Change> it=list.iterator();it.hasNext();){FeatureBoard.Change ch=it.next();if(ch.state.isEmpty())continue;if(retry&&ch.origin.equals(here)){ch.state="";ch.error="";}else if(!retry)it.remove();}
            store(c,list);
        }
        if(retry)TaskSyncJob.schedule(c,false);changed(c);
    }

    private static String path(String id)throws Exception{return "features/"+URLEncoder.encode(id,"UTF-8");}
    /** HttpURLConnection has no PATCH, so edits use the server's POST features/{id} alias and deletes POST features/{id}/delete. */
    private static Object send(Context c,FeatureBoard.Change ch)throws Exception{
        if("create".equals(ch.op))return Cloud.call(c,"features",new JSONObject().put("id",ch.target).put("title",ch.title==null?"":ch.title).put("detail",ch.detail==null?"":ch.detail).put("area",FeatureBoard.area(ch.area)),true);
        if("delete".equals(ch.op))return Cloud.call(c,path(ch.target)+"/delete",new JSONObject(),true);
        JSONObject body=new JSONObject();if(ch.done!=null)body.put("done",ch.done.booleanValue());if(ch.title!=null)body.put("title",ch.title);if(ch.detail!=null)body.put("detail",ch.detail);if(ch.area!=null)body.put("area",ch.area);
        return Cloud.call(c,path(ch.target),body,true);
    }
    /** Folds an acknowledged change into the cached list so it does not flicker back before the next full read. */
    private static void settle(Context c,FeatureBoard.Change ch,Object reply,boolean gone)throws JSONException{
        JSONObject snapshot=cached(c);JSONArray rows=snapshot.optJSONArray("items"),next=new JSONArray();boolean remove=gone||"delete".equals(ch.op),placed=false;
        JSONObject item=!remove&&reply instanceof JSONObject&&ch.target.equals(((JSONObject)reply).optString("id"))?(JSONObject)reply:null,old=null;
        for(int n=0;rows!=null&&n<rows.length();n++){JSONObject row=rows.optJSONObject(n);if(row!=null&&ch.target.equals(row.optString("id")))old=row;}
        if(item==null&&!remove){
            // A reply without the item still must not lose the acknowledged edit; apply it to the cached row.
            item=old==null?new JSONObject().put("id",ch.target).put("title","").put("detail","").put("area","assistant").put("done",false).put("done_at",JSONObject.NULL).put("created",ch.at):new JSONObject(old.toString());
            if(ch.title!=null)item.put("title",ch.title);if(ch.detail!=null)item.put("detail",ch.detail);if(ch.area!=null)item.put("area",ch.area);
            if(ch.done!=null&&ch.done!=item.optBoolean("done")){item.put("done",ch.done.booleanValue()).put("done_at",ch.done?ch.at:JSONObject.NULL);}item.put("updated",ch.at);
        }
        for(int n=0;rows!=null&&n<rows.length();n++){JSONObject row=rows.optJSONObject(n);if(row==null)continue;if(!ch.target.equals(row.optString("id")))next.put(row);else if(!remove&&!placed){next.put(item);placed=true;}}
        if(!remove&&!placed)next.put(item);
        Cloud.prefs(c).edit().putString("features_snapshot",snapshot.put("items",next).toString()).putString("features_origin",origin(c)).commit();
    }
    static void flush(Context c)throws Exception{synchronized(sendLock){
        while(true){
            FeatureBoard.Change ch=null;boolean marked=false;
            synchronized(Features.class){
                List<FeatureBoard.Change> list=changes(c);String here=origin(c);
                for(FeatureBoard.Change row:list){if(!row.state.isEmpty())continue;if(!row.origin.equals(here)){row.state="needs_review";row.error="This change belongs to a different server";marked=true;continue;}ch=row;break;}
                if(marked)store(c,list);if(ch!=null)sending=ch.id;
            }
            if(marked)changed(c);if(ch==null)break;
            try{
                Object reply=send(c,ch);
                synchronized(Features.class){List<FeatureBoard.Change> list=changes(c);for(Iterator<FeatureBoard.Change> it=list.iterator();it.hasNext();)if(it.next().id.equals(ch.id))it.remove();store(c,list);settle(c,ch,reply,false);}
                changed(c);
            }catch(Cloud.HttpError error){
                String outcome=FeatureBoard.outcome(ch.op,error.status);if(outcome.equals("retry"))throw error;
                if(outcome.equals("drop")){android.util.Log.w("Features","Server declined a saved "+ch.op+" ("+error.status+"); removed from the outbox");Cloud.prefs(c).edit().putString("features_declined",ch.op+" "+error.status+" "+System.currentTimeMillis()).commit();}
                synchronized(Features.class){
                    List<FeatureBoard.Change> list=changes(c);
                    for(Iterator<FeatureBoard.Change> it=list.iterator();it.hasNext();){FeatureBoard.Change row=it.next();if(!row.id.equals(ch.id))continue;if(outcome.equals("drop"))it.remove();else{row.state="needs_review";row.error=String.valueOf(error.getMessage());}}
                    store(c,list);if(outcome.equals("drop"))settle(c,ch,null,true);
                }
                changed(c);
            }finally{synchronized(Features.class){sending=null;}}
        }
    }}
    /** Sends saved changes in order, then replaces the cached list; a newer local edit made meanwhile stays in the outbox and is replayed over it. */
    static void sync(Context c)throws Exception{synchronized(sendLock){
        flush(c);
        JSONObject result=(JSONObject)Cloud.call(c,"features",null,true);if(result.optJSONArray("items")==null)throw new JSONException("Unexpected features reply");
        synchronized(Features.class){if(!Cloud.prefs(c).edit().putString("features_snapshot",result.toString()).putString("features_origin",origin(c)).putLong("features_synced",System.currentTimeMillis()).remove("features_error").commit())throw new IllegalStateException("Phone storage failed");}
        changed(c);
    }}
    /** Background recovery from the task sync job; asks for a retry only while sendable changes remain. */
    static boolean background(Context c){
        if(Cloud.prefs(c).getString("token","").isEmpty())return false;
        try{sync(c);return false;}catch(Exception error){Cloud.prefs(c).edit().putString("features_error",String.valueOf(error.getMessage())).commit();changed(c);try{return waiting(c)>0;}catch(RuntimeException unreadable){return false;}}
    }
}
