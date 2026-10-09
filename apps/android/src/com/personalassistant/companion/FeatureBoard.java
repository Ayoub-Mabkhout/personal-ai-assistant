package com.personalassistant.companion;

import java.util.*;

/** Framework-free rules of the features checklist: replaying saved phone changes over the last server list, ordering, input limits and folding repeated edits. */
final class FeatureBoard {
    static final int TITLE_MAX=200,DETAIL_MAX=1000;
    static final String[] AREAS={"assistant","companion","dashboard"};
    private FeatureBoard(){}

    static final class Item {
        String id="",title="",detail="",area="assistant";boolean done,pending;double doneAt,created,updated;int index;
        Item copy(){Item i=new Item();i.id=id;i.title=title;i.detail=detail;i.area=area;i.done=done;i.pending=pending;i.doneAt=doneAt;i.created=created;i.updated=updated;i.index=index;return i;}
    }
    /** One saved edit: create, update or delete of target. Null fields of an update are left alone. A non-empty state ("needs_review") keeps it out of sending and of the optimistic view. */
    static final class Change {String id="",op="",target="",title,detail,area,state="",origin="",error="";Boolean done;double at;}

    /** Trimmed title within the server limit, or null when nothing is left. */
    static String title(String raw){if(raw==null)return null;String value=raw.trim().replaceAll("\\s+"," ");if(value.isEmpty())return null;return value.length()>TITLE_MAX?value.substring(0,TITLE_MAX).trim():value;}
    static String detail(String raw){if(raw==null)return "";String value=raw.trim();return value.length()>DETAIL_MAX?value.substring(0,DETAIL_MAX).trim():value;}
    static String area(String raw){for(String known:AREAS)if(known.equals(raw))return known;return "assistant";}
    static String areaName(String area){return "companion".equals(area)?"Companion":"dashboard".equals(area)?"Dashboard":"Assistant";}

    /** The list as the phone should show it: server items with saved changes applied, open first in creation order (as the server and dashboard list them), then finished (most recently finished first). */
    static List<Item> replay(List<Item> snapshot,List<Change> queue){
        LinkedHashMap<String,Item> map=new LinkedHashMap<>();int n=0;
        for(Item item:snapshot){Item copy=item.copy();copy.index=n++;copy.pending=false;map.put(copy.id,copy);}
        for(Change change:queue){
            if(!change.state.isEmpty())continue;Item item=map.get(change.target);
            if("create".equals(change.op)){if(item!=null)continue;item=new Item();item.id=change.target;item.title=change.title==null?"":change.title;item.detail=change.detail==null?"":change.detail;item.area=area(change.area);item.created=item.updated=change.at;item.index=n++;item.pending=true;map.put(item.id,item);}
            else if("update".equals(change.op)&&item!=null){
                if(change.title!=null)item.title=change.title;if(change.detail!=null)item.detail=change.detail;if(change.area!=null)item.area=area(change.area);
                if(change.done!=null&&change.done!=item.done){item.done=change.done;item.doneAt=item.done?change.at:0;}
                item.updated=change.at;item.pending=true;
            }
            else if("delete".equals(change.op))map.remove(change.target);
        }
        List<Item> list=new ArrayList<>(map.values());
        Collections.sort(list,(a,b)->{
            if(a.done!=b.done)return a.done?1:-1;
            int order=a.done?Double.compare(b.doneAt,a.doneAt):Double.compare(a.created,b.created);
            return order!=0?order:Integer.compare(a.index,b.index);
        });
        return list;
    }
    static int open(List<Item> list){int count=0;for(Item item:list)if(!item.done)count++;return count;}

    /** Merges an update into the latest saved update of the same item when that one is not being sent; returns false when the update must be appended. */
    static boolean fold(List<Change> queue,Change next,String sending){
        if(!"update".equals(next.op))return false;
        for(int i=queue.size()-1;i>=0;i--){
            Change old=queue.get(i);if(!old.target.equals(next.target))continue;
            if(!"update".equals(old.op)||old.id.equals(sending)||!old.state.isEmpty())return false;
            if(next.title!=null)old.title=next.title;if(next.detail!=null)old.detail=next.detail;if(next.area!=null)old.area=next.area;if(next.done!=null)old.done=next.done;old.at=next.at;return true;
        }
        return false;
    }
    /** A delete makes waiting updates of the same item pointless; the create stays so a lost acknowledgement cannot leave an orphan on the server. */
    static int dropUpdates(List<Change> queue,String target,String sending){
        int dropped=0;for(Iterator<Change> it=queue.iterator();it.hasNext();){Change old=it.next();if(old.target.equals(target)&&"update".equals(old.op)&&!old.id.equals(sending)){it.remove();dropped++;}}return dropped;
    }
    /** Permanent server answers leave the outbox: 404 on an edit or delete (item gone), 409 (a deleted ID cannot come back) and 422 (invalid input).
     *  An unexpected 400/413 waits for the owner's review; anything else (offline, 5xx, 401, a server without the route yet) retries in order. */
    static String outcome(String op,int status){
        if((status==404&&!"create".equals(op))||status==409||status==422)return "drop";
        if(status==400||status==413)return "review";
        return "retry";
    }
}
