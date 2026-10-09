package com.personalassistant.companion;
public final class TimerHarness {
    public static void main(String[] args)throws Exception{
        java.io.BufferedReader input=new java.io.BufferedReader(new java.io.InputStreamReader(System.in,"UTF-8"));String line;
        while((line=input.readLine())!=null){if(line.startsWith("gate:")){String[] parts=line.substring(5).split(",");System.out.println(CaptureTurnPolicy.finished(Integer.parseInt(parts[0]),Integer.parseInt(parts[1]),Integer.parseInt(parts[2]),Boolean.parseBoolean(parts[3])));}else System.out.println(String.valueOf(TimerCommand.seconds(line)));}
    }
}
