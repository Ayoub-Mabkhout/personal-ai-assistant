package com.personalassistant.companion;

import android.content.SharedPreferences;
import android.graphics.Typeface;
import android.os.*;
import android.text.*;
import android.text.style.*;
import android.view.*;
import android.view.inputmethod.EditorInfo;
import android.widget.*;
import org.json.*;
import java.util.*;
import java.util.regex.Pattern;

/** Shopping tab: quick add, offline-first rows with a timed undo, and the saved-changes banner. */
final class MainShopping {
    static final long UNDO_MS=4000;
    private static final String[] COMPOUNDS={"mac and cheese","salt and pepper","oil and vinegar"};
    private static final Pattern SEPARATOR=Pattern.compile("\\s*(?:,|;|\\band\\b|\\bund\\b)\\s*",Pattern.CASE_INSENSITIVE);
    private final MainActivity a;private final AppUi ui;private final Handler handler=new Handler(Looper.getMainLooper());
    final EditText input;final TextView status;
    private final AppUi.Icon syncGlyph;private final MainParts.Banner banner;private final LinearLayout card,rows,empty;
    private final Runnable commitTick=()->commit(true);
    private String renderedKey="",tickId;private Row tick;private long collapsingUntil;

    MainShopping(MainActivity a,AppUi ui,LinearLayout page){
        this.a=a;this.ui=ui;
        LinearLayout head=ui.row();head.setGravity(Gravity.TOP);head.addView(ui.header("Shopping","Your list, wherever you are."),MainParts.weighted(ui,1,0,0,0,0));head.addView(MainParts.tonalChip(ui,"Recipes","recipe",a::recipes),MainParts.params(ui,-2,-2,4,-4,-4,0));page.addView(head);ui.space(page,12);
        LinearLayout add=ui.row();input=ui.field("Add an item","",true);input.setTag("shopping_item");input.setImeOptions(EditorInfo.IME_ACTION_DONE);input.setOnEditorActionListener((v,action,event)->{if(action==EditorInfo.IME_ACTION_DONE){add();return true;}return false;});
        add.addView(input,new LinearLayout.LayoutParams(0,ui.dp(52),1));ImageButton save=ui.fab("plus","Add to list",this::add);save.setTag("shopping_add");add.addView(save,MainParts.params(ui,ui.dp(52),ui.dp(52),10,0,0,0));page.addView(add);ui.space(page,10);
        LinearLayout sync=ui.row();sync.setPadding(ui.dp(4),0,0,0);syncGlyph=MainParts.icon(ui,"cloud",ui.success);sync.addView(syncGlyph,new LinearLayout.LayoutParams(ui.dp(17),ui.dp(17)));
        status=ui.type("",13,18,500,0,ui.success);status.setTag("shopping_status");sync.addView(status,MainParts.weighted(ui,1,7,0,8,0));sync.addView(ui.chip("Refresh","refresh",a::sync),MainParts.params(ui,-2,-2,0,0,-3,0));page.addView(sync);
        banner=new MainParts.Banner(ui,"warning","phone-saved","Review saved changes","They send when you are back online",a::review);banner.setVisibility(View.GONE);page.addView(banner,MainParts.params(ui,-1,-2,0,6,0,8));
        rows=ui.column();card=ui.rowsCard();card.addView(rows);page.addView(card,MainParts.params(ui,-1,-2,0,4,0,0));
        empty=ui.empty("shopping","Nothing on the list","Add an item above, or pick ingredients from a saved recipe.","Add from a recipe",a::recipes);page.addView(empty);
        LinearLayout tip=ui.row();tip.setGravity(Gravity.CENTER);tip.addView(MainParts.icon(ui,"voice",ui.accent),new LinearLayout.LayoutParams(ui.dp(15),ui.dp(15)));tip.addView(ui.type("Try saying \u201cHey Chat, add basil to my list.\u201d",13,18,400,0,ui.muted),MainParts.params(ui,-2,-2,8,0,0,0));page.addView(tip,MainParts.params(ui,-1,-2,0,18,0,0));
    }

    /** Splits "milk, eggs and bread" into separate items; a few common pairs stay together. */
    static List<String> split(String text){
        Map<String,String> keys=new LinkedHashMap<>();String value=text==null?"":text;
        for(String phrase:COMPOUNDS){Pattern p=Pattern.compile(Pattern.quote(phrase),Pattern.CASE_INSENSITIVE);if(p.matcher(value).find()){String key="COMPOUND"+keys.size();keys.put(key,phrase);value=p.matcher(value).replaceAll(key);}}
        List<String> names=new ArrayList<>();
        for(String part:SEPARATOR.split(value)){String name=part.trim();for(Map.Entry<String,String> e:keys.entrySet())name=name.replace(e.getKey(),e.getValue());if(!name.isEmpty()&&names.size()<100)names.add(name.length()>300?name.substring(0,300):name);}
        return names;
    }

    void add(){
        if(!a.paired()){a.needPairing();return;}
        List<String> names=split(input.getText().toString());if(names.isEmpty())return;
        try{JSONArray items=new JSONArray();for(String name:names)items.put(new JSONObject().put("name",name).put("quantity",""));Cloud.enqueue(a,new JSONObject().put("operation","add").put("items",items));input.setText("");render();a.sync();}
        catch(Exception error){note(error.getMessage(),"warning","alert");}
    }

    void note(String message,String tone,String glyph){int[] c=ui.toneColors(tone);status.setTextColor(c[0]);syncGlyph.color(c[0]);syncGlyph.kind(glyph);AppUi.update(status,message);}

    private JSONObject find(String id){try{JSONArray items=Cloud.pendingList(a).optJSONArray("items");if(items!=null)for(int i=0;i<items.length();i++)if(items.getJSONObject(i).optString("id").equals(id))return items.getJSONObject(i);}catch(Exception ignored){}return null;}

    /** Writes the ticked row to the outbox: after the undo window, or at once when another row is ticked or the screen is left. */
    void commit(boolean animate){
        if(tickId==null)return;handler.removeCallbacks(commitTick);String id=tickId;Row row=tick;tickId=null;tick=null;
        JSONObject item=find(id);if(item==null||item.optInt("complete")!=0||item.optInt("version")<1)return;
        try{
            boolean slide=animate&&AppUi.motion()&&row!=null&&row.box.isShown();collapsingUntil=slide?SystemClock.uptimeMillis()+600:0;
            Cloud.enqueue(a,new JSONObject().put("operation","complete").put("target",id).put("version",item.getInt("version")).put("complete",true));a.sync();
            if(slide)AppUi.collapse(row.box,()->{collapsingUntil=0;render();});
        }catch(Exception error){collapsingUntil=0;if(row!=null)row.set(false,false);note(error.getMessage(),"warning","alert");}
    }

    private void tick(Row row){commit(true);tickId=row.id;tick=row;row.set(true,true);row.box.announceForAccessibility(row.name+" marked as bought. Undo is available.");handler.postDelayed(commitTick,UNDO_MS);}
    private void undo(Row row){handler.removeCallbacks(commitTick);tickId=null;tick=null;row.set(false,true);}

    void render(){
        SharedPreferences p=Cloud.prefs(a);boolean paired=a.paired(),syncing=a.syncing();String key=p.getString("snapshot","")+p.getString("outbox","")+p.getString("status","")+p.getLong("synced",0)+syncing+paired;
        if(key.equals(renderedKey)||SystemClock.uptimeMillis()<collapsingUntil)return;renderedKey=key;
        rows.removeAllViews();tick=null;int count=0,queued=0;
        try{
            JSONArray items=Cloud.pendingList(a).optJSONArray("items");
            if(items!=null)for(int i=0;i<items.length();i++){JSONObject item=items.getJSONObject(i);if(item.optInt("complete")!=0)continue;Row row=new Row(item,count>0);rows.addView(row.box);if(row.id.equals(tickId))tick=row;count++;}
            queued=Cloud.queue(a).length();
        }catch(Exception error){note("Could not read the list on this phone.","warning","alert");}
        card.setVisibility(count>0?View.VISIBLE:View.GONE);empty.setVisibility(count>0?View.GONE:View.VISIBLE);
        banner.setVisibility(queued>0?View.VISIBLE:View.GONE);
        String saved=p.getString("status",paired?"Cloud list":"Connect your phone to use the list");
        if(syncing)note("Syncing...","accent","refresh");
        else if(queued>0)note(queued+" change"+(queued==1?"":"s")+" saved on this phone","warning","phone-saved");
        else if(!paired)note(saved,"neutral","cloud-off");
        else if(saved.equals("Cloud saved")){long at=p.getLong("synced",0);note(at>0?"Cloud saved \u00b7 "+android.text.format.DateFormat.format("HH:mm",at):saved,"success","cloud");}
        else note(saved,saved.equals("Cloud list")?"neutral":"warning",saved.equals("Cloud list")?"cloud":"alert");
    }

    /** One list row: check dot, struck label, then Undo while ticked or a "Saved on phone" chip for adds not yet synced. */
    private final class Row {
        final LinearLayout box=ui.column(),line=ui.row();final String id,name,quantity;final boolean pending;final AppUi.CheckDot dot=new AppUi.CheckDot(ui);final AppUi.StrikeText label=new AppUi.StrikeText(a,ui.muted);final TextView undo;final View divider;
        Row(JSONObject item,boolean separated){
            id=item.optString("id");name=item.optString("name");quantity=item.optString("quantity").trim();pending=item.optBoolean("pending",false)&&item.optInt("version")==0;
            divider=new View(a);divider.setBackgroundColor(ui.stroke);if(separated)box.addView(divider,MainParts.params(ui,-1,1,54,0,14,0));
            line.setMinimumHeight(ui.dp(60));line.setPadding(ui.dp(14),0,ui.dp(6),0);line.addView(dot,new LinearLayout.LayoutParams(ui.dp(26),ui.dp(26)));
            label.setTextSize(16);label.setTypeface(AppUi.face(500));label.setIncludeFontPadding(false);label.setLineSpacing(0,1.12f);line.addView(label,MainParts.weighted(ui,1,14,10,8,10));
            undo=ui.type("Undo",14,0,700,0,ui.accent);undo.setGravity(Gravity.CENTER);undo.setMinHeight(ui.dp(48));undo.setMinimumWidth(ui.dp(56));undo.setPadding(ui.dp(10),0,ui.dp(10),0);undo.setBackground(ui.pressable(null,20));undo.setClickable(true);undo.setOnClickListener(v->undo(this));undo.setContentDescription("Undo "+name);
            line.addView(undo);box.addView(line);
            if(pending){AppUi.StatusChip chip=ui.statusChip("Saved on phone","warning");chip.setCompoundDrawablesWithIntrinsicBounds(ui.glyph("phone-saved",ui.warning,14),null,null,null);line.addView(chip,MainParts.params(ui,-2,-2,0,0,8,0));dot.setAlpha(.45f);}
            else{line.setClickable(true);line.setFocusable(true);line.setOnClickListener(v->{if(id.equals(tickId))undo(this);else tick(this);});AppUi.press(line);}
            String spoken=quantity.isEmpty()?name:quantity+" "+name;line.setContentDescription(pending?spoken+", saved on this phone":spoken+", tap to mark as bought");
            set(id.equals(tickId),false);
        }
        void set(boolean on,boolean animate){
            dot.set(on,animate);label.strike(on,animate);label.setTextColor(on?ui.muted:ui.text);label.setText(text(on));undo.setVisibility(on?View.VISIBLE:View.GONE);
            line.setBackground(pending?null:ui.pressable(on?ui.outline(ui.accentSoft,20,0,0):null,20));divider.setVisibility(on?View.INVISIBLE:View.VISIBLE);
        }
        CharSequence text(boolean on){
            if(quantity.isEmpty())return name;SpannableStringBuilder s=new SpannableStringBuilder(quantity);s.setSpan(new StyleSpan(Typeface.BOLD),0,s.length(),0);s.setSpan(new ForegroundColorSpan(on?ui.muted:ui.accent),0,s.length(),0);return s.append("  ").append(name);
        }
    }
}
