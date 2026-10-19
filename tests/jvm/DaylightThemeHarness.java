package com.personalassistant.companion;

import java.time.Instant;

/** Real solar equations and scheduling decisions, using neutral synthetic coordinates. */
public final class DaylightThemeHarness {
    private static int checks;
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    private static long at(String value){return Instant.parse(value).toEpochMilli();}
    public static void main(String[] args){
        long equinox=at("2026-03-20T12:00:00Z");long[] day=DaylightTheme.sunTimes(equinox,0,0);
        check(day!=null&&day[0]<day[1],"Equatorial day must have ordered events");
        check(day[1]-day[0]>11*3600000L&&day[1]-day[0]<13*3600000L,"Equatorial daylight must be about twelve hours");
        check(DaylightTheme.dark(day[0]-1,0,0)&&!DaylightTheme.dark(day[0],0,0),"Sunrise boundary must switch once");
        check(!DaylightTheme.dark(day[1]-1,0,0)&&DaylightTheme.dark(day[1],0,0),"Sunset boundary must switch once");
        check(DaylightTheme.nextChange(day[0]-1,0,0)==day[0],"Before sunrise must schedule sunrise");
        check(DaylightTheme.nextChange(day[0],0,0)==day[1],"At sunrise must schedule sunset");
        check(DaylightTheme.nextChange(day[1],0,0)>day[1],"At sunset must schedule a strictly future event");
        long[] east=DaylightTheme.sunTimes(equinox,0,180),west=DaylightTheme.sunTimes(equinox,0,-180);
        check(Math.abs(east[0]-west[0])<=1&&Math.abs(east[1]-west[1])<=1,"Dateline aliases must agree");
        for(double longitude:new double[]{179,-179}){long current=equinox;for(int i=0;i<8;i++){long next=DaylightTheme.nextChange(current,0,longitude);check(next>current,"UTC date crossings cannot schedule in the past");current=next;}}
        long edge=at("2026-06-29T00:02:00Z");
        check(!DaylightTheme.dark(edge,65.88,0),"Nearest cycle must not skip the prior sunset");
        long edgeNext=DaylightTheme.nextChange(edge,65.88,0);
        check(edgeNext>edge&&edgeNext-edge<180000,"Prior cycle sunset must remain the next transition");
        long summer=at("2026-06-21T12:00:00Z"),winter=at("2026-12-21T12:00:00Z");
        check(!DaylightTheme.dark(summer,80,0)&&DaylightTheme.dark(winter,80,0),"Northern polar light/dark must retain altitude classification");
        check(DaylightTheme.dark(summer,-80,0)&&!DaylightTheme.dark(winter,-80,0),"Southern polar seasons must reverse");
        check(!DaylightTheme.dark(at("2026-03-19T12:00:00Z"),90,0),"Apparent polar daylight includes the sunrise refraction threshold");
        long polarNext=DaylightTheme.nextChange(summer,80,0);
        check(polarNext>summer&&polarNext-summer<=3600000L,"Polar reevaluation must be bounded and future");
        for(double[] invalid:new double[][]{{Double.NaN,0},{0,Double.POSITIVE_INFINITY},{91,0},{0,-181}}){boolean rejected=false;try{DaylightTheme.sunTimes(equinox,invalid[0],invalid[1]);}catch(IllegalArgumentException expected){rejected=true;}check(rejected,"Invalid coordinates must not create epoch-zero events");}
        check(DaylightTheme.resolve("sun",true,equinox,null,null)&&!DaylightTheme.resolve("sun",false,equinox,null,null),"Unconfigured Sun follows System in both modes");
        check(DaylightTheme.resolve("sun",true,equinox,Double.NaN,0d),"Invalid cached coordinates follow System");
        check(!DaylightTheme.resolve("light",true,equinox,null,null)&&DaylightTheme.resolve("dark",false,equinox,null,null),"Explicit choices remain authoritative");
        DaylightTheme.Refresh before=DaylightTheme.refresh(false,false,true,day[1]-500,day[1]);
        check(!before.apply&&before.delay==500,"Foreground timer must target the boundary");
        DaylightTheme.Refresh blocked=DaylightTheme.refresh(false,true,false,day[1],DaylightTheme.nextChange(day[1],0,0));
        check(!blocked.apply&&blocked.delay>0&&blocked.delay<=1000,"Active capture/dialog defers without dropping a transition");
        DaylightTheme.Refresh released=DaylightTheme.refresh(false,true,true,day[1]+1000,DaylightTheme.nextChange(day[1]+1000,0,0));
        check(released.apply,"Deferred transition applies when host becomes idle");
        check(DaylightTheme.refresh(false,false,true,equinox,Long.MAX_VALUE).delay==Long.MAX_VALUE,"System fallback needs no solar polling timer");
        int[] dayPalette=DaylightPalette.blend(40,.5,0),nightPalette=DaylightPalette.blend(-30,.5,0),dusk=DaylightPalette.blend(2,0,0);
        check(java.util.Arrays.equals(dayPalette,DaylightPalette.fixed(false))&&java.util.Arrays.equals(nightPalette,DaylightPalette.fixed(true)),"Daylight plateaus are the Light and Dark palettes");
        check(!DaylightPalette.dark(dayPalette)&&DaylightPalette.dark(nightPalette)&&!DaylightPalette.dark(dayPalette)&&DaylightPalette.dark(nightPalette),"Foreground polarity follows the palette");
        check(!DaylightPalette.differs(dusk,DaylightPalette.blend(2.05,0,0)),"A minute of drift does not repaint");
        check(DaylightPalette.differs(dusk,dayPalette)&&DaylightPalette.differs(dusk,DaylightPalette.blend(-1,0,0)),"Perceptible drift or a polarity flip repaints");
        DaylightTheme.Refresh drift=DaylightPalette.refresh(dusk,dayPalette,false);
        check(!drift.apply&&drift.delay==1000L,"Capture defers a Daylight repaint without dropping it");
        check(DaylightPalette.refresh(dusk,dayPalette,true).apply,"Idle host repaints the drifted palette");
        DaylightTheme.Refresh steady=DaylightPalette.refresh(dusk,dusk,true);
        check(!steady.apply&&steady.delay==DaylightPalette.TICK,"Daylight rechecks every minute while foreground");
        boolean invalidPlace=false;try{DaylightPalette.at(equinox,Double.NaN,0,0);}catch(IllegalArgumentException expected){invalidPlace=true;}check(invalidPlace,"Unknown places require a runtime System fallback, never a baked-in home");
        System.out.println("{\"checks\":"+checks+",\"passed\":true}");
    }
}
