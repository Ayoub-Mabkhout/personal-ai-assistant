package com.personalassistant.companion;

/** Conservative energy gate for capture endpointing, independent of the wake detector. */
final class CaptureSpeechGate {
    private CaptureSpeechGate(){}
    static boolean speech(double rms,double noiseFloor){return rms>Math.max(80,noiseFloor*2.0);}
}
