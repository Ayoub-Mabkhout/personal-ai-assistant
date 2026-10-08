import com.personalassistant.companion.PcmRingBuffer;
import com.personalassistant.companion.TemplateWakeDetector;
import com.personalassistant.companion.BufferedCapture;
import javax.sound.sampled.*;
import java.nio.*;
import java.nio.file.*;
import java.util.*;

/** Exercises the same acoustic detector and pre-roll class compiled into Android. */
public final class VoiceReplay {
    static short[] wav(Path file) throws Exception {
        try(AudioInputStream in=AudioSystem.getAudioInputStream(file.toFile())){
            AudioFormat f=in.getFormat();
            if(f.getSampleRate()!=16000||f.getChannels()!=1||f.getSampleSizeInBits()!=16||f.isBigEndian())throw new IllegalArgumentException("mono PCM16 16k required");
            byte[] bytes=in.readAllBytes();short[] pcm=new short[bytes.length/2];ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(pcm);return pcm;
        }
    }
    static void buffering(){
        // Producer never waits for network. Trigger snapshot plus each later frame
        // is retained until transport can drain it, preserving exact sample order.
        for(int delay:new int[]{0,16000,48000,160000}){
            PcmRingBuffer ring=new PcmRingBuffer(32000);short[] source=new short[256000];
            BufferedCapture actual=new BufferedCapture(32000);
            for(int i=0;i<source.length;i++)source[i]=(short)((i*31)^ (i>>>4));
            List<short[]> retained=new ArrayList<>();int trigger=64000,received=0;
            for(int cursor=0;cursor<source.length;cursor+=320){
                short[] frame=Arrays.copyOfRange(source,cursor,cursor+320);ring.append(frame,frame.length);
                actual.ingest(frame,frame.length);
                if(cursor+320==trigger){retained.add(ring.snapshot());actual.begin(true);}
                else if(cursor+320>trigger)retained.add(frame);
                // Simulate a disconnected socket: no drain until delay has passed.
                if(cursor+320>=trigger+delay){
                    for(short[] chunk:retained){for(short sample:chunk){if(sample!=source[trigger-32000+received])throw new AssertionError("gap or duplicate");received++;}}
                    retained.clear();
                }
            }
            if(received!=source.length-trigger+32000)throw new AssertionError("first/trailing samples lost");
            if(!Arrays.equals(actual.finish(),Arrays.copyOfRange(source,trigger-32000,source.length)))throw new AssertionError("Android capture gap or duplicate");
        }
        System.err.println("Buffer replay: exact ordered samples at 0,1,3,10 second connection delays.");
    }
    public static void main(String[] args)throws Exception{
        buffering();if(args.length==1&&args[0].equals("--buffer-only"))return;
        List<short[]> templates=new ArrayList<>();
        try(var paths=Files.list(Path.of(args[0]))){for(Path p:paths.filter(x->x.toString().endsWith(".wav")).sorted().toList())templates.add(wav(p));}
        double threshold=args.length>2?Double.parseDouble(args[2]):.45;
        try(var paths=Files.walk(Path.of(args[1]))){
            for(Path p:paths.filter(x->x.toString().endsWith(".wav")&&!x.toString().contains("wake-model")).sorted().toList()){
                TemplateWakeDetector detector=new TemplateWakeDetector();for(short[] t:templates)detector.add(t);detector.threshold(threshold);
                short[] clip=wav(p);short[] data=new short[clip.length+16000+9600];System.arraycopy(clip,0,data,16000,clip.length);
                PcmRingBuffer history=new PcmRingBuffer(32000);double best=Double.POSITIVE_INFINITY;int first=-1;
                long started=System.nanoTime();
                for(int cursor=0;cursor<data.length;cursor+=320){short[] frame=Arrays.copyOfRange(data,cursor,Math.min(data.length,cursor+320));history.append(frame,frame.length);
                    if(detector.accept(frame,frame.length)&&first<0)first=cursor+frame.length-16000;
                    best=Math.min(best,detector.lastScore());
                }
                System.out.printf(Locale.ROOT,"%s\t%.8f\t%d\t%.3f%n",Path.of(args[1]).relativize(p),best,first,(System.nanoTime()-started)/1e9);
            }
        }
    }
}
