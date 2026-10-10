package com.personalassistant.companion;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Framework-free rules for voice on the task details screen: control phrases, follow-up turn IDs, draft insertion and spoken answers. */
final class TaskTurns {
    private TaskTurns(){}
    // Same whole-request controls as the relay's conversation_control: a substantive request that merely contains them is not a control.
    private static final Pattern WAKE=Pattern.compile("^\\s*(?:hey|hej|ej)[ ,]+chat[,.!? ]*",Pattern.CASE_INSENSITIVE),PLEASE=Pattern.compile("^please\\s+",Pattern.CASE_INSENSITIVE);
    private static final Pattern START=Pattern.compile("(?:(?:start|enter|open) (?:a |the )?conversation(?: mode)?|conversation mode|let(?:['’]s| us) talk)[.!? ]*",Pattern.CASE_INSENSITIVE);
    private static final Pattern END=Pattern.compile("(?:stop|(?:end|finish|stop) (?:the )?conversation(?: mode)?|stop listening|goodbye|that was all|that['’]s all|I(?:['’]m| am) done)[.!? ]*",Pattern.CASE_INSENSITIVE);
    static final int SPOKEN_LIMIT=600;
    /** Fresh speech, in samples, before a capture counts as heard: the minimum CaptureTurnPolicy.finished asks of every turn. */
    static final int HEARD=2400;

    /** "end", "start" or null when the transcript is an instruction. */
    static String control(String text){
        if(text==null)return null;String cleaned=WAKE.matcher(text).replaceFirst("").trim();cleaned=PLEASE.matcher(cleaned).replaceFirst("");
        if(START.matcher(cleaned).matches())return "start";if(END.matcher(cleaned).matches())return "end";return null;
    }

    /**
     * Stop dictation for task stop: "finish" transcribes the capture in progress into the draft, "drop" ends one that has heard no
     * speech yet, "cancel" withdraws a dictation that has not begun, and "" leaves everything else alone, so a transcription already
     * in flight still reaches the draft. Stopping never cancels words the user already said.
     */
    static String stop(String stop,boolean active,String captureTask,boolean captureDictation,String target,boolean targetDictation,int freshSpeech){
        if(stop==null||stop.isEmpty())return "";
        if(active&&captureDictation&&stop.equals(captureTask))return freshSpeech>=HEARD?"finish":"drop";
        if(targetDictation&&stop.equals(target))return "cancel";
        return "";
    }

    /** The relay's continuation job ID for a follow-up ID: "continue-" and the first 48 hex digits of its SHA-256. */
    static String turnId(String followup){
        try{byte[] digest=java.security.MessageDigest.getInstance("SHA-256").digest(followup.getBytes("UTF-8"));StringBuilder hex=new StringBuilder("continue-");
            for(byte b:digest){hex.append(Character.forDigit((b>>4)&15,16)).append(Character.forDigit(b&15,16));}return hex.substring(0,9+48);}
        catch(Exception error){throw new IllegalStateException("SHA-256 unavailable",error);}
    }

    static final class Insertion {final String text,piece;final int start,caret;Insertion(String text,String piece,int start,int caret){this.text=text;this.piece=piece;this.start=start;this.caret=caret;}}
    /** Dictated words replace the selection; a space separates them from neighbouring words and the caret lands after them. */
    static Insertion insert(String draft,int start,int end,String words){
        String d=draft==null?"":draft;int s=Math.max(0,Math.min(Math.min(start,end),d.length())),e=Math.max(s,Math.min(Math.max(start,end),d.length()));String w=words==null?"":words.trim();
        if(w.isEmpty())return new Insertion(d,"",s,e);
        String before=d.substring(0,s),after=d.substring(e);
        boolean lead=!before.isEmpty()&&!Character.isWhitespace(before.charAt(before.length()-1)),trail=!after.isEmpty()&&Character.isLetterOrDigit(after.charAt(0));
        String piece=(lead?" ":"")+w+(trail?" ":"");return new Insertion(before+piece+after,piece,s,s+(lead?1:0)+w.length());
    }

    /** wait, answer, input, failed or cancelled for a follow-up turn's queue state. */
    static String outcome(String state){
        String s=state==null?"":state;
        if(s.equals("completed")||s.equals("complete"))return "answer";if(s.equals("needs_input"))return "input";if(s.equals("failed"))return "failed";if(s.equals("cancelled"))return "cancelled";return "wait";
    }

    /** What is read aloud when a turn settles; the written answer stays complete in the task conversation. */
    static String spoken(String state,String summary){
        String o=outcome(state),text=bounded(summary);
        if(o.equals("input"))return text.isEmpty()?"The task needs more information from you.":text;
        if(o.equals("failed"))return text.isEmpty()?"That follow-up failed.":"That follow-up failed. "+text;
        if(o.equals("cancelled"))return "That follow-up was cancelled.";
        return text.isEmpty()?"Done. There is no written answer.":text;
    }

    /** Plain speech from a worker summary: code, links and markdown are dropped and long answers end at a sentence. */
    static String bounded(String summary){
        if(summary==null)return "";
        String t=summary.replaceAll("(?s)```.*?```"," (code is in the task) ").replace("`","");
        t=t.replaceAll("!?\\[([^\\]]*)\\]\\([^)]*\\)","$1").replaceAll("https?://\\S+","a link");
        t=t.replaceAll("(?m)^\\s*(?:#{1,6}|[-*+>]|\\d+[.)])\\s+","").replace("**","").replace("__","");
        t=t.replaceAll("\\s+"," ").trim();
        if(t.length()<=SPOKEN_LIMIT)return t;
        String head=t.substring(0,SPOKEN_LIMIT);int cut=-1;Matcher m=Pattern.compile("[.!?](?=\\s)").matcher(head);while(m.find())cut=m.end();
        if(cut<SPOKEN_LIMIT/3){cut=head.lastIndexOf(' ');if(cut<=0)cut=SPOKEN_LIMIT;head=head.substring(0,cut).trim()+"…";}else head=head.substring(0,cut);
        return head+" The full answer is in the task.";
    }

    /** The composer's voice line for this task, from the shared raw voice status. */
    static String note(String mode,String raw){
        String low=raw==null?"":raw.toLowerCase(Locale.ROOT);boolean dictate="dictate".equals(mode);
        if(low.contains("starting")||low.contains("preparing"))return "Starting the microphone…";
        if(low.contains("permission")||low.contains("could not")||low.contains("unavailable")||low.contains("no internet")||low.contains("interrupted")||low.contains("busy"))return raw;
        if(low.contains("transcribing")||low.contains("sending"))return dictate?"Transcribing… Nothing is sent until you tap Send.":"Transcribing your words…";
        if(dictate)return low.contains("listening to your command")?"Listening… Pause when you finish. Nothing is sent until you tap Send.":"Dictation is on. Nothing is sent until you tap Send.";
        if(low.contains("waiting for the task"))return "Sent as a follow-up · waiting for the answer";
        if(low.contains("listening to your command"))return "Listening to you…";
        if(low.contains("conversation mode"))return "Listening · say your next instruction, or That was all to finish.";
        return "Talking about this task · each turn is sent as a follow-up. Say That was all to finish.";
    }
}
