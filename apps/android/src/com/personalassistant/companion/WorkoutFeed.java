package com.personalassistant.companion;

import android.app.AlertDialog;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.net.Uri;
import android.text.InputFilter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** The league's shared workout check-ins. Progress-vault photos never use these routes. */
final class WorkoutFeed {
    private static final String PATH="workout/friends/feed";
    private static final String MOBILE_PREFIX="/groceries/v1/mobile/";
    private static final DateTimeFormatter DATE=DateTimeFormatter.ofPattern("EEE d MMM · HH:mm");
    private static final ExecutorService PHOTOS=Executors.newFixedThreadPool(3);
    private final MainActivity a;
    private final AppUi ui;

    WorkoutFeed(WorkoutScreen screen){a=screen.a;ui=screen.ui;}

    void open(){
        WorkoutViews.Sheet sheet=new WorkoutViews.Sheet(ui,"Workout feed");
        sheet.body.addView(ui.detail("Workout check-ins shared by your league."),WorkoutViews.gap(ui,10));
        LinearLayout posts=ui.column(),footer=ui.column();
        sheet.body.addView(posts);
        sheet.body.addView(footer);
        sheet.show();
        load(sheet,posts,footer,"");
    }

    private void load(WorkoutViews.Sheet sheet,LinearLayout posts,LinearLayout footer,String cursor){
        footer.removeAllViews();
        footer.addView(ui.detail("Loading check-ins…"));
        new Thread(()->{
            try{
                JSONObject page=(JSONObject)Cloud.call(a,PATH+"?limit=12"+(cursor.isEmpty()?"":"&before="+Uri.encode(cursor)),null,true);
                JSONArray items=page.getJSONArray("items");
                a.runOnUiThread(()->{
                    if(!sheet.dialog.isShowing())return;
                    footer.removeAllViews();
                    for(int i=0;i<items.length();i++){
                        JSONObject item=items.optJSONObject(i);
                        if(item!=null)posts.addView(card(sheet,item),WorkoutViews.gap(ui,14));
                    }
                    if(posts.getChildCount()==0)footer.addView(ui.detail("No shared workouts yet."));
                    if(!page.isNull("next_cursor")){
                        String next=page.optString("next_cursor");
                        if(!next.isEmpty())footer.addView(ui.quietButton("Older workouts",()->load(sheet,posts,footer,next)));
                    }
                });
            }catch(Exception error){
                a.runOnUiThread(()->{
                    if(!sheet.dialog.isShowing())return;
                    footer.removeAllViews();
                    footer.addView(ui.detail("Couldn't load the workout feed."),WorkoutViews.gap(ui,8));
                    footer.addView(ui.quietButton("Retry",()->load(sheet,posts,footer,cursor)));
                });
            }
        }).start();
    }

    private LinearLayout card(WorkoutViews.Sheet sheet,JSONObject item){
        LinearLayout card=WorkoutViews.card(ui);
        JSONObject athlete=item.optJSONObject("athlete");
        card.addView(ui.type(athlete==null?"Athlete":athlete.optString("name","Athlete"),14,19,650,0,ui.accent));
        card.addView(ui.type(item.optString("name","Workout"),22,29,750,0,ui.text),WorkoutViews.gap(ui,3));
        String duration=item.optInt("duration_seconds")>0?" · "+Math.max(1,item.optInt("duration_seconds")/60)+" min":"";
        card.addView(ui.detail(date(item.optString("started_at"))+duration),WorkoutViews.gap(ui,8));
        long id=item.optLong("id",-1);
        if(id>=0&&(MOBILE_PREFIX+PATH+"/"+id+"/photo").equals(item.optString("photo_url"))){
            ImageView image=new ImageView(a);
            image.setContentDescription("Workout check-in photo");
            image.setScaleType(ImageView.ScaleType.CENTER_CROP);
            image.setBackground(ui.outline(ui.surfaceAlt,14,0,0));
            image.setClipToOutline(true);
            card.addView(image,MainParts.params(ui,-1,ui.dp(260),0,0,0,10));
            PHOTOS.execute(()->{
                try{
                    byte[] photo=Cloud.raw(a,"GET",PATH+"/"+id+"/photo",null,null);
                    Bitmap bitmap=BitmapFactory.decodeByteArray(photo,0,photo.length);
                    if(bitmap!=null)a.runOnUiThread(()->{
                        if(sheet.dialog.isShowing())image.setImageBitmap(bitmap);
                        else bitmap.recycle();
                    });
                }catch(Exception error){a.runOnUiThread(()->image.setVisibility(ImageView.GONE));}
            });
        }
        JSONArray exercises=item.optJSONArray("exercises");
        if(exercises!=null)for(int i=0;i<exercises.length();i++){
            JSONObject exercise=exercises.optJSONObject(i);
            if(exercise==null)continue;
            card.addView(ui.type(exercise.optString("name","Exercise"),14,20,650,0,ui.text),WorkoutViews.gap(ui,2));
            String sets=describeSets(exercise.optJSONArray("sets"));
            if(!sets.isEmpty())card.addView(ui.detail(sets),WorkoutViews.gap(ui,7));
        }
        if(id>=0){
            int count=item.optInt("comment_count");
            Button comments=ui.quietButton(commentLabel(count),()->{});
            comments.setOnClickListener(v->new Comments(id,athlete==null?"":athlete.optString("id"),count,comments).open());
            card.addView(comments,WorkoutViews.gap(ui,8));
        }
        return card;
    }

    private String describeSets(JSONArray sets){
        ArrayList<String> labels=new ArrayList<>();
        for(int i=0;sets!=null&&i<sets.length();i++){
            JSONObject s=sets.optJSONObject(i);
            if(s==null)continue;
            ArrayList<String> fields=new ArrayList<>();
            if(!s.isNull("weight_kg"))fields.add(WorkoutUnits.load(a,s.optDouble("weight_kg")));
            if(!s.isNull("reps"))fields.add(s.optInt("reps")+" reps");
            if(!s.isNull("distance_m"))fields.add(WorkoutUnits.distance(a,s.optDouble("distance_m")));
            if(!s.isNull("seconds"))fields.add(s.optLong("seconds")+" s");
            if(fields.isEmpty())continue;
            String label=String.join(" × ",fields);
            if("warmup".equals(s.optString("kind")))label+=" (warm-up)";
            labels.add(label);
        }
        return String.join(" · ",labels);
    }

    private static String date(String raw){
        try{return OffsetDateTime.parse(raw).atZoneSameInstant(ZoneId.systemDefault()).format(DATE);}
        catch(Exception ignored){return raw;}
    }

    private static String commentLabel(int count){
        return count==0?"Comments":count+(count==1?" comment":" comments");
    }

    private final class Comments {
        private final String endpoint,postOwner;
        private final Button badge;
        private final WorkoutViews.Sheet sheet;
        private LinearLayout list,footer;
        private EditText input;
        private Button send;
        private TextView status;
        private int count;
        private String lastText="",lastId="";

        Comments(long id,String postOwner,int count,Button badge){
            endpoint=PATH+"/"+id+"/comments";
            this.postOwner=postOwner;this.count=count;this.badge=badge;
            sheet=new WorkoutViews.Sheet(ui,"Comments");
        }

        void open(){
            list=ui.column();footer=ui.column();
            sheet.body.addView(list);
            sheet.body.addView(footer,WorkoutViews.gap(ui,12));
            LinearLayout composer=ui.row();
            input=ui.field("Add a comment","");
            input.setSingleLine(false);
            input.setMaxLines(4);
            input.setFilters(new InputFilter[]{new InputFilter.LengthFilter(1000)});
            composer.addView(input,MainParts.weighted(ui,1,0,0,8,0));
            send=ui.primaryButton("Post",this::post);
            composer.addView(send);
            sheet.body.addView(composer);
            status=ui.detail("");
            sheet.body.addView(status,WorkoutViews.gap(ui,6));
            sheet.show();
            load("");
        }

        private void load(String cursor){
            if(cursor.isEmpty())list.removeAllViews();
            footer.removeAllViews();
            footer.addView(ui.detail("Loading comments…"));
            new Thread(()->{
                try{
                    JSONObject page=(JSONObject)Cloud.call(a,endpoint+"?limit=30"+(cursor.isEmpty()?"":"&after="+Uri.encode(cursor)),null,true);
                    JSONArray items=page.getJSONArray("items");
                    a.runOnUiThread(()->{
                        if(!sheet.dialog.isShowing())return;
                        footer.removeAllViews();
                        for(int i=0;i<items.length();i++){
                            JSONObject row=items.optJSONObject(i);
                            if(row!=null)list.addView(comment(row),WorkoutViews.gap(ui,8));
                        }
                        if(list.getChildCount()==0)footer.addView(ui.detail("No comments yet."));
                        if(!page.isNull("next_cursor")){
                            String next=page.optString("next_cursor");
                            if(!next.isEmpty())footer.addView(ui.quietButton("More comments",()->load(next)));
                        }
                    });
                }catch(Exception error){a.runOnUiThread(()->{
                    if(!sheet.dialog.isShowing())return;
                    footer.removeAllViews();
                    footer.addView(ui.detail("Couldn't load comments."));
                    footer.addView(ui.quietButton("Retry",()->load(cursor)));
                });}
            }).start();
        }

        private LinearLayout comment(JSONObject row){
            LinearLayout card=WorkoutViews.card(ui);
            JSONObject author=row.optJSONObject("author");
            card.addView(ui.type(author==null?"Athlete":author.optString("name","Athlete"),14,19,650,0,ui.accent));
            card.addView(ui.type(row.optString("text"),15,21,400,0,ui.text),WorkoutViews.gap(ui,3));
            card.addView(ui.detail(Instant.ofEpochSecond(row.optLong("created_at")).atZone(ZoneId.systemDefault()).format(DATE)));
            long id=row.optLong("id",-1);
            if(id>=0&&("owner".equals(postOwner)||author!=null&&"owner".equals(author.optString("id")))){
                card.addView(ui.quietButton("Delete",()->new AlertDialog.Builder(a).setTitle("Delete comment?")
                        .setPositiveButton("Delete",(d,w)->remove(id,card)).setNegativeButton("Cancel",null).show()));
            }
            return card;
        }

        private void post(){
            String words=input.getText().toString().trim();
            if(words.isEmpty())return;
            if(!words.equals(lastText)){lastText=words;lastId=WorkoutStore.id();}
            String requestId=lastId;
            send.setEnabled(false);input.setEnabled(false);status.setText("Posting…");
            new Thread(()->{
                try{
                    Cloud.call(a,endpoint,new JSONObject().put("text",words).put("client_id",requestId),true);
                    a.runOnUiThread(()->{
                        badge.setText(commentLabel(++count));
                        if(!sheet.dialog.isShowing())return;
                        lastText="";lastId="";
                        input.setText("");status.setText("");input.setEnabled(true);send.setEnabled(true);
                        load("");
                    });
                }catch(Exception error){a.runOnUiThread(()->{
                    if(!sheet.dialog.isShowing())return;
                    status.setText("Couldn't post. Tap Post to retry.");
                    input.setEnabled(true);send.setEnabled(true);
                });}
            }).start();
        }

        private void remove(long id,LinearLayout card){
            new Thread(()->{
                try{
                    Cloud.raw(a,"DELETE",endpoint+"/"+id,null,null);
                    a.runOnUiThread(()->{
                        badge.setText(commentLabel(count=Math.max(0,count-1)));
                        if(!sheet.dialog.isShowing())return;
                        list.removeView(card);
                        if(list.getChildCount()==0)load("");
                    });
                }catch(Exception error){a.runOnUiThread(()->{
                    if(sheet.dialog.isShowing())status.setText("Couldn't delete the comment.");
                });}
            }).start();
        }
    }
}
