package com.personalassistant.companion;
/** Local interchangeable detector, microphone owned exclusively by VoiceService. */
public interface WakeDetector {
    boolean accept(short[] frame,int length);
    boolean available();
    String name();
    /** Clear temporal audio/history after skipped capture, retaining loaded model weights. */
    void reset();
    default void close(){}
}
