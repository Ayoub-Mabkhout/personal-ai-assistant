package com.personalassistant.companion;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.util.*;

/** Answers tab-separated requests on stdin for the companion classes that need no Android framework: sun, split, status, the features checklist rules and the task voice rules, including Stop dictation. */
public final class AndroidLogicProbe {
    private AndroidLogicProbe(){}

    public static void main(String[] args)throws Exception{
        BufferedReader in=new BufferedReader(new InputStreamReader(System.in,"UTF-8"));
        PrintStream out=new PrintStream(System.out,true,"UTF-8");
        for(String line;(line=in.readLine())!=null;){
            final String[] f=line.split("\t",-1);
            if(f[0].equals("sun")){
                long at=Long.parseLong(f[1]);double latitude=Double.parseDouble(f[2]),longitude=Double.parseDouble(f[3]);
                long[] times=DaylightTheme.sunTimes(at,latitude,longitude);
                out.println((times==null?"null":times[0]+","+times[1])+"\t"+DaylightTheme.dark(at,latitude,longitude)+"\t"+DaylightTheme.nextChange(at,latitude,longitude));
            }else if(f[0].equals("split")){
                out.println(String.join("\u001f",ItemSplitter.split(f.length>1?f[1]:null)));
            }else if(f[0].equals("status")){
                VoiceStatus s=VoiceStatus.of(f[1],f[2].equals("1"),f[3].equals("1"),f[4].equals("1"),f[5].equals("1"),()->Integer.parseInt(f[6]),f[7].equals("1"));
                out.println(s.title+"\t"+s.detail+"\t"+s.orb+"\t"+s.loading);
            }else if(f[0].equals("board")){
                List<FeatureBoard.Item> list=FeatureBoard.replay(items(f[1]),changes(f[2]));StringBuilder ids=new StringBuilder(),pending=new StringBuilder();
                for(FeatureBoard.Item item:list){ids.append(ids.length()==0?"":",").append(item.id).append(item.done?"+":"");if(item.pending)pending.append(pending.length()==0?"":",").append(item.id);}
                out.println(ids+"\t"+FeatureBoard.open(list)+"\t"+pending);
            }else if(f[0].equals("fold")){
                List<FeatureBoard.Change> queue=changes(f[1]);FeatureBoard.Change next=changes(f[2]).get(0);
                if(next.op.equals("delete"))FeatureBoard.dropUpdates(queue,next.target,f[3]);
                boolean folded=FeatureBoard.fold(queue,next,f[3]);if(!folded)queue.add(next);StringBuilder rows=new StringBuilder();
                for(FeatureBoard.Change ch:queue)rows.append(rows.length()==0?"":";").append(ch.id).append(',').append(ch.op).append(',').append(ch.target).append(',').append(ch.done==null?"-":ch.done?"1":"0").append(',').append(ch.title==null?"-":ch.title);
                out.println(folded+"\t"+rows);
            }else if(f[0].equals("title")){
                String value=FeatureBoard.title(f[1]);out.println(value==null?"null":value.length()+"\t"+value);
            }else if(f[0].equals("outcome")){
                out.println(FeatureBoard.outcome(f[1],Integer.parseInt(f[2])));
            }else if(f[0].equals("control")){
                String control=TaskTurns.control(f[1]);out.println(control==null?"none":control);
            }else if(f[0].equals("turn")){
                out.println(TaskTurns.turnId(f[1]));
            }else if(f[0].equals("insert")){
                TaskTurns.Insertion r=TaskTurns.insert(f[1],Integer.parseInt(f[2]),Integer.parseInt(f[3]),f[4]);out.println(r.text+"\t"+r.caret+"\t"+r.start+"\t"+r.piece);
            }else if(f[0].equals("settle")){
                out.println(TaskTurns.outcome(f[1])+"\t"+TaskTurns.spoken(f[1],f[2].replace("\\n","\n")));
            }else if(f[0].equals("note")){
                out.println(TaskTurns.note(f[1],f[2]));
            }else if(f[0].equals("stop")){
                // stop, capture active, capture task, capture is a dictation, requested task, request is a dictation, fresh speech
                String result=TaskTurns.stop(blank(f[1]),f[2].equals("1"),blank(f[3]),f[4].equals("1"),blank(f[5]),f[6].equals("1"),Integer.parseInt(f[7]));
                out.println(result.isEmpty()?"none":result);
            }else if(f[0].equals("heard")){
                int fresh=Integer.parseInt(f[1]);out.println(TaskTurns.stop("t",true,"t",true,null,false,fresh)+"\t"+CaptureTurnPolicy.finished(80000,fresh,19200,false));
            }else out.println("unknown request");
        }
    }

    private static String blank(String value){return value.isEmpty()?null:value;}
    /** id,done,created,doneAt;... */
    private static List<FeatureBoard.Item> items(String spec){
        List<FeatureBoard.Item> list=new ArrayList<>();if(spec.isEmpty())return list;
        for(String row:spec.split(";")){String[] v=row.split(",",-1);FeatureBoard.Item item=new FeatureBoard.Item();item.id=v[0];item.title="Feature "+v[0];item.done=v[1].equals("1");item.created=Double.parseDouble(v[2]);item.doneAt=Double.parseDouble(v[3]);list.add(item);}
        return list;
    }
    /** id,op,target,done(-|0|1),at,state,title;... */
    private static List<FeatureBoard.Change> changes(String spec){
        List<FeatureBoard.Change> list=new ArrayList<>();if(spec.isEmpty())return list;
        for(String row:spec.split(";")){String[] v=row.split(",",-1);FeatureBoard.Change ch=new FeatureBoard.Change();ch.id=v[0];ch.op=v[1];ch.target=v[2];ch.done=v[3].equals("-")?null:Boolean.valueOf(v[3].equals("1"));ch.at=Double.parseDouble(v[4]);ch.state=v[5];ch.title=v[6].equals("-")?null:v[6];list.add(ch);}
        return list;
    }
}
