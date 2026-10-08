package com.personalassistant.companion;
import java.io.ByteArrayOutputStream;

/** Recorder-thread owned: ingest frame once, then begin after a detector trigger. */
public final class BufferedCapture {
    private final PcmRingBuffer ring;private ByteArrayOutputStream command;
    public BufferedCapture(int preRollSamples){ring=new PcmRingBuffer(preRollSamples);}
    public void ingest(short[] frame,int length){ring.append(frame,length);if(command!=null)write(frame,length);}
    public void begin(boolean preRoll){if(command!=null)throw new IllegalStateException("Capture already active");command=new ByteArrayOutputStream();if(preRoll){short[] prefix=ring.snapshot();write(prefix,prefix.length);}}
    private void write(short[] pcm,int length){for(int i=0;i<length;i++){command.write(pcm[i]&255);command.write((pcm[i]>>>8)&255);}}
    public int size(){return command==null?0:command.size()/2;}
    public boolean active(){return command!=null;}
    public short[] finish(){if(command==null)throw new IllegalStateException("No capture");byte[] raw=command.toByteArray();command=null;short[] pcm=new short[raw.length/2];for(int i=0;i<pcm.length;i++)pcm[i]=(short)((raw[2*i]&255)|(raw[2*i+1]<<8));return pcm;}
    public short[] snapshot(){if(command==null)return new short[0];byte[] raw=command.toByteArray();short[] pcm=new short[raw.length/2];for(int i=0;i<pcm.length;i++)pcm[i]=(short)((raw[2*i]&255)|(raw[2*i+1]<<8));return pcm;}
    public void cancel(){command=null;ring.clear();}
}
