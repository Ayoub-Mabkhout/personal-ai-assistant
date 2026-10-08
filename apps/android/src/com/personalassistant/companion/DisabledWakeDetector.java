package com.personalassistant.companion;
/** Button voice does not load a neural runtime or wait for wake-model warm-up. */
final class DisabledWakeDetector implements WakeDetector {
    public boolean accept(short[] pcm,int length){return false;}
    public boolean available(){return false;}
    public String name(){return "Wake disabled";}
    public void reset(){}
}
