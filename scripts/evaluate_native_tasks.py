"""Exercise the actual native follow-up outbox with a controlled fake transport."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def evaluate(root, json_jar):
    shims = {
        'android/content/SharedPreferences.java': '''package android.content;import java.util.*;public class SharedPreferences {final Map<String,Object> data=new HashMap<>();public synchronized String getString(String k,String d){Object v=data.get(k);return v==null?d:v.toString();}public long getLong(String k,long d){Object v=data.get(k);return v==null?d:((Number)v).longValue();}public Editor edit(){return new Editor();}public class Editor {Map<String,Object> pending=new HashMap<>();public Editor putString(String k,String v){pending.put(k,v);return this;}public Editor putLong(String k,long v){pending.put(k,v);return this;}public boolean commit(){synchronized(SharedPreferences.this){data.putAll(pending);}return true;}}}''',
        'android/content/Context.java': '''package android.content;public class Context {public final SharedPreferences prefs=new SharedPreferences();public String getPackageName(){return "test";}public void sendBroadcast(Intent i){}}''',
        'android/content/Intent.java': '''package android.content;public class Intent {public Intent(String action){}public Intent setPackage(String name){return this;}}''',
        'com/personalassistant/companion/TaskSyncJob.java': '''package com.personalassistant.companion;class TaskSyncJob {static void schedule(android.content.Context c,boolean p){}}''',
        'com/personalassistant/companion/NativeNotifications.java': '''package com.personalassistant.companion;class NativeNotifications {static void sync(android.content.Context c){}}''',
        'com/personalassistant/companion/NotificationActions.java': '''package com.personalassistant.companion;class NotificationActions {static void flush(android.content.Context c){}}''',
        'com/personalassistant/companion/PushRegistration.java': '''package com.personalassistant.companion;class PushRegistration {static void sync(android.content.Context c){}}''',
        'com/personalassistant/companion/Cloud.java': '''package com.personalassistant.companion;import android.content.*;import java.util.*;import java.util.concurrent.*;import org.json.*;class Cloud {static boolean block,dropAck;static String rejectId="";static int executions;static CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);static Map<String,JSONObject> received=new HashMap<>();static SharedPreferences prefs(Context c){return c.prefs;}static Object call(Context c,String path,JSONObject body,boolean auth)throws Exception {if(block){block=false;entered.countDown();if(!release.await(2,TimeUnit.SECONDS))throw new java.io.IOException("blocked");}String id=body.getString("id");if(id.equals(rejectId))throw new Exception("Server rejected change (422)");JSONObject result=received.get(id);if(result==null){executions++;result=new JSONObject().put("id","accepted-"+id).put("state","queued");received.put(id,result);}if(dropAck){dropAck=false;throw new java.io.IOException("lost acknowledgement");}return result;}}''',
    }
    with tempfile.TemporaryDirectory(prefix='assistant-native-tasks-') as directory:
        work = Path(directory)
        sources = []
        for name, content in shims.items():
            file = work/name
            file.parent.mkdir(parents=True,exist_ok=True)
            file.write_text(content)
            sources.append(file)
        sources += [root/'apps/android/src/com/personalassistant/companion/NativeTasks.java',
                    root/'tests/jvm/NativeTaskQueueHarness.java']
        compile = subprocess.run(['javac','-cp',str(json_jar),'-d',str(work),*map(str,sources)],capture_output=True,text=True)
        if compile.returncode:
            raise RuntimeError(compile.stderr)
        result = subprocess.run(['java','-cp',str(work)+os.pathsep+str(json_jar),
                                 'com.personalassistant.companion.NativeTaskQueueHarness'],check=True,capture_output=True,text=True)
        return json.loads(result.stdout)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json-jar',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args = parser.parse_args()
    result = evaluate(Path(__file__).resolve().parents[1],args.json_jar.resolve())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
