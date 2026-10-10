"""Companion file drops: the real FileDrops, FileDropJob and NativeNotifications compiled with javac against the minimal
framework shims below and driven through tests/jvm/FileDropsHarness.java. The relay, MediaStore and the HTTPS download are
in memory; no network, phone or paid service is used. Skipped where no JDK is installed."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPANION = ROOT / 'apps/android/src/com/personalassistant/companion'
SOURCES = [COMPANION / name for name in ('FileDrops.java', 'FileDropJob.java', 'NativeNotifications.java')] + [ROOT / 'tests/jvm/FileDropsHarness.java']
MAIN = 'com.personalassistant.companion.FileDropsHarness'
APK = 'application/vnd.android.package-archive'

# Only what the three classes touch. Static state is shared, so the job (a Context) and the harness see one phone.
SHIMS = {
    'android/content/SharedPreferences.java': r'''package android.content;import java.util.*;import java.util.function.Consumer;
public class SharedPreferences {public static Consumer<Map<String,Object>> hook;final Map<String,Object> data=Collections.synchronizedMap(new HashMap<String,Object>());
public String getString(String k,String d){Object v=data.get(k);return v==null?d:v.toString();}public long getLong(String k,long d){Object v=data.get(k);return v==null?d:((Number)v).longValue();}
public boolean getBoolean(String k,boolean d){Object v=data.get(k);return v==null?d:(Boolean)v;}@SuppressWarnings("unchecked") public Set<String> getStringSet(String k,Set<String> d){Object v=data.get(k);return v==null?d:new HashSet<String>((Set<String>)v);}
public Editor edit(){return new Editor();}
public class Editor {final Map<String,Object> pending=new HashMap<String,Object>();public Editor putString(String k,String v){pending.put(k,v);return this;}public Editor putLong(String k,long v){pending.put(k,v);return this;}
public Editor putBoolean(String k,boolean v){pending.put(k,v);return this;}public Editor putStringSet(String k,Set<String> v){pending.put(k,new HashSet<String>(v));return this;}public Editor remove(String k){pending.put(k,null);return this;}
public boolean commit(){synchronized(data){for(Map.Entry<String,Object> e:pending.entrySet())if(e.getValue()==null)data.remove(e.getKey());else data.put(e.getKey(),e.getValue());}Consumer<Map<String,Object>> h=hook;if(h!=null)h.accept(pending);return true;}}}''',
    'android/content/Context.java': r'''package android.content;import java.io.File;
public class Context {public static final String JOB_SCHEDULER_SERVICE="jobscheduler",NOTIFICATION_SERVICE="notification";public static File root;
public static final SharedPreferences prefs=new SharedPreferences();public static final ContentResolver resolver=new ContentResolver();
public static final android.app.NotificationManager notifications=new android.app.NotificationManager();public static final android.app.job.JobScheduler scheduler=new android.app.job.JobScheduler();
public Object getSystemService(String name){return JOB_SCHEDULER_SERVICE.equals(name)?scheduler:notifications;}public ContentResolver getContentResolver(){return resolver;}
public File getCacheDir(){File f=new File(root,"cache");f.mkdirs();return f;}public File getExternalFilesDir(String type){File f=new File(root,"external/"+type);f.mkdirs();return f;}public String getPackageName(){return "fixture";}}''',
    'android/content/ContentValues.java': r'''package android.content;import java.util.*;
public class ContentValues {public final Map<String,Object> values=new HashMap<String,Object>();public void put(String k,String v){values.put(k,v);}public void put(String k,Integer v){values.put(k,v);}public Object get(String k){return values.get(k);}public void clear(){values.clear();}}''',
    # MediaStore adds the extension of the declared type when the name's extension names another type.
    'android/content/ContentResolver.java': r'''package android.content;import android.database.Cursor;import android.net.Uri;import android.webkit.MimeTypeMap;import java.io.*;import java.util.*;
public class ContentResolver {public final Map<String,ContentValues> rows=new HashMap<String,ContentValues>();public final Map<String,ByteArrayOutputStream> bytes=new HashMap<String,ByteArrayOutputStream>();public String lastName;int next;
public synchronized Uri insert(Uri collection,ContentValues values){String name=(String)values.get("_display_name"),mime=(String)values.get("mime_type");int dot=name.lastIndexOf('.');String ext=dot>0?name.substring(dot+1).toLowerCase():"";
MimeTypeMap map=MimeTypeMap.getSingleton();String fromExt=map.getMimeTypeFromExtension(ext),extFromMime=map.getExtensionFromMimeType(mime);
if(!"application/octet-stream".equals(mime)&&!mime.equals(fromExt)&&extFromMime!=null&&!extFromMime.equals(ext))name=name+"."+extFromMime;
ContentValues row=new ContentValues();row.values.putAll(values.values);row.put("_display_name",name);Uri uri=Uri.parse(collection+"/"+(++next));rows.put(uri.toString(),row);lastName=name;return uri;}
public synchronized OutputStream openOutputStream(Uri uri){ByteArrayOutputStream out=new ByteArrayOutputStream();bytes.put(uri.toString(),out);return out;}
public synchronized int update(Uri uri,ContentValues values,String where,String[] args){rows.get(uri.toString()).values.putAll(values.values);return 1;}
public synchronized int delete(Uri uri,String where,String[] args){bytes.remove(uri.toString());return rows.remove(uri.toString())==null?0:1;}
public synchronized Cursor query(Uri uri,String[] projection,String selection,String[] args,String sort){ContentValues row=rows.get(uri.toString());return new Cursor(row==null?null:(String)row.get(projection[0]));}}''',
    'android/content/Intent.java': r'''package android.content;import android.net.Uri;import java.util.*;
public class Intent {public static final String ACTION_VIEW="android.intent.action.VIEW",ACTION_CHOOSER="android.intent.action.CHOOSER";public static final int FLAG_GRANT_READ_URI_PERMISSION=1,FLAG_ACTIVITY_NEW_TASK=0x10000000,FLAG_ACTIVITY_SINGLE_TOP=0x20000000,FLAG_ACTIVITY_CLEAR_TOP=0x4000000;
public String action,type;public Uri data;public Intent target;public int flags;public final Map<String,Object> extras=new HashMap<String,Object>();
public Intent(String action){this.action=action;}public Intent(Context c,Class<?> component){}public Intent setAction(String a){action=a;return this;}public Intent setData(Uri d){data=d;return this;}
public Intent setDataAndType(Uri d,String t){data=d;type=t;return this;}public Intent addFlags(int f){flags|=f;return this;}public Intent putExtra(String k,String v){extras.put(k,v);return this;}
public static Intent createChooser(Intent target,CharSequence title){Intent chooser=new Intent(ACTION_CHOOSER);chooser.target=target;return chooser;}}''',
    'android/content/ComponentName.java': 'package android.content;public class ComponentName {public ComponentName(Context c,Class<?> component){}}',
    'android/database/Cursor.java': r'''package android.database;
public class Cursor implements java.io.Closeable {final String value;public Cursor(String value){this.value=value;}public boolean moveToFirst(){return value!=null;}public String getString(int column){return value;}public void close(){}}''',
    'android/net/Uri.java': r'''package android.net;
public class Uri {final String value;Uri(String value){this.value=value;}public static Uri parse(String value){return new Uri(value);}@Override public String toString(){return value;}}''',
    'android/os/Build.java': 'package android.os;public class Build {public static class VERSION {public static int SDK_INT=29;}}',
    'android/os/Environment.java': 'package android.os;public class Environment {public static final String DIRECTORY_DOWNLOADS="Download";}',
    'android/provider/MediaStore.java': r'''package android.provider;
public class MediaStore {public static class MediaColumns {public static final String DISPLAY_NAME="_display_name",MIME_TYPE="mime_type",RELATIVE_PATH="relative_path",IS_PENDING="is_pending";}
public static class Downloads {public static final android.net.Uri EXTERNAL_CONTENT_URI=android.net.Uri.parse("content://media/external/downloads");}}''',
    'android/webkit/MimeTypeMap.java': r'''package android.webkit;import java.util.*;
public class MimeTypeMap {static final Map<String,String> TYPES=new HashMap<String,String>();static{TYPES.put("png","image/png");TYPES.put("jpg","image/jpeg");TYPES.put("pdf","application/pdf");TYPES.put("txt","text/plain");TYPES.put("apk","application/vnd.android.package-archive");}
public static MimeTypeMap getSingleton(){return new MimeTypeMap();}public String getMimeTypeFromExtension(String ext){return TYPES.get(ext);}
public String getExtensionFromMimeType(String mime){for(Map.Entry<String,String> e:TYPES.entrySet())if(e.getValue().equals(mime))return e.getKey();return null;}}''',
    'android/graphics/Typeface.java': 'package android.graphics;public class Typeface {public static final int BOLD=1;}',
    'android/text/Spanned.java': 'package android.text;public interface Spanned {int SPAN_EXCLUSIVE_EXCLUSIVE=33;}',
    'android/text/SpannableStringBuilder.java': r'''package android.text;
public class SpannableStringBuilder implements CharSequence {final StringBuilder text;public SpannableStringBuilder(CharSequence t){text=new StringBuilder(t);}public void setSpan(Object what,int start,int end,int flags){}
public SpannableStringBuilder append(CharSequence t){text.append(t);return this;}public int length(){return text.length();}public char charAt(int i){return text.charAt(i);}public CharSequence subSequence(int s,int e){return text.subSequence(s,e);}@Override public String toString(){return text.toString();}}''',
    'android/text/style/StyleSpan.java': 'package android.text.style;public class StyleSpan {public StyleSpan(int style){}}',
    'android/app/Notification.java': r'''package android.app;import java.util.*;
public class Notification {public static final int VISIBILITY_PRIVATE=0,VISIBILITY_PUBLIC=1;public static final String CATEGORY_EVENT="event",CATEGORY_PROGRESS="progress";
public CharSequence title,text;public PendingIntent contentIntent;public final List<Action> actions=new ArrayList<Action>();
public static class Style {}public static class BigTextStyle extends Style {public BigTextStyle bigText(CharSequence t){return this;}}
public static class Action {public CharSequence title;public PendingIntent intent;public static class Builder {final Action action=new Action();public Builder(Object icon,CharSequence title,PendingIntent intent){action.title=title;action.intent=intent;}
public Builder addRemoteInput(RemoteInput input){return this;}public Builder setAllowGeneratedReplies(boolean allow){return this;}public Action build(){return action;}}}
public static class Builder {final Notification n=new Notification();public Builder(android.content.Context c,String channel){}
public Builder setSmallIcon(int i){return this;}public Builder setColor(int c){return this;}public Builder setContentTitle(CharSequence t){n.title=t;return this;}public Builder setContentText(CharSequence t){n.text=t;return this;}
public Builder setStyle(Style s){return this;}public Builder setSubText(CharSequence s){return this;}public Builder setLargeIcon(Object i){return this;}public Builder setContentIntent(PendingIntent p){n.contentIntent=p;return this;}
public Builder setAutoCancel(boolean b){return this;}public Builder setGroup(String g){return this;}public Builder setShowWhen(boolean b){return this;}public Builder setVisibility(int v){return this;}public Builder setPublicVersion(Notification p){return this;}
public Builder addAction(Action a){n.actions.add(a);return this;}public Builder setOngoing(boolean b){return this;}public Builder setOnlyAlertOnce(boolean b){return this;}public Builder setWhen(long w){return this;}
public Builder setCategory(String c){return this;}public Builder setProgress(int max,int value,boolean indeterminate){return this;}public Notification build(){return n;}}}''',
    'android/app/NotificationManager.java': r'''package android.app;import java.util.*;
public class NotificationManager {public static final int IMPORTANCE_NONE=0,IMPORTANCE_HIGH=4;public final Map<String,Notification> posted=new LinkedHashMap<String,Notification>();
public synchronized void notify(String tag,int id,Notification n){posted.put(tag,n);}public boolean areNotificationsEnabled(){return true;}public NotificationChannel getNotificationChannel(String id){return null;}}''',
    'android/app/NotificationChannel.java': 'package android.app;public class NotificationChannel {public int getImportance(){return 4;}}',
    'android/app/PendingIntent.java': r'''package android.app;import android.content.*;
public class PendingIntent {public static final int FLAG_UPDATE_CURRENT=1,FLAG_IMMUTABLE=2,FLAG_MUTABLE=4;public Intent intent;
public static PendingIntent getActivity(Context c,int code,Intent intent,int flags){PendingIntent p=new PendingIntent();p.intent=intent;return p;}public static PendingIntent getBroadcast(Context c,int code,Intent intent,int flags){return getActivity(c,code,intent,flags);}}''',
    'android/app/DownloadManager.java': 'package android.app;public class DownloadManager {public static final String ACTION_VIEW_DOWNLOADS="android.intent.action.VIEW_DOWNLOADS";}',
    'android/app/RemoteInput.java': 'package android.app;public class RemoteInput {public static class Builder {public Builder(String key){}public Builder setLabel(CharSequence label){return this;}public RemoteInput build(){return new RemoteInput();}}}',
    # The pending job is both a running job and one waiting out its backoff; scheduling the same ID replaces it.
    'android/app/job/JobScheduler.java': r'''package android.app.job;
public class JobScheduler {public JobInfo pending;public boolean executing;public int scheduled,stopped;public synchronized JobInfo getPendingJob(int id){return pending;}
public synchronized int schedule(JobInfo job){if(executing){stopped++;executing=false;}scheduled++;pending=job;return 1;}}''',
    'android/app/job/JobInfo.java': r'''package android.app.job;
public class JobInfo {public static final int NETWORK_TYPE_ANY=1;public static class Builder {final JobInfo job=new JobInfo();public Builder(int id,android.content.ComponentName c){}
public Builder setRequiredNetworkType(int n){return this;}public Builder setMinimumLatency(long l){return this;}public Builder setPersisted(boolean p){return this;}public JobInfo build(){return job;}}}''',
    'android/app/job/JobParameters.java': 'package android.app.job;public class JobParameters {public JobInfo job;}',
    'android/app/job/JobService.java': r'''package android.app.job;import java.util.concurrent.*;
public abstract class JobService extends android.content.Context {public static final BlockingQueue<Boolean> finished=new LinkedBlockingQueue<Boolean>();
public abstract boolean onStartJob(JobParameters p);public abstract boolean onStopJob(JobParameters p);
public final void jobFinished(JobParameters p,boolean retry){JobScheduler s=scheduler;synchronized(s){if(p.job==s.pending){s.executing=false;if(!retry)s.pending=null;}}finished.add(retry);}}''',
    'org/json/JSONException.java': 'package org.json;public class JSONException extends Exception {public JSONException(String message){super(message);}}',
    'org/json/JSONObject.java': r'''package org.json;import java.util.*;
public class JSONObject {public static final Object NULL=new Object(){@Override public String toString(){return "null";}};final Map<String,Object> map=new LinkedHashMap<String,Object>();
public JSONObject(){}public JSONObject(String text)throws JSONException{Object v=new JSONTokener(text).nextValue();if(!(v instanceof JSONObject))throw new JSONException("Not an object");map.putAll(((JSONObject)v).map);}
public JSONObject put(String k,Object v)throws JSONException{if(v==null)map.remove(k);else map.put(k,v);return this;}public JSONObject put(String k,long v)throws JSONException{map.put(k,v);return this;}
public JSONObject put(String k,int v)throws JSONException{map.put(k,(long)v);return this;}public JSONObject put(String k,double v)throws JSONException{map.put(k,v);return this;}public JSONObject put(String k,boolean v)throws JSONException{map.put(k,v);return this;}
public boolean has(String k){return map.containsKey(k);}public Object opt(String k){return map.get(k);}public Object get(String k)throws JSONException{Object v=map.get(k);if(v==null)throw new JSONException("No value for "+k);return v;}
public String getString(String k)throws JSONException{return get(k).toString();}public String optString(String k){return optString(k,"");}public String optString(String k,String d){Object v=map.get(k);return v==null||v==NULL?d:v.toString();}
public long getLong(String k)throws JSONException{Object v=get(k);if(v instanceof Number)return ((Number)v).longValue();try{return Long.parseLong(v.toString());}catch(NumberFormatException e){throw new JSONException(k);}}
public double optDouble(String k,double d){Object v=map.get(k);return v instanceof Number?((Number)v).doubleValue():d;}public boolean optBoolean(String k,boolean d){Object v=map.get(k);return v instanceof Boolean?(Boolean)v:d;}
public JSONObject getJSONObject(String k)throws JSONException{Object v=get(k);if(!(v instanceof JSONObject))throw new JSONException(k);return (JSONObject)v;}public JSONObject optJSONObject(String k){Object v=map.get(k);return v instanceof JSONObject?(JSONObject)v:null;}
public JSONArray optJSONArray(String k){Object v=map.get(k);return v instanceof JSONArray?(JSONArray)v:null;}
static String quote(String s){StringBuilder b=new StringBuilder("\"");for(char ch:s.toCharArray()){if(ch=='"'||ch=='\\')b.append('\\').append(ch);else if(ch<0x20)b.append(String.format("\\u%04x",(int)ch));else b.append(ch);}return b.append('"').toString();}
static String value(Object v){return v instanceof String?quote((String)v):String.valueOf(v);}
@Override public String toString(){StringBuilder b=new StringBuilder("{");for(Map.Entry<String,Object> e:map.entrySet()){if(b.length()>1)b.append(',');b.append(quote(e.getKey())).append(':').append(value(e.getValue()));}return b.append('}').toString();}}''',
    'org/json/JSONArray.java': r'''package org.json;import java.util.*;
public class JSONArray {final List<Object> list=new ArrayList<Object>();public int length(){return list.size();}public JSONArray put(Object v){list.add(v);return this;}public JSONArray put(long v){list.add(v);return this;}
public Object get(int i)throws JSONException{if(i<0||i>=list.size())throw new JSONException("Index "+i);return list.get(i);}public JSONObject getJSONObject(int i)throws JSONException{Object v=get(i);if(!(v instanceof JSONObject))throw new JSONException("Not an object");return (JSONObject)v;}
@Override public String toString(){StringBuilder b=new StringBuilder("[");for(Object v:list){if(b.length()>1)b.append(',');b.append(JSONObject.value(v));}return b.append(']').toString();}}''',
    'org/json/JSONTokener.java': r'''package org.json;
public class JSONTokener {final String s;int i;public JSONTokener(String s){this.s=s;}void skip(){while(i<s.length()&&Character.isWhitespace(s.charAt(i)))i++;}
void expect(char c)throws JSONException{skip();if(i>=s.length()||s.charAt(i)!=c)throw new JSONException("Expected "+c);i++;}
public Object nextValue()throws JSONException{skip();if(i>=s.length())throw new JSONException("End of input");char c=s.charAt(i);
if(c=='{'){i++;JSONObject o=new JSONObject();skip();if(s.charAt(i)=='}'){i++;return o;}while(true){skip();String k=(String)nextValue();expect(':');o.put(k,nextValue());skip();if(s.charAt(i)==','){i++;continue;}expect('}');return o;}}
if(c=='['){i++;JSONArray a=new JSONArray();skip();if(s.charAt(i)==']'){i++;return a;}while(true){a.put(nextValue());skip();if(s.charAt(i)==','){i++;continue;}expect(']');return a;}}
if(c=='"'){i++;StringBuilder b=new StringBuilder();while(true){char ch=s.charAt(i++);if(ch=='"')return b.toString();if(ch!='\\'){b.append(ch);continue;}char e=s.charAt(i++);
switch(e){case 'n':b.append('\n');break;case 't':b.append('\t');break;case 'r':b.append('\r');break;case 'b':b.append('\b');break;case 'f':b.append('\f');break;case 'u':b.append((char)Integer.parseInt(s.substring(i,i+4),16));i+=4;break;default:b.append(e);}}}
int start=i;while(i<s.length()&&",]} \n\r\t".indexOf(s.charAt(i))<0)i++;String w=s.substring(start,i);if(w.equals("true"))return true;if(w.equals("false"))return false;if(w.equals("null"))return JSONObject.NULL;
try{return w.matches("-?\\d+")?(Object)Long.parseLong(w):(Object)Double.parseDouble(w);}catch(NumberFormatException e){throw new JSONException("Bad value "+w);}}}''',
    'com/personalassistant/companion/Cloud.java': r'''package com.personalassistant.companion;import android.content.*;import org.json.*;
class Cloud {interface Server {Object call(String path,JSONObject body)throws Exception;}static Server server;static SharedPreferences prefs(Context c){return Context.prefs;}
static final class HttpError extends Exception {final int status;HttpError(int status,String message){super(message);this.status=status;}}
static Object call(Context c,String path,JSONObject body,boolean auth)throws Exception{return server.call(path,body);}}''',
    'com/personalassistant/companion/Updates.java': r'''package com.personalassistant.companion;
class Updates {static String hex(byte[] data){StringBuilder out=new StringBuilder();for(byte b:data)out.append(String.format("%02x",b&255));return out.toString();}}''',
    'com/personalassistant/companion/FileDropProvider.java': r'''package com.personalassistant.companion;
class FileDropProvider {static android.net.Uri uri(android.content.Context c,java.io.File file){return android.net.Uri.parse("content://fixture.files/"+file.getName());}}''',
    'com/personalassistant/companion/NotificationStyle.java': r'''package com.personalassistant.companion;
final class NotificationStyle {static final int[] BRAND={0},PROGRESS={0},DONE={0},ATTENTION={0},FAILED={0};static Object icon(android.content.Context c,String glyph,int[] tone){return null;}
static void channel(android.app.NotificationManager manager,String id,String name,int importance,String description){}}''',
    'com/personalassistant/companion/R.java': 'package com.personalassistant.companion;final class R {static final class drawable {static final int ic_stat_assistant=1;}}',
    'com/personalassistant/companion/SyncJob.java': 'package com.personalassistant.companion;class SyncJob {static void scheduleUpdate(android.content.Context c){}}',
    'com/personalassistant/companion/NativeTasks.java': 'package com.personalassistant.companion;class NativeTasks {static void changed(android.content.Context c){}}',
    'com/personalassistant/companion/MainActivity.java': 'package com.personalassistant.companion;class MainActivity {}',
    'com/personalassistant/companion/NotificationActions.java': 'package com.personalassistant.companion;class NotificationActions {}',
}


def tool(name):
    found = shutil.which(name)
    home = os.environ.get('JAVA_HOME')
    if not found and home:
        candidate = Path(home) / 'bin' / (name + ('.exe' if os.name == 'nt' else ''))
        found = str(candidate) if candidate.is_file() else None
    return found


JAVAC, JAVA = tool('javac'), tool('java')
BUILD = None


def setUpModule():
    global BUILD
    if not (JAVAC and JAVA):
        return
    BUILD = tempfile.TemporaryDirectory(prefix='assistant-file-drops-')
    shims = Path(BUILD.name) / 'shims'
    for name, body in SHIMS.items():
        (shims / name).parent.mkdir(parents=True, exist_ok=True)
        (shims / name).write_text(body, encoding='utf-8')
    classes = Path(BUILD.name) / 'classes'
    for flags in (['--release', '8'], []):
        built = subprocess.run([JAVAC, '-encoding', 'UTF-8', '-nowarn', *flags, '-d', str(classes), *map(str, SOURCES), *map(str, sorted(shims.rglob('*.java')))],
                               capture_output=True, text=True)
        if built.returncode == 0:
            return
    raise RuntimeError(built.stderr)


def tearDownModule():
    if BUILD:
        BUILD.cleanup()


def harness(mode, lines=()):
    """One fresh JVM and phone per call; returns the printed lines."""
    with tempfile.TemporaryDirectory(prefix='assistant-file-drop-phone-') as phone:
        run = subprocess.run([JAVA, '-cp', str(Path(BUILD.name) / 'classes'), MAIN, mode, phone], input=''.join(line + '\n' for line in lines),
                             capture_output=True, text=True, encoding='utf-8', timeout=120)
    if run.returncode:
        raise AssertionError(run.stderr)
    return run.stdout.splitlines()


def report(mode):
    return json.loads(harness(mode)[-1])


def utf8(text):
    return len(text.encode('utf-8', 'surrogatepass'))


@unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
class WaitingListTests(unittest.TestCase):
    def test_drops_past_the_relays_first_page_are_delivered_in_the_same_run(self):
        # The relay lists 50 waiting drops at a time; delivered drops leave the list.
        result = report('paging')
        self.assertEqual((result['delivered'], result['waiting'], result['saved'], result['cards']), (120, 0, 120, 120))
        self.assertFalse(result['more'])
        self.assertFalse(result['due'])
        self.assertTrue(result['listed'])
        self.assertLessEqual(result['lists'], 4)

    def test_a_failing_drop_does_not_hold_back_the_pages_after_it(self):
        result = report('failing')
        self.assertTrue(result['threw'])
        self.assertEqual((result['delivered'], result['waiting']), (59, 1))
        # The failure leaves drops due for the job's retry and does not count as a completed check.
        self.assertTrue(result['due'])
        self.assertFalse(result['listed'])

    def test_a_drop_that_stays_listed_without_its_bytes_ends_the_run(self):
        result = report('stuck')
        self.assertFalse(result['more'])
        self.assertEqual((result['delivered'], result['waiting']), (2, 1))
        self.assertEqual(result['lists'], 2)

    def test_a_server_without_file_transfer_has_nothing_waiting(self):
        self.assertEqual(report('missing'), {'more': False, 'due': False, 'listed': True})


@unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
class FileNameTests(unittest.TestCase):
    def names(self, values):
        return [tuple(json.loads(line)) for line in harness('names', [json.dumps(value) for value in values])]

    def test_names_stay_within_the_byte_limit_and_keep_their_extension(self):
        cjk, emoji = '\u6587' * 150, '\U0001F600' * 100
        cases = [cjk + '.pdf', emoji + '.txt', 'a' * 146 + '.pdf', 'x.' + '\u5b57' * 100, 'Quarterly report 2026.pdf']
        for value, (name, size) in zip(cases, self.names(cases)):
            with self.subTest(value=value[:12]):
                self.assertEqual(size, utf8(name))
                self.assertLessEqual(size, 200)
                name.encode('utf-8')  # whole code points only: a split surrogate pair cannot be encoded
        got = dict(zip(cases, (name for name, _ in self.names(cases))))
        self.assertEqual(got[cjk + '.pdf'], '\u6587' * 65 + '.pdf')
        self.assertEqual(got[emoji + '.txt'], '\U0001F600' * 49 + '.txt')
        self.assertEqual(got['a' * 146 + '.pdf'], 'a' * 146 + '.pdf')
        # An "extension" too long to be one is part of the name and is cut with it.
        self.assertEqual(got['x.' + '\u5b57' * 100], 'x.' + '\u5b57' * 66)
        self.assertEqual(got['Quarterly report 2026.pdf'], 'Quarterly report 2026.pdf')

    def test_format_characters_cannot_disguise_the_extension(self):
        cases = ['invoice\u202egnp.apk', 'photo\u200f.png', 'a\u2028b.txt', 'a\u2029b.txt', 'a\u0085b.txt', 'a\u0007b.txt', '../x\\y.txt', '...', '', ' trip.pdf ']
        self.assertEqual([name for name, _ in self.names(cases)],
                         ['invoice_gnp.apk', 'photo_.png', 'a_b.txt', 'a_b.txt', 'a_b.txt', 'a_b.txt', '.._x_y.txt', 'download', 'download', 'trip.pdf'])


@unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
class FileCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = report('save')['cases']

    def test_every_case_was_saved_and_receipted(self):
        self.assertTrue(all(case['delivered'] for case in self.cases))

    def test_app_packages_are_saved_but_never_opened_from_the_card(self):
        renamed, _, plain, _, pre_q, disguised, _, _, _ = self.cases
        # Declared as a package under a photo's name: MediaStore saves it as a package, and the card says so.
        self.assertEqual(renamed['title'], 'File ready: holiday.jpg.apk')
        for case in (renamed, plain):
            self.assertEqual(case['open'], 'downloads')
            self.assertEqual(case['actions'], ['Downloads'])
            self.assertIn('app packages are not opened from here', case['text'])
        for case in (pre_q, disguised):
            self.assertEqual((case['open'], case['actions']), ('none', []))
        self.assertEqual(disguised['saved'], 'invoice_gnp.apk')
        self.assertEqual(disguised['title'], 'File ready: invoice_gnp.apk')

    def test_cards_open_by_the_extension_the_saved_file_has(self):
        _, photo, _, notes, _, _, long, first, second = self.cases
        self.assertEqual((photo['open'], photo['actions']), ('view:image/png', ['Open with', 'Downloads']))
        # MediaStore gave the extension-less text file its extension; the card names and opens the saved file.
        self.assertEqual((notes['saved'], notes['title'], notes['open']), ('notes.txt', 'File ready: notes.txt', 'view:text/plain'))
        self.assertEqual((long['open'], long['actions']), ('view:application/pdf', ['Open with']))
        self.assertEqual((first['saved'], second['saved']), ('scan.png', 'scan (1).png'))
        self.assertEqual(second['title'], 'File ready: scan (1).png')

    def test_long_names_fit_the_file_system_on_android_8_and_9(self):
        long = self.cases[6]
        self.assertEqual(long['sdk'], 28)
        self.assertTrue(long['saved'].endswith('.pdf'))
        self.assertLessEqual(long['saved_bytes'], 200)
        self.assertEqual(long['title'], 'File ready: ' + long['saved'])


@unittest.skipUnless(JAVAC and JAVA, 'A JDK is needed to compile the companion classes')
class SchedulingTests(unittest.TestCase):
    def test_a_new_file_event_replaces_a_failure_backoff_and_a_recovery_check_keeps_it(self):
        result = report('schedule')
        self.assertTrue(result['failure_retries'])
        self.assertTrue(result['backoff_pending'])
        self.assertTrue(result['due_after_failure'])
        self.assertTrue(result['recovery_keeps_backoff'])
        self.assertTrue(result['new_event_replaces_backoff'])

    def test_a_running_job_is_not_restarted_and_a_late_event_runs_it_again(self):
        result = report('schedule')
        self.assertTrue(result['event_while_running_ignored'])
        self.assertTrue(result['pass_succeeded'])
        self.assertEqual(result['delivered'], 1)
        self.assertTrue(result['late_event_runs_again'])

    def test_an_expired_file_event_still_has_the_waiting_list_checked(self):
        result = report('events')
        self.assertTrue(result['expired_file_event_marks_due'])
        self.assertTrue(result['new_event_replaces_backoff'])
        self.assertEqual(result['cursor'], 1)
        self.assertTrue(result['recovery_keeps_backoff'])

    def test_the_waiting_list_is_checked_again_after_hours_without_file_events(self):
        result = report('events')
        self.assertTrue(result['recent_check_stays_idle'])
        self.assertTrue(result['old_check_runs_again'])


if __name__ == '__main__':
    unittest.main()
