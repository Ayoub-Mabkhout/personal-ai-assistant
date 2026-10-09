package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.os.*;
import android.text.*;
import android.view.*;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.inputmethod.EditorInfo;
import android.widget.*;
import java.util.*;
import java.util.function.Consumer;

/** Features checklist sheet: open features under a quick add, a collapsible Finished section, and offline-first edits through the Features outbox. */
final class FeatureScreen {
    private static final Map<Activity,FeatureScreen> openScreens=new WeakHashMap<>();
    static void open(MainActivity a){if(!openScreens.containsKey(a))new FeatureScreen(a).show();}
    static void close(Activity a){FeatureScreen screen=openScreens.remove(a);if(screen!=null)screen.dialog.dismiss();}

    final MainActivity a;final AppUi ui;final Dialog dialog;final LinearLayout root,body,areas,openHolder,doneHead,doneCard,doneRows;final ScrollView scroll;
    final TextView status,openCount,doneCount;final ImageButton refresh;final EditText input;final AppUi.Fab add;final MainParts.Banner banner;final AppUi.Icon chevron;final Handler main=new Handler(Looper.getMainLooper());
    final BroadcastReceiver changes=new BroadcastReceiver(){@Override public void onReceive(Context c,Intent i){render();}};
    String area,rendered,arriving;boolean closed,registered,busy,again,expanded;long movingUntil;int finished;

    FeatureScreen(MainActivity a){
        this.a=a;ui=new AppUi(a);dialog=ui.sheet();SharedPreferences p=Cloud.prefs(a);area=FeatureBoard.area(p.getString("features_area","assistant"));expanded=p.getBoolean("features_finished_open",true);
        root=ui.column();root.setBackground(ui.pageBackground());
        LinearLayout bar=ui.row();bar.setPadding(ui.dp(17),ui.dp(6),ui.dp(17),ui.dp(6));bar.addView(ui.iconButton("back","Back from Features",dialog::dismiss),new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));
        TextView heading=ui.type("Features",20,26,700,-.01f,ui.text);heading.setSingleLine(true);heading.setEllipsize(TextUtils.TruncateAt.END);if(Build.VERSION.SDK_INT>=28)heading.setAccessibilityHeading(true);bar.addView(heading,MainParts.weighted(ui,1,10,0,10,0));
        refresh=ui.iconButton("refresh","Refresh features",this::sync);refresh.setTag("features_refresh");bar.addView(refresh,new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));root.addView(bar);
        status=ui.type("",12.5f,18,500,0,ui.muted);status.setTag("features_status");status.setVisibility(View.GONE);status.setPadding(ui.dp(24),ui.dp(2),ui.dp(24),ui.dp(8));status.setCompoundDrawablePadding(ui.dp(6));status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);root.addView(status);
        scroll=new ScrollView(a);scroll.setFillViewport(true);body=ui.column();body.setPadding(ui.dp(20),ui.dp(4),ui.dp(20),ui.dp(24));scroll.addView(body);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));

        body.addView(ui.detail("What the assistant can do and what is planned. Implemented features move to Finished."),MainParts.params(ui,-1,-2,4,0,4,14));
        LinearLayout addRow=ui.row();input=ui.field("Add a feature",p.getString("features_draft",""),true);input.setTag("features_input");input.setContentDescription("New feature name");
        input.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);input.setImeOptions(EditorInfo.IME_ACTION_DONE);input.setFilters(new InputFilter[]{new InputFilter.LengthFilter(FeatureBoard.TITLE_MAX)});
        input.setOnEditorActionListener((v,action,event)->{if(action==EditorInfo.IME_ACTION_DONE){add();return true;}return false;});
        addRow.addView(input,new LinearLayout.LayoutParams(0,ui.dp(52),1));add=ui.fab("plus","Add feature",this::add);add.setTag("features_add");addRow.addView(add,MainParts.params(ui,ui.dp(52),ui.dp(52),10,0,0,0));body.addView(addRow);
        input.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int x,int count,int after){}public void onTextChanged(CharSequence s,int x,int before,int count){Cloud.prefs(a).edit().putString("features_draft",s.toString()).apply();add.setEnabled(FeatureBoard.title(s.toString())!=null);}public void afterTextChanged(Editable e){}});
        add.setEnabled(FeatureBoard.title(input.getText().toString())!=null);input.setSelection(input.length());
        HorizontalScrollView strip=new HorizontalScrollView(a);strip.setHorizontalScrollBarEnabled(false);areas=ui.row();strip.addView(areas);body.addView(strip,MainParts.params(ui,-1,-2,-3,6,0,4));
        chips(areas,area,value->{area=value;Cloud.prefs(a).edit().putString("features_area",value).apply();});

        banner=new MainParts.Banner(ui,"warning","alert","Changes need review","The server did not accept them. Tap to choose.",this::review);banner.setTag("features_review");banner.setVisibility(View.GONE);body.addView(banner,MainParts.params(ui,-1,-2,0,8,0,4));
        LinearLayout openHead=ui.row();openHead.addView(ui.label("Open"),MainParts.weighted(ui,1,0,0,8,0));openCount=ui.small("");openHead.addView(openCount);body.addView(openHead,MainParts.params(ui,-1,-2,4,14,4,8));
        openHolder=ui.column();openHolder.setTag("features_open");body.addView(openHolder);

        doneHead=ui.row();doneHead.setTag("features_finished_toggle");doneHead.setMinimumHeight(ui.dp(48));doneHead.setPadding(ui.dp(4),0,ui.dp(8),0);doneHead.setBackground(ui.pressable(null,16));doneHead.setClickable(true);doneHead.setFocusable(true);AppUi.press(doneHead);
        TextView doneLabel=ui.label("Finished");doneLabel.setTextColor(ui.success);doneHead.addView(doneLabel);doneCount=ui.badge("0");doneHead.addView(doneCount,MainParts.params(ui,-2,-2,8,0,0,0));doneHead.addView(new View(a),new LinearLayout.LayoutParams(0,1,1));
        chevron=MainParts.icon(ui,expanded?"up":"down",ui.muted);doneHead.addView(chevron,new LinearLayout.LayoutParams(ui.dp(20),ui.dp(20)));
        for(int i=0;i<doneHead.getChildCount();i++)doneHead.getChildAt(i).setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        doneHead.setAccessibilityDelegate(new View.AccessibilityDelegate(){@Override public void onInitializeAccessibilityNodeInfo(View host,AccessibilityNodeInfo info){super.onInitializeAccessibilityNodeInfo(host,info);info.setClassName(Button.class.getName());}});
        doneHead.setOnClickListener(v->toggleFinished());body.addView(doneHead,MainParts.params(ui,-1,-2,0,10,0,4));
        doneRows=ui.column();doneRows.setTag("features_finished");doneCard=ui.rowsCard();doneCard.addView(doneRows);body.addView(doneCard);

        root.setOnApplyWindowInsetsListener((v,insets)->{int[] bars=TaskViews.bars(insets);root.setPadding(bars[0],bars[1],bars[2],0);body.setPadding(ui.dp(20),ui.dp(4),ui.dp(20),ui.dp(24)+bars[3]);return insets;});
        dialog.setContentView(root);
        dialog.setOnDismissListener(d->{closed=true;if(openScreens.get(a)==this)openScreens.remove(a);if(registered){a.unregisterReceiver(changes);registered=false;}main.removeCallbacksAndMessages(null);if(!a.isFinishing()&&!a.isDestroyed())a.show();});
        Window window=dialog.getWindow();window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE|WindowManager.LayoutParams.SOFT_INPUT_STATE_HIDDEN);if(Build.VERSION.SDK_INT>=29)window.setNavigationBarContrastEnforced(false);
    }

    void show(){
        openScreens.put(a,this);dialog.show();dialog.getWindow().setLayout(-1,-1);root.post(()->{root.setClipChildren(true);root.setClipToPadding(true);});
        if(Build.VERSION.SDK_INT>=33)a.registerReceiver(changes,new IntentFilter(Features.ACTION),Context.RECEIVER_NOT_EXPORTED);else a.registerReceiver(changes,new IntentFilter(Features.ACTION));registered=true;
        render();sync();
    }

    /** Area choice: the selected chip is tonal with a tick; the rest are outlined with their own glyph. */
    private void chips(LinearLayout row,String chosen,Consumer<String> pick){
        row.removeAllViews();
        for(String value:FeatureBoard.AREAS){
            boolean on=value.equals(chosen);String name=FeatureBoard.areaName(value);Runnable choose=()->{pick.accept(value);chips(row,value,pick);};
            AppUi.Pill chip=on?ui.tonalChip(name,"check",choose):ui.chip(name,"dashboard".equals(value)?"activity":"companion".equals(value)?"voice":"sparkle",choose);
            chip.setTag("feature_area:"+value);chip.setSelected(on);chip.setContentDescription(name+" area"+(on?", selected":""));row.addView(chip,MainParts.params(ui,-2,-2,0,0,6,0));
        }
    }

    void note(String text,String icon,boolean warn){int color=warn?ui.warning:ui.muted;status.setVisibility(text.isEmpty()?View.GONE:View.VISIBLE);AppUi.update(status,text);status.setTextColor(color);status.setCompoundDrawablesRelativeWithIntrinsicBounds(icon==null||text.isEmpty()?null:ui.glyph(icon,color,14),null,null,null);}
    private void spin(){if(!AppUi.motion())return;refresh.animate().cancel();refresh.setRotation(0);refresh.animate().rotation(360).setDuration(600).setInterpolator(AppUi.SLIDE).start();}

    void sync(){
        if(busy){again=true;return;}busy=true;again=false;spin();renderStatus();
        Features.network.execute(()->{try{Features.sync(a);}catch(Exception error){Cloud.prefs(a).edit().putString("features_error",String.valueOf(error.getMessage())).commit();}
            main.post(()->{busy=false;if(closed)return;render();if(again)sync();});});
    }

    void renderStatus(){
        int waiting=0,review=0;try{waiting=Features.waiting(a);review=Features.review(a).size();}catch(Exception ignored){}
        banner.setVisibility(review>0?View.VISIBLE:View.GONE);if(review>0)AppUi.update(banner.title,review==1?"1 change needs review":review+" changes need review");
        SharedPreferences p=Cloud.prefs(a);String error=p.getString("features_error","");long synced=p.getLong("features_synced",0);
        if(busy)note("Syncing features...","refresh",false);
        else if(waiting>0)note(waiting+(waiting==1?" change":" changes")+" saved on this phone · sending when connected","phone-saved",true);
        else if(error.startsWith("Disconnected."))note(error,"alert",true);
        else if(error.contains("(404)"))note("This server does not offer the features list yet. Changes stay on this phone.","alert",true);
        else if(error.contains("Server rejected"))note("The server could not load features. Tap refresh to retry.","alert",true);
        else if(!error.isEmpty())note("Offline · showing features saved on this phone. Tap refresh to retry.","cloud-off",true);
        else if(synced>0)note("Up to date · "+android.text.format.DateFormat.format("HH:mm",synced),"check",false);
        else note("",null,false);
    }

    /** Rebuilds rows only when the cached list or the outbox changed, and never during a move; the add field, its caret and the scroll position stay put. */
    void render(){
        if(closed)return;renderStatus();if(SystemClock.uptimeMillis()<movingUntil)return;
        String key=Features.signature(a);if(key.equals(rendered))return;
        List<FeatureBoard.Item> list;try{list=Features.board(a);}catch(Exception error){note("Could not read the features saved on this phone.","alert",true);return;}
        rendered=key;int open=FeatureBoard.open(list);finished=list.size()-open;View arrived=null;
        openHolder.removeAllViews();doneRows.removeAllViews();
        if(open==0)openHolder.addView(ui.empty("checklist",finished==0?"No features yet":"Everything is finished",finished==0?"Add the first feature above.":"Add the next feature above."));
        else{LinearLayout card=ui.rowsCard();int n=0;for(FeatureBoard.Item item:list)if(!item.done){Row row=new Row(item,n++>0);card.addView(row.box);if(item.id.equals(arriving))arrived=row.box;}openHolder.addView(card);}
        int n=0;for(FeatureBoard.Item item:list)if(item.done){Row row=new Row(item,n++>0);doneRows.addView(row.box);if(item.id.equals(arriving))arrived=row.box;}
        AppUi.update(openCount,open==0?"":open+" open");AppUi.update(doneCount,Integer.toString(finished));
        doneHead.setVisibility(finished>0?View.VISIBLE:View.GONE);doneCard.setVisibility(finished>0&&expanded?View.VISIBLE:View.GONE);describeFinished();
        if(arrived!=null){if(arrived.isShown())AppUi.enter(arrived,0);else AppUi.fade(doneCount);}arriving=null;
    }
    private void describeFinished(){doneHead.setContentDescription("Finished, "+finished+(finished==1?" feature":" features")+(expanded?", expanded. Double tap to collapse":", collapsed. Double tap to expand"));}
    void toggleFinished(){
        expanded=!expanded;Cloud.prefs(a).edit().putBoolean("features_finished_open",expanded).apply();chevron.kind(expanded?"up":"down");describeFinished();
        if(expanded)AppUi.expand(doneCard);else AppUi.collapse(doneCard,null);
    }

    void add(){
        String title=FeatureBoard.title(input.getText().toString());if(title==null){input.requestFocus();return;}
        try{arriving=Features.create(a,title,"",area);input.setText("");render();input.announceForAccessibility(title+" added to open features");sync();}
        catch(Exception error){note("Could not save the feature on this phone. Your text is still here.","alert",true);}
    }

    /** Ticks or unticks at once (saved before anything moves), then slides the row out; it reappears at the top of the other section. */
    void toggle(Row row){
        if(row.moving)return;boolean done=!row.item.done;long hold=SystemClock.uptimeMillis()+900;movingUntil=Math.max(movingUntil,hold);
        try{Features.done(a,row.item.id,done);}catch(Exception error){movingUntil=0;note("Could not save the change on this phone. Try again.","alert",true);return;}
        row.moving=true;row.set(done,true);arriving=row.item.id;row.line.announceForAccessibility(row.item.title+(done?" finished, moved to Finished":" moved back to open"));
        if(!AppUi.motion()||!row.box.isShown()){movingUntil=0;render();}
        else main.postDelayed(()->AppUi.collapse(row.box,()->{if(movingUntil<=hold)movingUntil=0;render();}),260);
        sync();
    }

    void options(FeatureBoard.Item item){
        String[] choices={item.done?"Move back to open":"Mark as finished","Edit","Delete"};
        new AlertDialog.Builder(a).setTitle(item.title).setItems(choices,(d,which)->{
            if(which==0){try{Features.done(a,item.id,!item.done);arriving=item.id;render();sync();}catch(Exception error){note("Could not save the change on this phone. Try again.","alert",true);}}
            else if(which==1)edit(item);else delete(item);
        }).setNegativeButton("Cancel",null).show();
    }

    void edit(FeatureBoard.Item item){
        LinearLayout box=ui.column();box.setPadding(ui.dp(20),ui.dp(8),ui.dp(20),0);
        EditText name=ui.field("Feature name",item.title);name.setContentDescription("Feature name");name.setFilters(new InputFilter[]{new InputFilter.LengthFilter(FeatureBoard.TITLE_MAX)});name.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);box.addView(name);ui.space(box,10);
        EditText detail=ui.field("Details (optional)",item.detail);detail.setContentDescription("Details");detail.setSingleLine(false);detail.setMaxLines(5);detail.setGravity(Gravity.TOP);detail.setFilters(new InputFilter[]{new InputFilter.LengthFilter(FeatureBoard.DETAIL_MAX)});detail.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_MULTI_LINE|InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);box.addView(detail);ui.space(box,6);
        final String[] chosen={item.area};HorizontalScrollView strip=new HorizontalScrollView(a);strip.setHorizontalScrollBarEnabled(false);LinearLayout row=ui.row();strip.addView(row);chips(row,chosen[0],value->chosen[0]=value);box.addView(strip);
        TextView problem=ui.small("");problem.setTextColor(ui.danger);problem.setVisibility(View.GONE);problem.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);box.addView(problem,MainParts.params(ui,-1,-2,4,4,4,0));
        AlertDialog editor=new AlertDialog.Builder(a).setTitle("Edit feature").setView(box).setPositiveButton("Save",null).setNegativeButton("Cancel",null).create();
        editor.setOnShowListener(d->editor.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{
            if(FeatureBoard.title(name.getText().toString())==null){problem.setVisibility(View.VISIBLE);AppUi.update(problem,"Enter a feature name.");return;}
            try{Features.edit(a,item.id,name.getText().toString(),detail.getText().toString(),chosen[0]);editor.dismiss();render();sync();}
            catch(Exception error){problem.setVisibility(View.VISIBLE);AppUi.update(problem,"Could not save on this phone. Your text is still here.");}
        }));
        editor.show();
    }

    void delete(FeatureBoard.Item item){
        new AlertDialog.Builder(a).setTitle("Delete this feature?").setMessage("“"+item.title+"” is removed from the checklist here and on the dashboard.").setPositiveButton("Delete",(d,w)->{
            try{Features.delete(a,item.id);render();openHolder.announceForAccessibility(item.title+" deleted");sync();}catch(Exception error){note("Could not save the change on this phone. Try again.","alert",true);}
        }).setNegativeButton("Cancel",null).show();
    }

    /** Rejected changes stay on the phone until the owner sends them again or discards them. */
    void review(){
        List<FeatureBoard.Change> rows;try{rows=Features.review(a);}catch(Exception error){note("Could not read the saved changes.","alert",true);return;}if(rows.isEmpty())return;
        Map<String,String> names=new HashMap<>();try{for(FeatureBoard.Item item:Features.items(Features.cached(a)))names.put(item.id,item.title);}catch(Exception ignored){}
        StringBuilder text=new StringBuilder();
        for(FeatureBoard.Change ch:rows){String name=ch.title!=null?ch.title:names.containsKey(ch.target)?names.get(ch.target):"a feature";text.append("create".equals(ch.op)?"Add “"+name+"”":"delete".equals(ch.op)?"Delete “"+name+"”":"Change “"+name+"”");if(!ch.error.isEmpty())text.append("\n").append(ch.error);text.append("\n\n");}
        new AlertDialog.Builder(a).setTitle(rows.size()==1?"1 change needs review":rows.size()+" changes need review").setMessage(text.toString().trim())
            .setPositiveButton("Try again",(d,w)->{try{Features.resolve(a,true);sync();}catch(Exception error){note("Could not update the saved changes.","alert",true);}})
            .setNeutralButton("Discard",(d,w)->new AlertDialog.Builder(a).setTitle("Discard these changes?").setMessage("They have not reached the server and will be removed from this phone.").setPositiveButton("Discard",(x,y)->{try{Features.resolve(a,false);render();}catch(Exception error){note("Could not update the saved changes.","alert",true);}}).setNegativeButton("Keep",null).show())
            .setNegativeButton("Keep",null).show();
    }

    /** One row: an open ring or a green check, title, details, area with finish date, and a 48 dp delete cross. */
    private final class Row {
        final FeatureBoard.Item item;final LinearLayout box=ui.column(),line=ui.row();final ImageView dot=new ImageView(a);final TextView label=new TextView(a);boolean on,moving;
        Row(FeatureBoard.Item item,boolean separated){
            this.item=item;on=item.done;if(separated)ui.hairline(box,54,0,14);
            line.setTag("feature_row:"+item.id);line.setMinimumHeight(ui.dp(60));line.setPadding(ui.dp(14),ui.dp(8),ui.dp(2),ui.dp(8));line.addView(dot,new LinearLayout.LayoutParams(ui.dp(26),ui.dp(26)));
            LinearLayout words=ui.column();label.setText(item.title);label.setTextSize(16);label.setTypeface(AppUi.face(500));label.setIncludeFontPadding(false);label.setLineSpacing(0,1.12f);words.addView(label);
            if(!item.detail.isEmpty()){TextView detail=ui.type(item.detail,13,18,400,0,ui.muted);detail.setMaxLines(3);detail.setEllipsize(TextUtils.TruncateAt.END);words.addView(detail,MainParts.params(ui,-1,-2,0,4,0,0));}
            LinearLayout meta=ui.row();meta.addView(ui.type(meta(),12,16,500,0,item.done?ui.success:ui.muted));if(item.pending)meta.addView(ui.savedChip("Saved on phone"),MainParts.params(ui,-2,-2,8,0,0,0));words.addView(meta,MainParts.params(ui,-1,-2,0,5,0,0));
            words.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);line.addView(words,MainParts.weighted(ui,1,14,0,4,0));
            ImageButton remove=new ImageButton(a);remove.setImageDrawable(ui.glyph("x",ui.muted,20));remove.setScaleType(ImageView.ScaleType.CENTER);remove.setBackground(ui.pressable(null,24));remove.setContentDescription("Delete "+item.title);remove.setTag("feature_delete:"+item.id);remove.setOnClickListener(v->delete(item));line.addView(remove,new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));
            box.addView(line);set(on,false);
        }
        String meta(){String where=FeatureBoard.areaName(item.area);return item.done&&item.doneAt>0?where+" · Finished "+AppUi.date((long)(item.doneAt*1000)):where;}
        void set(boolean value,boolean animate){
            on=value;label.setTextColor(ui.text);dot.setScaleType(ImageView.ScaleType.CENTER);
            if(value){dot.setBackground(ui.outline(ui.success,13,0,0));dot.setImageDrawable(ui.glyph("check",ui.surface,16));}else{dot.setBackground(ui.outline(0,13,ui.strokeStrong,1.5f));dot.setImageDrawable(null);}
            line.setContentDescription(item.title+(item.detail.isEmpty()?"":", "+item.detail)+", "+meta()+(value?", finished":", to build"));
        }
    }
}
