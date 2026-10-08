package com.personalassistant.companion;

import java.util.*;

/** Experimental local acoustic template matcher. No microphone/network ownership. */
public final class TemplateWakeDetector implements WakeDetector {
    public static final int RATE=16000, WINDOW=400, HOP=160, COEFFICIENTS=12;
    private final List<float[][]> templates=new ArrayList<>();
    private final short[] analysis=new short[WINDOW];private int analysisSize,hop;
    private final ArrayDeque<float[]> featureHistory=new ArrayDeque<>();private long sampleCount;
    private int untilCheck=1600; private long cooldown; private double threshold=0.45,lastScore=Double.POSITIVE_INFINITY;
    public double lastScore(){return lastScore;}
    public void add(short[] pcm){float[][] features=features(pcm);if(features.length<15||features.length>190)throw new IllegalArgumentException("Wake template must be 0.2–1.9 seconds");templates.add(features);}
    public void threshold(double value){if(value<=0||value>2)throw new IllegalArgumentException("threshold");threshold=value;}
    public boolean available(){return !templates.isEmpty();}
    public String name(){return "Experimental acoustic template";}
    public void reset(){Arrays.fill(analysis,(short)0);analysisSize=hop=0;featureHistory.clear();sampleCount=cooldown=0;untilCheck=1600;lastScore=Double.POSITIVE_INFINITY;}
    public boolean accept(short[] frame,int length){for(int i=0;i<length;i++){if(analysisSize<WINDOW)analysis[analysisSize++]=frame[i];else{System.arraycopy(analysis,1,analysis,0,WINDOW-1);analysis[WINDOW-1]=frame[i];}if(analysisSize==WINDOW&&++hop>=HOP){hop=0;featureHistory.add(features(analysis)[0]);if(featureHistory.size()>198)featureHistory.removeFirst();}}sampleCount+=length;untilCheck-=length;if(untilCheck>0||!available())return false;untilCheck=1600;if(sampleCount<cooldown)return false;lastScore=scoreFeatures(featureHistory.toArray(new float[0][]));if(lastScore<threshold){cooldown=sampleCount+RATE*3;return true;}return false;}
    public double score(short[] pcm){return scoreFeatures(features(pcm));}
    public double scoreFeatures(float[][] observed){double best=Double.POSITIVE_INFINITY;for(float[][] template:templates)best=Math.min(best,distance(template,observed));return best;}
    /** Subsequence DTW ending near the newest frame, bounded 0.6–1.7x duration. */
    public static double distance(float[][] template,float[][] observed){
        if(observed.length<template.length*0.6)return Double.POSITIVE_INFINITY;
        double best=Double.POSITIVE_INFINITY;
        for(int end=observed.length;end>=Math.max(1,observed.length-8);end-=4){
            int first=Math.max(0,end-(int)(template.length*1.7));double[] prev=new double[end-first+1];int[] lengths=new int[prev.length];Arrays.fill(prev,0);
            for(int i=0;i<template.length;i++){double[] curr=new double[prev.length];int[] nextLengths=new int[prev.length];Arrays.fill(curr,Double.POSITIVE_INFINITY);
                for(int j=1;j<curr.length;j++){double cost=0;for(int k=0;k<COEFFICIENTS;k++){double delta=template[i][k]-observed[first+j-1][k];cost+=delta*delta;}cost=Math.sqrt(cost/COEFFICIENTS);
                    int from=j-1;double minimum=prev[from];int steps=lengths[from];if(prev[j]<minimum){minimum=prev[j];steps=lengths[j];}if(curr[j-1]<minimum){minimum=curr[j-1];steps=nextLengths[j-1];}curr[j]=cost+minimum;nextLengths[j]=steps+1;
                }prev=curr;lengths=nextLengths;
            }
            int len=lengths[prev.length-1];if(len>=template.length&&len<=template.length*2.7)best=Math.min(best,prev[prev.length-1]/Math.max(1,len));
        }return best;
    }
    /** FFT log-Mel cepstra normalized per frame, shared by phone and replay harness. */
    public static float[][] features(short[] pcm){
        int count=pcm.length<WINDOW?0:(pcm.length-WINDOW)/HOP+1;float[][] result=new float[count][COEFFICIENTS];
        int[] edges=new int[26];for(int i=0;i<26;i++){double mel=2595*Math.log10(1+7600.0/700)*i/25;edges[i]=(int)Math.round((700*(Math.pow(10,mel/2595)-1))*512/RATE);}
        for(int f=0;f<count;f++){double[] real=new double[512],imag=new double[512];int offset=f*HOP;for(int i=0;i<WINDOW;i++){double x=pcm[offset+i]/32768.0-(i==0?0:0.97*pcm[offset+i-1]/32768.0);real[i]=x*(0.54-0.46*Math.cos(2*Math.PI*i/(WINDOW-1)));}fft(real,imag);
            double[] logs=new double[24];double average=0;for(int b=0;b<24;b++){double sum=0;for(int k=edges[b];k<edges[b+2];k++){double weight=k<edges[b+1]?(k-edges[b])/(double)Math.max(1,edges[b+1]-edges[b]):(edges[b+2]-k)/(double)Math.max(1,edges[b+2]-edges[b+1]);sum+=(real[k]*real[k]+imag[k]*imag[k])*weight;}logs[b]=Math.log(Math.max(1e-9,sum));average+=logs[b]/24;}
            double norm=0;for(int c=1;c<=COEFFICIENTS;c++){double value=0;for(int b=0;b<24;b++)value+=(logs[b]-average)*Math.cos(Math.PI*c*(b+0.5)/24);result[f][c-1]=(float)value;norm+=value*value;}norm=Math.sqrt(norm)+1e-8;for(int c=0;c<COEFFICIENTS;c++)result[f][c]/=norm;
        }return result;
    }
    static void fft(double[] re,double[] im){int n=re.length;for(int i=1,j=0;i<n;i++){int bit=n>>1;for(; (j&bit)!=0;bit>>=1)j^=bit;j^=bit;if(i<j){double v=re[i];re[i]=re[j];re[j]=v;}}
        for(int len=2;len<=n;len*=2){double angle=-2*Math.PI/len;for(int start=0;start<n;start+=len){double wr=1,wi=0;for(int j=0;j<len/2;j++){int a=start+j,b=a+len/2;double tr=wr*re[b]-wi*im[b],ti=wr*im[b]+wi*re[b];re[b]=re[a]-tr;im[b]=im[a]-ti;re[a]+=tr;im[a]+=ti;double next=wr*Math.cos(angle)-wi*Math.sin(angle);wi=wr*Math.sin(angle)+wi*Math.cos(angle);wr=next;}}}
    }
}
