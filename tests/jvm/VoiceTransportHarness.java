package com.personalassistant.companion;

import android.content.Context;
import java.io.ByteArrayOutputStream;
import java.lang.reflect.Field;
import java.util.*;
import java.util.concurrent.BlockingQueue;
import org.json.*;

/** Actual production buffer/socket code, no network, microphone, Android framework or paid API. */
public final class VoiceTransportHarness {
    static final class Events implements VoiceSocket.Listener {
        int failures; boolean acknowledged;
        public void event(JSONObject event) {}
        public void closed(String message, boolean ack) {failures++; acknowledged=ack;}
    }
    static short[] samples(int offset,int count) {
        short[] data=new short[count];for(int i=0;i<count;i++)data[i]=(short)(((offset+i)*31)^((offset+i)>>>4));return data;
    }
    static void check(boolean value,String message) {if(!value)throw new AssertionError(message);}
    @SuppressWarnings("unchecked") static BlockingQueue<String> queue(VoiceSocket socket)throws Exception {
        Field field=VoiceSocket.class.getDeclaredField("output");field.setAccessible(true);return (BlockingQueue<String>)field.get(socket);
    }
    static byte[] drain(VoiceSocket socket)throws Exception {
        ByteArrayOutputStream pcm=new ByteArrayOutputStream();String frame;
        while((frame=queue(socket).poll())!=null){JSONObject json=new JSONObject(frame);if("audio".equals(json.optString("type")))pcm.write(android.util.Base64.decode(json.getString("audio"),0));}
        return pcm.toByteArray();
    }
    static void exact(byte[] actual,short[] expected,String message) {
        check(actual.length==expected.length*2,message+" length");
        for(int i=0;i<expected.length;i++)check(expected[i]==(short)((actual[2*i]&255)|(actual[2*i+1]<<8)),message+" sample "+i);
    }
    static JSONObject backlog(int seconds)throws Exception {
        Events events=new Events();VoiceSocket socket=new VoiceSocket(new Context(),events);BufferedCapture backup=new BufferedCapture(32000);
        short[] prefix=samples(0,32000);backup.ingest(prefix,prefix.length);backup.begin(true);check(socket.audio(prefix,prefix.length),"Prefix rejected");
        int firstFailure=-1;for(int i=0;i<seconds*50;i++){short[] frame=samples(32000+i*320,320);backup.ingest(frame,320);if(!socket.audio(frame,320)&&firstFailure<0)firstFailure=i;}
        byte[] wire=drain(socket);short[] expected=samples(0,32000+seconds*16000);check(Arrays.equals(backup.finish(),expected),"Unacknowledged fallback backup lost PCM");
        if(firstFailure<0)exact(wire,expected,"Delayed-ready backlog");
        JSONObject result=new JSONObject().put("delay_seconds",seconds).put("audio_preserved",firstFailure<0).put("first_failure_seconds",firstFailure<0?JSONObject.NULL:(firstFailure+1)*.02)
            .put("closed_events",events.failures).put("acknowledged_at_failure",events.acknowledged).put("fallback_exact",true).put("queued_pcm_bytes",wire.length);
        socket.disconnect();check(!socket.audio(new short[]{1},1),"Closed socket accepted audio");return result;
    }
    static JSONObject capture() {
        for(int delay:new int[]{0,16000,48000,80000,160000}){
            BufferedCapture capture=new BufferedCapture(32000);short[] source=samples(0,256000);int trigger=64000;
            for(int cursor=0;cursor<source.length;cursor+=320){short[] frame=Arrays.copyOfRange(source,cursor,cursor+320);capture.ingest(frame,320);if(cursor+320==trigger)capture.begin(true);if(cursor+320==trigger+delay)check(Arrays.equals(capture.snapshot(),Arrays.copyOfRange(source,trigger-32000,cursor+320)),"Capture snapshot mismatch");}
            check(Arrays.equals(capture.finish(),Arrays.copyOfRange(source,trigger-32000,source.length)),"Capture continuation mismatch");
        }
        BufferedCapture cleared=new BufferedCapture(32000);cleared.ingest(samples(0,32000),32000);cleared.cancel();cleared.ingest(new short[]{7,8,9},3);cleared.begin(true);check(Arrays.equals(cleared.finish(),new short[]{7,8,9}),"Old playback leaked into prefix");
        return new JSONObject().put("delays_seconds",new JSONArray(new int[]{0,1,3,5,10})).put("exact_order",true).put("cancel_clears_stale_prefix",true).put("pre_trigger_retention_seconds",2);
    }
    static JSONObject partialStop()throws Exception {
        Events events=new Events();VoiceSocket socket=new VoiceSocket(new Context(),events);short[] source=samples(0,21731);int cursor=0,index=0;int[] fragments={1,319,320,997,4097,7};
        while(cursor<source.length){int count=Math.min(fragments[index++%fragments.length],source.length-cursor);check(socket.audio(Arrays.copyOfRange(source,cursor,cursor+count),count),"Fragmented input rejected");cursor+=count;}
        check(Math.abs(socket.bufferedAudioSeconds()-source.length/16000.0)<1e-9,"Start backlog credit omitted partial PCM");
        Field ready=VoiceSocket.class.getDeclaredField("ready");ready.setAccessible(true);ready.set(socket,true);socket.stop();socket.stop();check(!socket.audio(new short[]{55},1),"Audio accepted after stop queued");
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();boolean stop=false;int audioPackets=0;String frame;java.lang.reflect.Method consumed=VoiceSocket.class.getDeclaredMethod("consumed",String.class);consumed.setAccessible(true);
        while((frame=queue(socket).poll())!=null){JSONObject json=new JSONObject(frame);if("stop".equals(json.getString("type"))){check(!stop,"Duplicate stop");stop=true;}else{check(!stop,"PCM after stop");byte[] pcm=android.util.Base64.decode(json.getString("audio"),0);check(pcm.length<=3200,"Audio packet exceeds100ms");bytes.write(pcm);audioPackets++;consumed.invoke(socket,frame);}}
        check(stop,"Stop marker missing");exact(bytes.toByteArray(),source,"Partial tail and stop order");check(socket.bufferedAudioSeconds()==0,"Consumed PCM still counted in queue credit");check(events.failures==0,"Stop flush failed");socket.disconnect();
        VoiceSocket unready=new VoiceSocket(new Context(),new Events());unready.audio(source,source.length);unready.stop();check(queue(unready).isEmpty()&&!unready.audio(source,1),"Preack stop retained/livequeued audio");
        return new JSONObject().put("samples",source.length).put("packets",audioPackets).put("fragmented_pcm_exact",true).put("partial_tail_before_stop",true).put("duplicate_stop_idempotent",true).put("start_credit_counts_partial",true).put("preack_stop_disconnects",true);
    }
    public static void main(String[] args)throws Exception {
        JSONArray backlogs=new JSONArray();for(int seconds:new int[]{5,10,20,30,60}){JSONObject row=backlog(seconds);check(row.getBoolean("audio_preserved")== (seconds<60),"Queue delay regression "+seconds);if(seconds==60)check(row.getDouble("first_failure_seconds")==58.02,"PCM cap no longer60seconds including prefix");backlogs.put(row);}
        System.out.println(new JSONObject().put("capture",capture()).put("socket_backlogs",backlogs).put("stop_order",partialStop()).put("network_used",false));
    }
}
