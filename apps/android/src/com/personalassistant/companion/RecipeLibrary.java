package com.personalassistant.companion;

import android.app.*;
import android.content.Context;
import android.os.Build;
import android.text.InputType;
import android.view.*;
import android.view.accessibility.*;
import android.view.inputmethod.InputMethodManager;
import android.widget.*;
import org.json.*;
import java.util.*;
import java.util.function.Consumer;

/** Cached recipe browsing and selected ingredients use the same stable offline outbox. One sheet walks list, recipe and import. */
final class RecipeLibrary {
    static void show(Activity activity,Runnable changed,Consumer<String> importer,Runnable web){new Sheet(activity,changed,importer,web).open();}

    private static final class Sheet {
        final Activity activity;final AppUi ui;final Runnable changed,web;final Consumer<String> importer;final Dialog dialog;final LinkedHashMap<String,JSONObject> recipes=new LinkedHashMap<>();
        FrameLayout stage;View back;EditText importField;String draft="";int depth;

        Sheet(Activity activity,Runnable changed,Consumer<String> importer,Runnable web){
            this.activity=activity;this.changed=changed;this.importer=importer;this.web=web;ui=new AppUi(activity);dialog=ui.sheet();
            try{
                JSONArray cached=Cloud.cached(activity).optJSONArray("recipes");
                if(cached!=null)for(int i=0;i<cached.length();i++){JSONObject recipe=cached.getJSONObject(i);recipes.put(recipe.optString("id",Integer.toString(i)),recipe);}
                JSONArray queued=Cloud.queue(activity);
                for(int i=0;i<queued.length();i++){
                    JSONObject change=queued.getJSONObject(i);
                    if("recipe_save".equals(change.optString("operation"))){JSONObject recipe=new JSONObject(change.getJSONObject("recipe").toString());recipe.put("pending",true);recipes.put(recipe.getString("id"),recipe);}
                    else if("recipe_delete".equals(change.optString("operation")))recipes.remove(change.optString("target"));
                }
            }catch(Exception ignored){}
        }

        void open(){
            LinearLayout root=ui.column();root.setFitsSystemWindows(true);root.setBackground(ui.pageBackground());
            LinearLayout bar=ui.row();bar.setPadding(ui.dp(17),ui.dp(4),ui.dp(8),0);
            back=ui.iconButton("back","Back",this::list);bar.addView(back,new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));
            bar.addView(new View(activity),new LinearLayout.LayoutParams(0,1,1));
            Button close=ui.ghostButton("Close",dialog::dismiss);close.setPadding(ui.dp(12),0,ui.dp(12),0);bar.addView(close);
            stage=new FrameLayout(activity);root.addView(bar);root.addView(stage,new LinearLayout.LayoutParams(-1,0,1));
            dialog.setContentView(root);
            if(Build.VERSION.SDK_INT>=29)dialog.getWindow().setNavigationBarContrastEnforced(false);
            dialog.setOnKeyListener((d,code,event)->{if(code!=KeyEvent.KEYCODE_BACK||depth==0)return false;if(event.getAction()==KeyEvent.ACTION_UP)list();return true;});
            list();dialog.show();
        }

        private void go(View page,int direction){stage.removeAllViews();stage.addView(page,new FrameLayout.LayoutParams(-1,-1));AppUi.slide(page,direction);}
        private void level(int value){depth=value;back.setVisibility(value==0?View.GONE:View.VISIBLE);}
        private void stash(){if(importField==null)return;draft=importField.getText().toString();((InputMethodManager)activity.getSystemService(Context.INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(importField.getWindowToken(),0);importField=null;}
        private void say(TextView line,String message){line.setVisibility(View.VISIBLE);AppUi.update(line,message);}
        private TextView problem(){TextView line=ui.small("");line.setTextColor(ui.danger);line.setVisibility(View.GONE);line.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);line.setPadding(ui.dp(4),0,ui.dp(4),ui.dp(8));return line;}

        /** Scrolling body on the page gutter, with an optional action bar pinned underneath. */
        private View page(LinearLayout content,View... footer){
            LinearLayout page=ui.column();ScrollView scroll=new ScrollView(activity);
            scroll.setPadding(ui.dp(20),ui.dp(4),ui.dp(20),ui.dp(24));scroll.setClipToPadding(false);scroll.setVerticalFadingEdgeEnabled(true);scroll.setFadingEdgeLength(ui.dp(20));scroll.addView(content);
            page.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
            if(footer.length>0){LinearLayout bottom=ui.column();bottom.setPadding(ui.dp(20),ui.dp(8),ui.dp(20),ui.dp(16));for(View view:footer)bottom.addView(view,new LinearLayout.LayoutParams(-1,-2));page.addView(bottom);}
            return page;
        }
        private void rule(LinearLayout parent,int inset){View line=new View(activity);line.setBackgroundColor(ui.stroke);LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,Math.max(1,ui.dp(1)));p.leftMargin=ui.dp(inset);parent.addView(line,p);}
        private static void silence(View... views){for(View view:views)view.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);}
        private static ArrayList<JSONObject> ingredients(JSONObject recipe){
            ArrayList<JSONObject> list=new ArrayList<>();JSONArray rows=recipe.optJSONArray("ingredients");
            if(rows!=null)for(int i=0;i<rows.length();i++){JSONObject ingredient=rows.optJSONObject(i);if(ingredient!=null&&!ingredient.optString("name").trim().isEmpty())list.add(ingredient);}
            return list;
        }

        void list(){
            stash();level(0);
            LinearLayout content=ui.column();
            content.addView(ui.header("Recipes",recipes.isEmpty()?null:"Choose a recipe, then select the ingredients you need. Cached recipes work offline."));ui.space(content,18);
            if(recipes.isEmpty())content.addView(ui.empty("recipe","No recipes saved yet","Import recipe text, or share a recipe to Assistant Companion from another app.","Import text",this::importPage));
            else{
                LinearLayout card=ui.rowsCard();int n=0;
                for(JSONObject recipe:recipes.values()){if(n++>0)rule(card,66);card.addView(recipeRow(recipe));}
                content.addView(card);content.addView(ui.quietButton("Import text",this::importPage),new LinearLayout.LayoutParams(-1,-2));
            }
            ui.space(content,4);content.addView(ui.ghostButton("Open web library",()->{dialog.dismiss();web.run();}),new LinearLayout.LayoutParams(-1,-2));
            go(page(content),-1);
        }

        private View recipeRow(JSONObject recipe){
            String title=recipe.optString("title","Recipe");int count=ingredients(recipe).size();boolean pending=recipe.optBoolean("pending");String sub=count==1?"1 ingredient":count+" ingredients";
            LinearLayout row=ui.row();row.setMinimumHeight(ui.dp(68));row.setPadding(ui.dp(12),ui.dp(10),ui.dp(12),ui.dp(10));row.setBackground(ui.pressable(null,18));row.setClickable(true);row.setFocusable(true);AppUi.press(row);
            int[] tone=ui.iconTone("recipe");ImageView tile=new ImageView(activity);tile.setImageDrawable(ui.glyph("recipe",tone[0],22));tile.setScaleType(ImageView.ScaleType.CENTER);tile.setBackground(ui.outline(tone[1],12,0,0));row.addView(tile,new LinearLayout.LayoutParams(ui.dp(40),ui.dp(40)));
            LinearLayout words=ui.column();TextView name=ui.type(title,16,22,500,0,ui.text);name.setMaxLines(2);name.setEllipsize(android.text.TextUtils.TruncateAt.END);words.addView(name);
            LinearLayout detail=ui.row();detail.addView(ui.small(sub));
            if(pending){AppUi.StatusChip chip=ui.statusChip("Saved on phone","warning");chip.setCompoundDrawablesWithIntrinsicBounds(ui.glyph("phone-saved",ui.warning,14),null,null,null);LinearLayout.LayoutParams cp=new LinearLayout.LayoutParams(-2,-2);cp.leftMargin=ui.dp(8);detail.addView(chip,cp);}
            words.addView(detail);LinearLayout.LayoutParams wp=new LinearLayout.LayoutParams(0,-2,1);wp.leftMargin=ui.dp(14);row.addView(words,wp);
            AppUi.Icon arrow=new AppUi.Icon(activity,"arrow",ui.muted);LinearLayout.LayoutParams ap=new LinearLayout.LayoutParams(ui.dp(18),ui.dp(18));ap.leftMargin=ui.dp(8);row.addView(arrow,ap);
            silence(tile,words,arrow);row.setContentDescription(title+", "+sub+(pending?", saved on phone":""));
            row.setTag("recipe_"+recipe.optString("id"));row.setOnClickListener(v->detail(recipe));return row;
        }

        void detail(JSONObject recipe){
            stash();level(1);
            ArrayList<JSONObject> items=ingredients(recipe);ArrayList<Ingredient> checks=new ArrayList<>();TextView summary=ui.small("");
            LinearLayout content=ui.column();content.addView(ui.title(recipe.optString("title","Recipe")));ui.space(content,6);
            content.addView(ui.detail(items.isEmpty()?"This recipe has no ingredients to add.":"Uncheck anything you already have."));ui.space(content,18);
            if(!items.isEmpty()){
                LinearLayout head=ui.row();head.setPadding(ui.dp(4),0,ui.dp(4),ui.dp(8));head.addView(ui.label("Ingredients"),new LinearLayout.LayoutParams(0,-2,1));head.addView(summary);content.addView(head);
                LinearLayout card=ui.rowsCard();
                for(int i=0;i<items.size();i++){
                    JSONObject ingredient=items.get(i);Ingredient row=new Ingredient(ui,(ingredient.optString("quantity")+" "+ingredient.optString("name")).trim(),()->count(summary,checks));
                    row.setTag("recipe_ingredient_"+i);if(i>0)rule(card,52);card.addView(row);checks.add(row);
                }
                content.addView(card);summary.setText(checks.size()+" of "+checks.size()+" selected");
            }
            String instructions=recipe.optString("instructions","");
            if(!instructions.isEmpty()){
                LinearLayout holder=ui.column();LinearLayout panel=ui.panel();TextView directions=ui.body(instructions);directions.setTextIsSelectable(true);panel.addView(directions);panel.setVisibility(View.GONE);
                Button toggle=ui.ghostButton("Show directions",()->{});toggle.setCompoundDrawablesWithIntrinsicBounds(null,null,ui.glyph("down",ui.accent,18),null);toggle.setCompoundDrawablePadding(ui.dp(4));toggle.setPadding(ui.dp(4),0,ui.dp(12),0);
                toggle.setOnClickListener(v->{boolean opening=panel.getVisibility()!=View.VISIBLE;AppUi.update(toggle,opening?"Hide directions":"Show directions");toggle.setCompoundDrawablesWithIntrinsicBounds(null,null,ui.glyph(opening?"up":"down",ui.accent,18),null);if(opening)AppUi.expand(panel);else AppUi.collapse(panel,null);});
                holder.addView(toggle,new LinearLayout.LayoutParams(-2,-2));holder.addView(panel);content.addView(holder);
            }
            TextView feedback=problem();Button add=ui.button("Add selected to list",true,()->{});add.setTag("recipe_add_selected");add.setEnabled(!items.isEmpty());add.setOnClickListener(v->add(items,checks,add,feedback));
            go(page(content,feedback,add),1);
        }
        private void count(TextView summary,ArrayList<Ingredient> checks){int on=0;for(Ingredient row:checks)if(row.isChecked())on++;AppUi.update(summary,on+" of "+checks.size()+" selected");}

        private void add(ArrayList<JSONObject> items,ArrayList<Ingredient> checks,Button add,TextView feedback){
            if(!add.isEnabled())return;add.setEnabled(false);JSONArray selected=new JSONArray();
            for(int i=0;i<checks.size();i++)if(checks.get(i).isChecked())try{JSONObject ingredient=items.get(i);selected.put(new JSONObject().put("name",ingredient.getString("name")).put("quantity",ingredient.optString("quantity","")));}catch(Exception ignored){}
            if(selected.length()==0){say(feedback,"Select at least one ingredient.");add.setEnabled(true);return;}
            try{Cloud.enqueue(activity,new JSONObject().put("operation","add").put("items",selected));}
            catch(Exception error){say(feedback,"Could not save ingredients on this phone. Try again.");add.setEnabled(true);return;}
            Toast.makeText(activity,selected.length()+" ingredients saved to your list",Toast.LENGTH_SHORT).show();changed.run();list();
        }

        void importPage(){
            stash();level(1);
            LinearLayout content=ui.column();content.addView(ui.title("Import recipe"));ui.space(content,6);
            content.addView(ui.detail("Paste ingredients and directions, or recipe JSON. Import needs an internet connection."));ui.space(content,18);
            EditText text=ui.field("Recipe text",draft);text.setSingleLine(false);text.setMinLines(8);text.setGravity(Gravity.TOP);text.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_MULTI_LINE);text.setTag("recipe_import_text");importField=text;content.addView(text,new LinearLayout.LayoutParams(-1,-2));
            TextView error=problem();
            Button submit=ui.button("Preview import",true,()->{
                String value=text.getText().toString().trim();
                if(value.isEmpty()){say(error,"Paste a recipe first.");return;}
                if(!VoiceOutbox.networkReady(activity)){say(error,"Connect to the internet to import. Your text stays here.");return;}
                draft="";dialog.dismiss();importer.accept(value);
            });
            submit.setTag("recipe_import_submit");go(page(content,error,submit),1);
        }
    }

    /** Checkbox row: the whole row toggles, and it reports itself to accessibility as a checkbox named after the ingredient. */
    private static final class Ingredient extends LinearLayout implements Checkable {
        final AppUi ui;final AppUi.CheckDot dot;final AppUi.StrikeText label;final Runnable changed;boolean on=true;
        Ingredient(AppUi ui,String text,Runnable changed){
            super(ui.context);this.ui=ui;this.changed=changed;setOrientation(HORIZONTAL);setGravity(Gravity.CENTER_VERTICAL);setMinimumHeight(ui.dp(56));setPadding(ui.dp(12),ui.dp(6),ui.dp(14),ui.dp(6));
            setBackground(ui.pressable(null,18));setClickable(true);setFocusable(true);AppUi.press(this);
            dot=new AppUi.CheckDot(ui);dot.set(true,false);addView(dot,new LayoutParams(ui.dp(26),ui.dp(26)));
            label=new AppUi.StrikeText(ui.context,ui.muted);label.setText(text);label.setTextSize(16);label.setTypeface(AppUi.face(500));label.setTextColor(ui.text);label.setIncludeFontPadding(false);
            LayoutParams lp=new LayoutParams(0,-2,1);lp.leftMargin=ui.dp(14);addView(label,lp);
            setContentDescription(text);label.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);setOnClickListener(v->toggle());
        }
        @Override public boolean isChecked(){return on;}
        @Override public void toggle(){setChecked(!on);}
        @Override public void setChecked(boolean value){if(value==on)return;on=value;dot.set(value,true);label.strike(!value,true);label.setTextColor(value?ui.text:ui.muted);changed.run();}
        @Override public CharSequence getAccessibilityClassName(){return CheckBox.class.getName();}
        @Override public void onInitializeAccessibilityNodeInfo(AccessibilityNodeInfo info){super.onInitializeAccessibilityNodeInfo(info);info.setCheckable(true);info.setChecked(on);}
        @Override public void onInitializeAccessibilityEvent(AccessibilityEvent event){super.onInitializeAccessibilityEvent(event);event.setChecked(on);}
    }
}
