package com.personalassistant.companion;

import java.util.*;

/** Battery cost of the Hey Chat listener from periodic on-phone samples; plain Java so the JVM tests can drive it.
 *  Only unplugged intervals whose two ends agree on listener and screen state count. The listener's own cost is the
 *  screen-off drain while listening minus the screen-off drain with the listener off. */
final class BatteryUsage {
    static final int OFF=0,LISTENING=1,OTHER=2;
    static final long HOUR=3600000L,MIN_MS=2*HOUR,MAX_GAP_MS=12*HOUR,CLOCK_SLACK_MS=120000L,STEADY_MS=24*HOUR,ESTIMATE_MS=6*HOUR;
    /** Above this awake share a listener-off, screen-off interval most likely hid phone use between samples. */
    static final double IDLE_AWAKE_MAX=.5;
    static final long CHARGE_RISE_UAH=20000;
    private BatteryUsage(){}

    /** One reading: wall and elapsed clocks guard against reboots and clock changes; uptime stops in deep sleep. */
    static final class Sample {
        final long wall,elapsed,uptime,chargeUah,wakes;final int level,mode;final boolean plugged,screen;
        Sample(long wall,long elapsed,long uptime,int level,long chargeUah,boolean plugged,boolean screen,int mode,long wakes){this.wall=wall;this.elapsed=elapsed;this.uptime=uptime;this.level=level;this.chargeUah=chargeUah;this.plugged=plugged;this.screen=screen;this.mode=mode;this.wakes=wakes;}
        String line(){return wall+"\t"+elapsed+"\t"+uptime+"\t"+level+"\t"+chargeUah+"\t"+(plugged?1:0)+"\t"+(screen?1:0)+"\t"+mode+"\t"+wakes;}
        static Sample parse(String line){
            if(line==null)return null;String[] f=line.trim().split("\t");if(f.length!=9)return null;
            try{int level=Integer.parseInt(f[3]),mode=Integer.parseInt(f[7]);if(level<0||level>100||mode<OFF||mode>OTHER)return null;
                return new Sample(Long.parseLong(f[0]),Long.parseLong(f[1]),Long.parseLong(f[2]),level,Long.parseLong(f[4]),"1".equals(f[5]),"1".equals(f[6]),mode,Long.parseLong(f[8]));}
            catch(NumberFormatException e){return null;}
        }
        /** Same recorded state as another sample, so a new periodic reading would add nothing. */
        boolean sameState(Sample o){return o!=null&&o.level==level&&o.plugged==plugged&&o.screen==screen&&o.mode==mode&&o.wakes==wakes;}
    }

    /** Accumulated unplugged time and drop for one state; the charge counter part only where both ends reported it. */
    static final class Bucket {
        long ms,counterMs,uah;int drop,intervals;
        void add(Sample a,Sample b){long d=b.elapsed-a.elapsed;ms+=d;drop+=a.level-b.level;intervals++;if(a.chargeUah>0&&b.chargeUah>0){counterMs+=d;uah+=a.chargeUah-b.chargeUah;}}
        boolean ready(){return ms>=MIN_MS;}
        double hours(){return ms/(double)HOUR;}
        /** mAh per hour from the charge counter, or NaN without enough counter coverage. */
        double mahPerHour(){return counterMs>=MIN_MS&&counterMs*2>=ms?(uah/1000.0)/(counterMs/(double)HOUR):Double.NaN;}
        /** Percent per hour: counter-based when the capacity is known, otherwise from the whole-percent level. */
        double percentPerHour(double capacityMah){double mah=mahPerHour();if(!Double.isNaN(mah)&&capacityMah>0)return mah*100/capacityMah;return ms>0?drop/(ms/(double)HOUR):Double.NaN;}
    }

    static final class Report {
        final Bucket idle=new Bucket(),active=new Bucket(),baseline=new Bucket();
        int skipped;double capacityMah=Double.NaN;int samples;
        boolean ready(){return idle.ready();}
        boolean comparable(){return idle.ready()&&baseline.ready();}
        /** Listener's own share of screen-off drain in percent per hour, or NaN until both sides have enough time. */
        double cost(){if(!comparable())return Double.NaN;return Math.max(0,idle.percentPerHour(capacityMah)-baseline.percentPerHour(capacityMah));}
        double costMah(){if(!comparable())return Double.NaN;double on=idle.mahPerHour(),off=baseline.mahPerHour();return Double.isNaN(on)||Double.isNaN(off)?Double.NaN:Math.max(0,on-off);}
        /** Weakest evidence decides the wording. */
        String confidence(){if(!ready())return "Measuring";long weakest=comparable()?Math.min(idle.ms,baseline.ms):idle.ms;return weakest>=STEADY_MS?"Steady estimate":weakest>=ESTIMATE_MS?"Estimate":"Early estimate";}
        String tone(){String c=confidence();return c.equals("Steady estimate")?"success":c.equals("Measuring")?"neutral":"info";}
        /** Short value for the Settings row. */
        String summary(){if(comparable())return cost()<0.05?"Under 0.1%/h":percent(cost())+"/h";return ready()?percent(idle.percentPerHour(capacityMah))+"/h total":"Measuring";}
        String headline(){
            if(comparable()){double c=cost();return c<0.05?"Listening costs too little to separate from normal standby drain":"Listening costs about "+percent(c)+" per hour with the screen off";}
            if(ready())return "With listening on, the phone uses about "+percent(idle.percentPerHour(capacityMah))+" per hour with the screen off";
            return "Measuring battery use";
        }
        String detail(){
            if(comparable()){double c=cost(),mah=costMah();return "About "+percent(c*8)+" over 8 hours"+(Double.isNaN(mah)?"":" ("+Math.round(mah)+" mAh per hour)")+". Based on "+hours(idle.ms)+" listening and "+hours(baseline.ms)+" with listening off, screen off and unplugged.";}
            if(ready())return "That includes the phone's normal standby drain. Based on "+hours(idle.ms)+". To separate the listener's share, also leave Background listening off for "+hours(Math.max(0,MIN_MS-baseline.ms))+" more unplugged with the screen off.";
            return "Leave Background listening on for a few hours unplugged with the screen off. So far "+hours(idle.ms)+" of the "+hours(MIN_MS)+" needed. Charging time is never counted.";
        }
        String row(Bucket b){
            if(b.ms==0)return "No time yet";if(!b.ready())return hours(b.ms)+" of "+hours(MIN_MS)+" needed";
            double mah=b.mahPerHour();return percent(b.percentPerHour(capacityMah))+"/h"+(Double.isNaN(mah)?"":" · "+Math.round(mah)+" mAh/h")+" · "+hours(b.ms);
        }
    }

    static String percent(double value){return String.format(Locale.ROOT,value<10?"%.1f%%":"%.0f%%",value);}
    static String hours(long ms){double h=ms/(double)HOUR;return h<1?Math.round(ms/60000.0)+" min":String.format(Locale.ROOT,h<10?"%.1f h":"%.0f h",h);}

    /** Why an interval between consecutive samples does not count; null when it does. */
    static String exclusion(Sample a,Sample b){
        long d=b.elapsed-a.elapsed,wall=b.wall-a.wall;
        if(d<=0||Math.abs(wall-d)>CLOCK_SLACK_MS)return "restart or clock change";
        if(d>MAX_GAP_MS)return "gap";
        if(a.plugged||b.plugged)return "charging";
        if(b.level>a.level||(a.chargeUah>0&&b.chargeUah>0&&b.chargeUah-a.chargeUah>CHARGE_RISE_UAH))return "charged between samples";
        if(a.mode!=b.mode||a.screen!=b.screen)return "state changed";
        if(a.mode==OTHER)return "voice use";
        if(b.wakes!=a.wakes)return "voice use";
        if(a.mode==OFF&&!a.screen){long up=b.uptime-a.uptime;if(up<0||up>d+CLOCK_SLACK_MS)return "restart or clock change";if(up>d*IDLE_AWAKE_MAX)return "phone in use";}
        return null;
    }

    /** Full-battery capacity from counter/level pairs (median), or NaN where the counter is absent or implausible. */
    static double capacityMah(List<Sample> samples){
        List<Double> values=new ArrayList<>();for(Sample s:samples)if(s.chargeUah>0&&s.level>=15)values.add(s.chargeUah/10.0/s.level);
        if(values.isEmpty())return Double.NaN;Collections.sort(values);double median=values.get(values.size()/2);return median>=500&&median<=20000?median:Double.NaN;
    }

    static Report report(List<Sample> samples){
        Report r=new Report();r.samples=samples.size();r.capacityMah=capacityMah(samples);
        for(int i=1;i<samples.size();i++){Sample a=samples.get(i-1),b=samples.get(i);
            if(exclusion(a,b)!=null){if(b.elapsed-a.elapsed>0)r.skipped++;continue;}
            if(a.mode==LISTENING)(a.screen?r.active:r.idle).add(a,b);else if(a.mode==OFF&&!a.screen)r.baseline.add(a,b);
        }
        return r;
    }

    /**
     * The listener state a reading records: OFF without the microphone, LISTENING only for plain Hey Chat listening, OTHER for any
     * voice use. That includes a conversation between turns: a task conversation awaiting its answer keeps the microphone on the
     * communication path (echo cancellation, speakerphone) although no capture or reply is active.
     */
    static int mode(boolean mic,boolean wake,boolean voiceActive,boolean conversation,String taskVoice){
        if(!mic)return OFF;return wake&&!voiceActive&&!conversation&&(taskVoice==null||!taskVoice.startsWith("talk:"))?LISTENING:OTHER;
    }

    static List<Sample> parse(List<String> lines){List<Sample> out=new ArrayList<>();for(String line:lines){Sample s=Sample.parse(line);if(s!=null)out.add(s);}return out;}
}
