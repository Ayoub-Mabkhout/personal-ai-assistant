package com.personalassistant.companion;

/** Only consecutive monitoring frames may contribute to one wake decision. */
public final class WakeStreamGate {
    private final WakeDetector detector;
    private boolean discontinuous;
    public WakeStreamGate(WakeDetector detector){this.detector=detector;}
    /** Audio existed while monitoring was suppressed; discard stale context on resume. */
    public void pause(){discontinuous=true;}
    public boolean accept(short[] frame,int length){
        if(discontinuous){detector.reset();discontinuous=false;}
        return detector.accept(frame,length);
    }
}
