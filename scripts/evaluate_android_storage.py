"""Check actual Android queue storage against a controlled blocked transport.

No external network, Android service, paired phone or paid API is used. Minimal
framework shims and disposable files keep tests outside runtime state.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def evaluate(root, json_jar, baseline=False):
    with tempfile.TemporaryDirectory(prefix="assistant-storage-") as folder:
        work = Path(folder)
        shims = {
            "android/content/SharedPreferences.java": """package android.content;import java.util.*;public class SharedPreferences {final Map<String,Object> data=Collections.synchronizedMap(new HashMap<>());public String getString(String k,String d){Object v=data.get(k);return v==null?d:v.toString();}public long getLong(String k,long d){Object v=data.get(k);return v==null?d:((Number)v).longValue();}public boolean getBoolean(String k,boolean d){Object v=data.get(k);return v==null?d:(Boolean)v;}public Editor edit(){return new Editor();}public class Editor {Map<String,Object> pending=new HashMap<>();public Editor putString(String k,String v){pending.put(k,v);return this;}public Editor putLong(String k,long v){pending.put(k,v);return this;}public Editor putBoolean(String k,boolean v){pending.put(k,v);return this;}public Editor remove(String k){pending.put(k,null);return this;}public boolean commit(){synchronized(data){for(Map.Entry<String,Object> e:pending.entrySet())if(e.getValue()==null)data.remove(e.getKey());else data.put(e.getKey(),e.getValue());}return true;}public void apply(){commit();}}}""",
            "android/content/Context.java": """package android.content;import java.io.*;public class Context {public static final String CONNECTIVITY_SERVICE=\"connectivity\";final SharedPreferences prefs=new SharedPreferences();final File files;public Context(File f){files=f;f.mkdirs();}public SharedPreferences getSharedPreferences(String n,int m){return prefs;}public File getFilesDir(){return files;}public Object getSystemService(String n){return new android.net.ConnectivityManager();}public String getPackageName(){return \"fixture\";}public void sendBroadcast(Intent i){}}""",
            "android/content/Intent.java": "package android.content;public class Intent {public Intent(String s){}public Intent setPackage(String s){return this;}}",
            "android/util/Base64.java": "package android.util;public class Base64 {public static final int NO_WRAP=2;public static String encodeToString(byte[] data,int flags){return java.util.Base64.getEncoder().encodeToString(data);}}",
            "android/util/AtomicFile.java": """package android.util;import java.io.*;public class AtomicFile {final File f;public AtomicFile(File f){this.f=f;}public byte[] readFully()throws IOException{return java.nio.file.Files.readAllBytes(f.toPath());}public FileOutputStream startWrite()throws IOException{return new FileOutputStream(f);}public void finishWrite(FileOutputStream out)throws IOException{out.close();}public void failWrite(FileOutputStream out){try{out.close();}catch(IOException ignored){}}}""",
            "android/net/ConnectivityManager.java": "package android.net;public class ConnectivityManager {public Object getActiveNetwork(){return null;}public NetworkCapabilities getNetworkCapabilities(Object n){return null;}}",
            "android/net/NetworkCapabilities.java": "package android.net;public class NetworkCapabilities {public static final int NET_CAPABILITY_INTERNET=1,NET_CAPABILITY_VALIDATED=2;public boolean hasCapability(int n){return false;}}",
            "com/personalassistant/companion/ShoppingWidget.java": "package com.personalassistant.companion;class ShoppingWidget {static void update(android.content.Context c){}}",
            "com/personalassistant/companion/SyncJob.java": "package com.personalassistant.companion;class SyncJob {static java.util.concurrent.Executor executor=r->{};static void schedule(android.content.Context c,boolean p){}}",
        }
        for name, body in shims.items():
            target = work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
        app = root / "apps/android/src/com/personalassistant/companion"
        sources = [app / "Cloud.java", app / "DaylightTheme.java", app / "VoiceOutbox.java", app / "VoiceHistory.java", app / "VoiceChat.java", root / "tests/jvm/OfflineQueueHarness.java", *[work / name for name in shims]]
        subprocess.run(["javac", "-cp", str(json_jar), "-d", str(work), *map(str, sources)], check=True, capture_output=True, text=True)
        arguments = (["baseline"] if baseline else []) + [str(work / "files")]
        run = subprocess.run(["java", "-cp", str(work) + os.pathsep + str(json_jar), "com.personalassistant.companion.OfflineQueueHarness", *arguments], check=True, capture_output=True, text=True)
        return json.loads(run.stdout)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-jar", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    result = evaluate(Path(__file__).resolve().parents[1], args.json_jar.resolve(), args.baseline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
