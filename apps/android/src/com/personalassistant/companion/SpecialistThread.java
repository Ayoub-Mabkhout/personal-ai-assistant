package com.personalassistant.companion;

import java.util.*;

/**
 * Merge rules for one specialist conversation (Coach or Money), free of Android and JSON so tests/jvm can drive them.
 * The user's message is shown from the phone at once; the server's row with the same ID replaces it. Each message has
 * one user bubble and one reply slot keyed by ID, so "Queued", "Thinking", partial text and the final answer all edit
 * the same bubble instead of adding new ones.
 */
final class SpecialistThread {
    /** Phone-side phases of a message the server has not listed yet. */
    static final String SENDING="sending",UNSENT="unsent",ACCEPTED="accepted";

    static final class Message {
        final String id,text;final double created;
        String state="",answer="",partial="",phase="",problem="";double answered;
        Message(String id,String text,double created){this.id=id;this.text=text==null?"":text;this.created=created;}
        Message state(String value){state=value==null?"":value;return this;}
        Message answer(String value,double at){answer=value==null?"":value;answered=at;return this;}
        Message partial(String value){partial=value==null?"":value;return this;}
    }

    /** One bubble. kind is user, answer, partial or status; key is stable for a message and its role. */
    static final class Row {
        final String key,id,kind,text,label,note;final double time;final boolean retry;
        Row(String key,String id,String kind,String text,String label,String note,double time,boolean retry){
            this.key=key;this.id=id;this.kind=kind;this.text=text;this.label=label;this.note=note;this.time=time;this.retry=retry;
        }
        boolean user(){return "user".equals(kind);}
        @Override public String toString(){return key+"|"+kind+"|"+label+"|"+note+"|"+text+(retry?"|retry":"");}
    }

    private final LinkedHashMap<String,Message> server=new LinkedHashMap<>(),local=new LinkedHashMap<>();

    /** A full page from the server (Coach returns the latest window each time). */
    void replace(List<Message> items){server.clear();for(Message m:items)put(m);}

    /** Adds or updates one server message (Money pages accumulate). */
    void put(Message m){if(m==null||m.id.isEmpty())return;server.put(m.id,m);local.remove(m.id);}

    boolean listed(String id){return server.containsKey(id);}

    /** Shows or moves a phone-side message. A message already listed by the server keeps the server's version. */
    void local(String id,String text,double created,String phase,String problem){
        if(server.containsKey(id))return;
        Message old=local.get(id);Message m=new Message(id,text,old==null?created:old.created);m.phase=phase;m.problem=problem==null?"":problem;local.put(id,m);
    }

    void forget(String id){local.remove(id);}

    /** True while any reply is still expected, so callers poll faster. */
    boolean waiting(){
        for(Message m:local.values())if(!UNSENT.equals(m.phase))return true;
        for(Message m:server.values())if(m.answer.isEmpty()&&!"failed".equals(m.state))return true;
        return false;
    }

    int size(){return server.size()+local.size();}

    List<Row> rows(String name,boolean online){
        ArrayList<Message> listed=new ArrayList<>(server.values());
        listed.sort((a,b)->{int t=Double.compare(a.created,b.created);return t!=0?t:a.id.compareTo(b.id);});
        ArrayList<Row> out=new ArrayList<>();
        for(Message m:listed)add(out,m,name,online);
        for(Message m:local.values())add(out,m,name,online);
        return out;
    }

    private static void add(List<Row> out,Message m,String name,boolean online){
        String phase=m.phase;
        if(SENDING.equals(phase)){out.add(user(m,"Sending…","",false));return;}
        if(UNSENT.equals(phase)){out.add(user(m,"Not sent",m.problem.isEmpty()?"Your message is saved on this phone.":m.problem,true));return;}
        out.add(user(m,"You",ACCEPTED.equals(phase)?"Sent":"",false));
        String reply=m.id+"|reply";
        if(!m.answer.isEmpty()){out.add(new Row(reply,m.id,"answer",m.answer,name,"failed".equals(m.state)?"Not completed":"",m.answered,false));return;}
        if(!m.partial.isEmpty()){out.add(new Row(reply,m.id,"partial",m.partial,name+" · Answering…","",0,false));return;}
        String text;
        if("failed".equals(m.state))text=name+" couldn't answer. Ask again.";
        else if("running".equals(m.state))text=name+" is thinking…";
        else text=online?"Queued · "+name+" will reply here.":"Queued · the reply arrives here when "+name+" is back online.";
        out.add(new Row(reply,m.id,"status",text,name,"",0,false));
    }

    private static Row user(Message m,String label,String note,boolean retry){
        return new Row(m.id+"|user",m.id,"user",m.text,label,note,SENDING.equals(m.phase)||UNSENT.equals(m.phase)?0:m.created,retry);
    }

    /** Retrying the same text and files reuses the saved ID, so the server answers once even if the first try arrived. */
    static String retryId(String savedKey,String savedId,String key,String fresh){
        return savedId!=null&&!savedId.isEmpty()&&key.equals(savedKey)?savedId:fresh;
    }

    /** Why a send was not confirmed, and whether Retry can help (0 means no HTTP answer at all). */
    static String problem(int httpStatus){
        if(httpStatus==0)return "No connection. Tap Retry when you're online.";
        if(httpStatus==401||httpStatus==403)return "This phone needs pairing again.";
        if(httpStatus==409)return "This message ID was already used for different content. Edit and send it again.";
        if(httpStatus==408||httpStatus==429||httpStatus>=500)return "Your server is busy. Tap Retry.";
        return "Your server refused this message. Edit it and send again.";
    }

    static boolean retryable(int httpStatus){return httpStatus==0||httpStatus==408||httpStatus==429||httpStatus>=500;}
}
