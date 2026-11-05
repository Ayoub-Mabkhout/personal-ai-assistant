package com.personalassistant.companion;

/** Wording for the worker and specialist chips. Plain Java so tests/jvm can check every state; an empty state is the only "Checking…". */
final class WorkerReadiness {
    static final String CHECKING="",READY="ready",BUSY="busy",BLOCKED="blocked",UNAVAILABLE="unavailable",
        UNPAIRED="unpaired",NO_NETWORK="no_network",UNREACHABLE="unreachable",TIMEOUT="timeout";
    /** A result this recent is shown at once by a new chip (another tab, a sheet, a recreated screen). */
    static final long FRESH_MS=120000;
    /** A chip still checking after this long says so instead of spinning forever. */
    static final long TIMEOUT_MS=12000;
    private WorkerReadiness(){}

    /** The relay's voice/status connection: assistant is the selected lane, then the VPS server worker, then the laptop. */
    static String pick(String assistant,String server,String laptop){
        for(String value:new String[]{assistant,server,laptop})if(value!=null&&!value.trim().isEmpty())return value.trim();
        return UNAVAILABLE;
    }

    /** What a failed status request means: 401 is a revoked pairing, anything else is a relay that did not answer. */
    static String failure(int httpStatus){return httpStatus==401||httpStatus==403?UNPAIRED:UNREACHABLE;}

    static boolean online(String state){return READY.equals(state)||BUSY.equals(state);}

    static String label(String name,String state){
        String s=state==null?"":state;
        if(s.isEmpty())return name+" · Checking…";
        if(online(s))return name+" online";
        if(BLOCKED.equals(s))return name+" · Usage limit";
        if(UNPAIRED.equals(s))return name+" · Not paired";
        if(NO_NETWORK.equals(s))return name+" · Phone offline";
        if(UNREACHABLE.equals(s))return name+" · Server unreachable";
        if(TIMEOUT.equals(s))return name+" · No response";
        return name+" offline";
    }

    static String tone(String state){
        String s=state==null?"":state;
        return s.isEmpty()||UNPAIRED.equals(s)?"neutral":online(s)?"success":"warning";
    }

    /** Spoken by TalkBack; the visible label is short, this one says what the state means. */
    static String description(String name,String state){
        String s=state==null?"":state;
        if(BLOCKED.equals(s))return name+" is paused by a usage limit. Messages stay queued.";
        if(UNPAIRED.equals(s))return name+" status needs a paired phone.";
        if(NO_NETWORK.equals(s))return "This phone has no connection, so "+name+" status is unknown.";
        if(UNREACHABLE.equals(s))return "Your server did not answer, so "+name+" status is unknown.";
        if(TIMEOUT.equals(s))return name+" status did not arrive in time.";
        return label(name,s);
    }
}
