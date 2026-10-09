package com.personalassistant.companion;

import java.util.Locale;
import java.util.function.IntSupplier;

/** Title, detail and orb state for the raw voice_status text; the Voice tab, the locked entry and the assistant overlay share it. */
final class VoiceStatus {
    final String title,detail,orb;final boolean loading;
    private VoiceStatus(String title,String detail,String orb,boolean loading){this.title=title;this.detail=detail;this.orb=orb;this.loading=loading;}

    static boolean live(String orb){return orb.equals("listening")||orb.equals("conversation");}
    boolean live(){return live(orb);}

    /** Only the Voice tab (inApp) has a Resume button; only the other screens can tell the user to open the app. */
    static VoiceStatus of(String raw,boolean mic,boolean wake,boolean test,boolean conversation,IntSupplier pending,boolean inApp){
        String low=raw.toLowerCase(Locale.ROOT);boolean loading=low.contains("starting")||low.contains("preparing")||low.contains("loading");
        if(inApp&&wake&&!mic&&!loading)return new VoiceStatus(test?"Wake test paused":"Listening paused","Background listening is enabled, but the microphone is off. Resume to restart it.","idle",loading);
        if(test)return new VoiceStatus(loading?"Getting ready...":"Wake test","Local only. Say Hey Chat at your normal volume.",loading?"working":"idle",loading);
        if(loading)return new VoiceStatus("Getting ready...","The microphone and wake model are starting.","working",true);
        if(mic&&low.contains("transcribing"))return new VoiceStatus("Transcribing...","Turning your words into text.","working",false);
        if(mic&&low.contains("waiting for the task"))return new VoiceStatus("Waiting for the answer","Your follow-up was sent to the task. Its answer will be read aloud.","working",false);
        if(low.contains("sending")||low.contains("connecting"))return new VoiceStatus("Connecting...","Your audio is buffered while the connection starts.","working",false);
        if(!inApp&&low.startsWith("open "))return new VoiceStatus("Open the app to start",raw,"attention",false);
        if(low.contains("no internet")||low.contains("saved on this phone")||low.contains("cloud unavailable"))return new VoiceStatus(pending.getAsInt()>0?"Saved offline":wake&&mic?"Listening offline":"Offline",raw,"offline",false);
        if(low.contains("permission")||low.contains("interrupted")||low.contains("could not")||low.contains("unavailable")||low.contains("voice stopped")||low.contains("connection lost"))return new VoiceStatus("Needs attention",raw,"attention",false);
        if(mic&&(conversation||low.contains("live voice")||low.contains("live microphone")||low.contains("conversation mode")))return new VoiceStatus("Conversation active","Speak naturally. Say That was all to end.","conversation",false);
        if(mic&&low.contains("listening to your command"))return new VoiceStatus("Listening to you","Say your full request, then pause.","listening",false);
        if(low.contains("no speech"))return new VoiceStatus("No speech heard","Tap Talk to try again.","idle",false);
        if(wake&&mic)return new VoiceStatus("Listening for Hey Chat","You can leave this "+(inApp?"app":"screen")+" or lock your phone.","idle",false);
        if(mic)return new VoiceStatus("Microphone ready","Tap Talk to start a request.","idle",false);
        return new VoiceStatus("Microphone off",inApp?"Tap Talk, or turn on Background listening.":"Tap Talk to start talking.","idle",false);
    }
}
