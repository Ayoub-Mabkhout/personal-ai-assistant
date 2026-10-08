package com.personalassistant.companion;

import android.content.Context;
import java.io.*;
import java.time.Instant;
import org.json.*;

/** Backend acknowledgements for the Activity page, merged by stable task ID. */
final class VoiceHistory {
    static synchronized boolean record(Context context,JSONObject event)throws Exception {
        String identifier=event.optString("task_id","");if(identifier.isEmpty())return false;
        if(!identifier.matches("[A-Za-z0-9_-]{1,128}"))throw new IllegalArgumentException("Invalid voice task ID");
        File directory=new File(context.getFilesDir(),"voice-receipts");if(!directory.isDirectory()&&!directory.mkdirs())throw new IOException("Voice history storage unavailable");
        File target=new File(directory,identifier+".json"),temporary=new File(directory,identifier+".part");JSONObject previous=target.isFile()?new JSONObject(VoiceOutbox.read(target)):new JSONObject();
        String text=event.has("text")?event.optString("text",""):previous.optString("text",""),reply=event.has("reply")?event.optString("reply",""):previous.optString("reply",""),status=event.has("status")?event.optString("status",""):previous.optString("status","");
        text=bounded(text);reply=bounded(reply);status=bounded(status);
        if(target.isFile()&&previous.optString("text","").equals(text)&&previous.optString("reply","").equals(reply)&&previous.optString("status","").equals(status))return false;
        String now=Instant.now().toString();JSONObject receipt=new JSONObject().put("id",identifier).put("task_id",identifier).put("text",text).put("reply",reply).put("status",status).put("source","live_voice").put("created_at",previous.optString("created_at",now)).put("updated_at",now);
        try(FileOutputStream output=new FileOutputStream(temporary)){output.write(receipt.toString().getBytes("UTF-8"));output.getFD().sync();}
        java.nio.file.Files.move(temporary.toPath(),target.toPath(),java.nio.file.StandardCopyOption.ATOMIC_MOVE,java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        context.sendBroadcast(new android.content.Intent("com.personalassistant.companion.VOICE_STATE").setPackage(context.getPackageName()));return true;
    }
    private static String bounded(String text){return text.length()>8000?text.substring(0,8000):text;}
}
