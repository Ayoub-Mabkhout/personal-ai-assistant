package com.personalassistant.companion;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** Reads sample cases from stdin (Sample.line rows, each case closed by "end"; "exclude" rows ask why one interval is
 *  left out) and prints one tab-separated report row per case for tests/test_android_battery.py. */
public final class BatteryUsageProbe {
    public static void main(String[] args)throws IOException {
        BufferedReader in=new BufferedReader(new InputStreamReader(System.in,StandardCharsets.UTF_8));PrintStream out=new PrintStream(System.out,true,"UTF-8");
        List<String> lines=new ArrayList<>();String line;
        while((line=in.readLine())!=null){
            if(line.equals("end")){List<BatteryUsage.Sample> samples=BatteryUsage.parse(lines);lines.clear();BatteryUsage.Report r=BatteryUsage.report(samples);
                out.println(samples.size()+"\t"+r.idle.ms+"\t"+r.active.ms+"\t"+r.baseline.ms+"\t"+r.idle.drop+"\t"+r.baseline.drop+"\t"+r.skipped+"\t"+num(r.cost())+"\t"+num(r.costMah())+"\t"+num(r.capacityMah)+"\t"+r.confidence()+"\t"+r.summary()+"\t"+r.headline());}
            else if(line.startsWith("exclude\t")){String[] parts=line.substring(8).split("\\|");String why=BatteryUsage.exclusion(BatteryUsage.Sample.parse(parts[0]),BatteryUsage.Sample.parse(parts[1]));out.println(why==null?"counted":why);}
            else lines.add(line);
        }
    }
    private static String num(double value){return Double.isNaN(value)?"NaN":String.format(Locale.ROOT,"%.3f",value);}
}
