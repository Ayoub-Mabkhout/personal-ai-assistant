import com.personalassistant.companion.*;
import java.util.*;

/** Real stream gate must reject a wake assembled from unrelated capture turns. */
public final class WakeBoundaryReplay {
    static final class PrefixDetector implements WakeDetector {
        boolean prefix;int resets;
        public boolean accept(short[] frame,int length){boolean found=false;for(int i=0;i<length;i++){if(prefix&&frame[i]==200)found=true;prefix=frame[i]==100;}return found;}
        public void reset(){prefix=false;resets++;}
        public boolean available(){return true;}
        public String name(){return "Deterministic split-prefix test";}
    }
    public static void check(){
        PrefixDetector unsafe=new PrefixDetector();unsafe.accept(new short[]{100},1);
        if(!unsafe.accept(new short[]{200},1))throw new AssertionError("Control must expose the stale-prefix failure");
        PrefixDetector safe=new PrefixDetector();WakeStreamGate gate=new WakeStreamGate(safe);
        if(gate.accept(new short[]{100},1))throw new AssertionError("Prefix alone triggered");
        gate.pause();gate.pause(); // Capture/TTS/transport audio is not fed to wake recognition.
        if(gate.accept(new short[]{200},1))throw new AssertionError("Wake spliced across skipped audio");
        if(safe.resets!=1)throw new AssertionError("A gap must reset exactly once on resume");
        if(!gate.accept(new short[]{100,200},2))throw new AssertionError("Contiguous wake no longer works");
        if(safe.resets!=1)throw new AssertionError("Continuous input unexpectedly reset");
        gate.pause();gate.accept(new short[]{100,200},2);
        if(safe.resets!=2)throw new AssertionError("Second discontinuity not reset");

        short[] phrase=new short[16000];for(int i=0;i<phrase.length;i++)phrase[i]=(short)(Math.sin(i*(.03+i*.000002))*10000);
        TemplateWakeDetector actual=new TemplateWakeDetector(),fresh=new TemplateWakeDetector();
        actual.add(phrase);fresh.add(phrase);actual.threshold(.01);fresh.threshold(.01);
        WakeStreamGate templateGate=new WakeStreamGate(actual);
        for(int i=0;i<8000;i+=320)templateGate.accept(Arrays.copyOfRange(phrase,i,i+320),320);
        templateGate.pause();
        for(int i=8000;i<phrase.length;i+=320){short[] frame=Arrays.copyOfRange(phrase,i,i+320);if(templateGate.accept(frame,frame.length)!=fresh.accept(frame,frame.length))throw new AssertionError("Acoustic suffix differs from fresh stream");}
        if(Double.compare(actual.lastScore(),fresh.lastScore())!=0||!actual.available())throw new AssertionError("Template reset failed or discarded model");
        System.out.println("Wake stream boundary: stale split prefix rejected, continuous phrase accepted, reset once, acoustic suffix matches fresh context.");
    }
    public static void main(String[] args){check();}
}
