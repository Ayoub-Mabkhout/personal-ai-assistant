package com.personalassistant.companion;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintStream;

/** Answers tab-separated requests on stdin for the companion classes that need no Android framework: sun, split and status. */
public final class AndroidLogicProbe {
    private AndroidLogicProbe(){}

    public static void main(String[] args)throws Exception{
        BufferedReader in=new BufferedReader(new InputStreamReader(System.in,"UTF-8"));
        PrintStream out=new PrintStream(System.out,true,"UTF-8");
        for(String line;(line=in.readLine())!=null;){
            final String[] f=line.split("\t",-1);
            if(f[0].equals("sun")){
                long at=Long.parseLong(f[1]);double latitude=f.length>2?Double.parseDouble(f[2]):DaylightTheme.LATITUDE;
                long[] times=DaylightTheme.sunTimes(at,latitude,DaylightTheme.LONGITUDE);
                out.println((times==null?"null":times[0]+","+times[1])+"\t"+DaylightTheme.dark(at)+"\t"+DaylightTheme.nextChange(at));
            }else if(f[0].equals("split")){
                out.println(String.join("\u001f",ItemSplitter.split(f.length>1?f[1]:null)));
            }else if(f[0].equals("status")){
                VoiceStatus s=VoiceStatus.of(f[1],f[2].equals("1"),f[3].equals("1"),f[4].equals("1"),f[5].equals("1"),()->Integer.parseInt(f[6]),f[7].equals("1"));
                out.println(s.title+"\t"+s.detail+"\t"+s.orb+"\t"+s.loading);
            }else out.println("unknown request");
        }
    }
}
