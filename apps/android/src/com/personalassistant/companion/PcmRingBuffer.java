package com.personalassistant.companion;

/** Single producer pre-roll; snapshots are independent and ordered oldest first. */
public final class PcmRingBuffer {
    private final short[] samples; private int next, size; private long count;
    public PcmRingBuffer(int capacity){if(capacity<1)throw new IllegalArgumentException("capacity");samples=new short[capacity];}
    public void append(short[] frame,int length){if(length<0||length>frame.length)throw new IllegalArgumentException("length");for(int i=0;i<length;i++){samples[next]=frame[i];next=(next+1)%samples.length;if(size<samples.length)size++;count++;}}
    public short[] snapshot(){short[] out=new short[size];int start=(next-size+samples.length)%samples.length;for(int i=0;i<size;i++)out[i]=samples[(start+i)%samples.length];return out;}
    public long count(){return count;}
    public void clear(){size=0;next=0;}
}
