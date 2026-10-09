package com.personalassistant.companion;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Strict, deterministic duration grammar. A timer request never becomes an agent task. */
final class TimerCommand {
    private static final Pattern START=Pattern.compile("^(?:please )?(?:can you |could you )?(?:set|start) (?:me )?(?:a |the )?timer(?: for)?(?: (.*))?$");
    private static final Pattern PART=Pattern.compile("(.+?) (hours?|hrs?|minutes?|mins?|seconds?|secs?)(?: |$)");
    static String clean(String text){return text.toLowerCase(Locale.ROOT).replaceAll("[,.!?]$", "").replaceAll("^\\s*(?:hey|hej|ej)[ ,]+chat[,.!? ]*", "").replaceAll("(?<=[a-z])-(?=[a-z])", " ").replaceAll("\\s+", " ").trim().replaceAll("[.!?]+$", "").trim();}
    static boolean candidate(String text){return START.matcher(clean(text)).matches();}
    /** null means not a timer; zero means a timer request with an invalid/unsupported duration. */
    static Integer seconds(String text){
        Matcher start=START.matcher(clean(text));if(!start.matches())return null;
        String duration=start.group(1);if(duration==null)return 0;
        duration=duration.replaceAll(" please$", "");
        Matcher parts=PART.matcher(duration);int end=0;double total=0;boolean seen=false;
        while(parts.find()){
            if(parts.start()!=end)return 0;
            String quantity=parts.group(1).replaceAll("^and ", "");
            double amount=number(quantity);if(amount<=0)return 0;
            String unit=parts.group(2);total+=amount*(unit.startsWith("h")?3600:unit.startsWith("m")?60:1);
            end=parts.end();seen=true;
        }
        // Android's public Clock contract supports 1–86400 seconds. Never truncate or round.
        return seen&&end==duration.length()&&total>=1&&total<=86400&&total==Math.floor(total)?(int)total:0;
    }
    private static double number(String value){
        if(value.endsWith(" and a half")){double whole=number(value.substring(0,value.length()-11));return whole>0?whole+.5:-1;}
        if(value.matches("[0-9]+(?:\\.[0-9]+)?"))try{return Double.parseDouble(value);}catch(NumberFormatException e){return -1;}
        if(value.equals("a")||value.equals("an"))return 1;
        if(value.equals("half a")||value.equals("half an"))return .5;
        if(value.equals("a quarter of an")||value.equals("a quarter of a"))return .25;
        String[] ones={"zero","one","two","three","four","five","six","seven","eight","nine","ten","eleven","twelve","thirteen","fourteen","fifteen","sixteen","seventeen","eighteen","nineteen"};
        String[] tens={"","","twenty","thirty","forty","fifty","sixty","seventy","eighty","ninety"};
        int sum=0,current=0;boolean previousSmall=false;
        for(String word:value.split(" ")){
            if(word.equals("and")){if(current==0)return -1;continue;}
            if(word.equals("hundred")){if(current<1||current>9)return -1;current*=100;previousSmall=false;continue;}
            if(word.equals("thousand")){if(current<1)return -1;sum+=current*1000;current=0;previousSmall=false;continue;}
            int digit=-1;for(int i=0;i<ones.length;i++)if(word.equals(ones[i]))digit=i;
            if(digit>=0){if(previousSmall)return -1;current+=digit;previousSmall=true;continue;}
            int ten=-1;for(int i=2;i<tens.length;i++)if(word.equals(tens[i]))ten=i*10;
            if(ten<0||previousSmall||current%100>=20)return -1;current+=ten;
        }
        return sum+current;
    }
    static String duration(int seconds){int hours=seconds/3600,minutes=seconds%3600/60,remainder=seconds%60;String result="";if(hours>0)result=hours+" hour"+(hours==1?"":"s");if(minutes>0)result+=(result.isEmpty()?"":" ")+minutes+" minute"+(minutes==1?"":"s");if(remainder>0)result+=(result.isEmpty()?"":" ")+remainder+" second"+(remainder==1?"":"s");return result;}
}
