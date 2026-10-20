package com.personalassistant.companion;

import android.app.*;
import android.content.*;
import android.graphics.*;
import android.text.InputType;
import android.view.*;
import android.widget.*;
import org.json.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.*;

/**
 * Read-mostly view of the laptop calendar: a month for orientation, then what's coming up with when each reminder fires and
 * whether it has reached the cloud that sends it. Tapping a day shows it and can queue one entry; the laptop adds it with the
 * owner's reminder rules, so nothing here sets reminders.
 */
final class CalendarScreen {
    static final DateTimeFormatter DAY=DateTimeFormatter.ofPattern("EEEE d MMMM"),SHORT=DateTimeFormatter.ofPattern("EEE d MMM"),TIME=DateTimeFormatter.ofPattern("HH:mm"),MONTH=DateTimeFormatter.ofPattern("MMMM yyyy");
    final MainActivity activity;final AppUi ui;final LinearLayout page;JSONObject data=new JSONObject();boolean loading;String error="";YearMonth month=YearMonth.now();
    CalendarScreen(MainActivity a,AppUi u,LinearLayout p){activity=a;ui=u;page=p;try{data=new JSONObject(Cloud.prefs(a).getString("calendar_snapshot","{}"));}catch(Exception ignored){}render();}

    void refresh(){if(loading)return;if(!activity.paired()){render();return;}loading=true;render();new Thread(()->{JSONObject result=null;String failure="";try{result=(JSONObject)Cloud.call(activity,"calendar",null,true);}catch(Exception e){failure=e instanceof Cloud.HttpError&&((Cloud.HttpError)e).status==404?"Your server doesn't have the calendar yet.":"Couldn't reach your server. Showing the last saved calendar.";}
        JSONObject fresh=result;String message=failure;activity.runOnUiThread(()->{loading=false;error=message;if(fresh!=null){data=fresh;Cloud.prefs(activity).edit().putString("calendar_snapshot",fresh.toString()).apply();}render();});}).start();}

    ZoneId zone(){try{return ZoneId.of(data.optString("timezone",ZoneId.systemDefault().getId()));}catch(Exception e){return ZoneId.systemDefault();}}
    LocalDate today(){return LocalDate.now(zone());}
    List<JSONObject> events(){ArrayList<JSONObject> out=new ArrayList<>();JSONArray all=data.optJSONArray("events");for(int i=0;all!=null&&i<all.length();i++){JSONObject e=all.optJSONObject(i);if(e!=null)out.add(e);}return out;}
    static LocalDate first(JSONObject e,ZoneId z){return e.optBoolean("all_day")?LocalDate.parse(e.optString("start_date")):OffsetDateTime.parse(e.optString("start")).atZoneSameInstant(z).toLocalDate();}
    /** Last day an entry covers; all-day end dates are exclusive. */
    static LocalDate last(JSONObject e,ZoneId z){if(e.optBoolean("all_day"))return LocalDate.parse(e.optString("end_date")).minusDays(1);ZonedDateTime end=OffsetDateTime.parse(e.optString("end")).atZoneSameInstant(z);return end.toLocalTime().equals(LocalTime.MIDNIGHT)?end.toLocalDate().minusDays(1):end.toLocalDate();}
    List<JSONObject> on(LocalDate day){ArrayList<JSONObject> out=new ArrayList<>();ZoneId z=zone();for(JSONObject e:events())try{if(!day.isBefore(first(e,z))&&!day.isAfter(last(e,z)))out.add(e);}catch(Exception ignored){}return out;}
    boolean birthday(JSONObject e){return "birthday".equals(e.optString("kind"));}
    int tint(JSONObject e){return birthday(e)?ui.aurora[2]:ui.accent;}

    void render(){page.removeAllViews();
        page.addView(ui.type("Calendar",13,18,500,0,ui.muted),MainParts.params(ui,-1,-2,0,0,0,2));
        LinearLayout head=ui.row();TextView title=ui.type(month.format(MONTH),28,34,700,-.025f,ui.text);head.addView(title,new LinearLayout.LayoutParams(0,-2,1));
        head.addView(ui.iconButton("back","Previous month",()->{month=month.minusMonths(1);render();}),new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));
        ImageButton next=ui.iconButton("arrow","Next month",()->{month=month.plusMonths(1);render();});head.addView(next,new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));page.addView(head,MainParts.params(ui,-1,-2,0,0,0,8));
        if(!activity.paired()){page.addView(ui.detail("Connect your phone to see your assistant's calendar."),MainParts.params(ui,-1,-2,0,8,0,0));return;}
        LinearLayout card=ui.card();card.setPadding(ui.dp(10),ui.dp(12),ui.dp(10),ui.dp(10));MonthGrid grid=new MonthGrid();grid.setTag("calendar_month");card.addView(grid,new LinearLayout.LayoutParams(-1,ui.dp(6*44+22)));page.addView(card,MainParts.params(ui,-1,-2,0,0,0,18));
        requests();
        LocalDate today=today();ZoneId z=zone();TreeMap<LocalDate,List<JSONObject>> days=new TreeMap<>();
        for(JSONObject e:events())try{LocalDate start=first(e,z),end=last(e,z);if(end.isBefore(today))continue;LocalDate key=start.isBefore(today)?today:start;List<JSONObject> list=days.get(key);if(list==null)days.put(key,list=new ArrayList<>());list.add(e);}catch(Exception ignored){}
        LinearLayout r=ui.row();r.addView(ui.type("Coming up",18,24,700,0,ui.text),new LinearLayout.LayoutParams(0,-2,1));r.addView(ui.type(published(),12,16,500,0,stale()?ui.warning:ui.muted));page.addView(r,MainParts.params(ui,-1,-2,0,0,0,8));
        if(days.isEmpty())page.addView(ui.detail(loading?"Loading your calendar…":"Nothing coming up. Ask your assistant to add something, or tap a day."),MainParts.params(ui,-1,-2,0,4,0,12));
        int shown=0;for(Map.Entry<LocalDate,List<JSONObject>> d:days.entrySet()){if(shown>=40)break;dayHeader(page,d.getKey());for(JSONObject e:d.getValue()){page.addView(entry(e,true),MainParts.params(ui,-1,-2,0,0,0,8));shown++;}}
        if(!error.isEmpty())page.addView(ui.type(error,13,18,500,0,ui.warning),MainParts.params(ui,-1,-2,0,10,0,0));
    }
    String published(){double at=data.optDouble("published",0);if(at<=0)return loading?"Updating…":"";long minutes=Math.max(0,(System.currentTimeMillis()-(long)(at*1000))/60000);return loading?"Updating…":minutes<2?"Up to date":minutes<60?"Synced "+minutes+" min ago":"Synced "+(minutes/60)+" h ago";}
    /** The laptop publishes every half minute while it is awake; a much older view may miss recent changes. */
    boolean stale(){double at=data.optDouble("published",0);return at>0&&System.currentTimeMillis()-(long)(at*1000)>3*3600*1000L;}

    void dayHeader(LinearLayout parent,LocalDate day){long n=ChronoUnit.DAYS.between(today(),day);String when=n==0?"Today":n==1?"Tomorrow":n<7?"in "+n+" days":n<14?"in a week":"in "+(n/7)+" weeks";
        LinearLayout r=ui.row();r.addView(ui.type(day.format(DAY),13,18,600,0,ui.muted),new LinearLayout.LayoutParams(0,-2,1));r.addView(ui.type(when,12,16,500,0,ui.muted));parent.addView(r,MainParts.params(ui,-1,-2,4,8,4,6));}

    /** Entry card: a coloured edge, title, time and place, then its reminders and whether each has reached the cloud. */
    View entry(JSONObject e,boolean tappable){LinearLayout box=ui.row();box.setGravity(Gravity.TOP);box.setPadding(0,0,ui.dp(14),0);box.setBackground(tappable?ui.pressable(ui.outline(ui.surface,18,ui.stroke,1),18):ui.outline(ui.surface,18,ui.stroke,1));box.setClipToOutline(true);
        View edge=new View(activity);edge.setBackgroundColor(tint(e));box.addView(edge,new LinearLayout.LayoutParams(ui.dp(4),-1));
        LinearLayout words=ui.column();words.setPadding(ui.dp(12),ui.dp(10),0,ui.dp(10));
        LinearLayout top=ui.row();if(birthday(e)){top.addView(MainParts.icon(ui,"cake",tint(e)),MainParts.params(ui,ui.dp(18),ui.dp(18),0,0,6,0));}
        top.addView(ui.type(e.optString("title"),15,20,600,0,ui.text),new LinearLayout.LayoutParams(0,-2,1));words.addView(top);
        words.addView(ui.type(when(e),13,18,400,0,ui.muted));
        String reminders=reminderLine(e);int[] tone=reminderTone(e);LinearLayout rr=ui.row();rr.addView(MainParts.icon(ui,tone[1]==1?"alert":"bell",tone[0]),MainParts.params(ui,ui.dp(14),ui.dp(14),0,0,6,0));rr.addView(ui.type(reminders,12,16,500,0,tone[0]),new LinearLayout.LayoutParams(0,-2,1));words.addView(rr,MainParts.params(ui,-1,-2,0,6,0,0));
        box.addView(words,new LinearLayout.LayoutParams(0,-2,1));
        if(tappable){box.setOnClickListener(v->details(e));AppUi.press(box);box.setContentDescription(e.optString("title")+", "+when(e)+". "+reminders);}
        return box;}
    String when(JSONObject e){ZoneId z=zone();try{if(e.optBoolean("all_day")){LocalDate a=first(e,z),b=last(e,z);String s=birthday(e)?"Birthday · every year":"All day";return a.equals(b)?s:s+" · until "+b.format(SHORT);}
        ZonedDateTime a=OffsetDateTime.parse(e.optString("start")).atZoneSameInstant(z),b=OffsetDateTime.parse(e.optString("end")).atZoneSameInstant(z);String s=a.format(TIME)+"–"+b.format(TIME);if(!b.toLocalDate().equals(a.toLocalDate()))s=a.format(TIME)+" – "+b.format(SHORT)+" "+b.format(TIME);String place=e.optString("location");return place.isEmpty()?s:s+" · "+place;}catch(Exception x){return "";}}
    String reminderLine(JSONObject e){JSONArray r=e.optJSONArray("reminders");if(e.optBoolean("occurrence"))return "Reminders follow once this year's day has passed";if(r==null||r.length()==0)return "No reminder";
        ArrayList<String> times=new ArrayList<>();boolean missing=false,sent=true;for(JSONObject x:chronological(r)){String state=x.optString("state");if("missing".equals(state))missing=true;if(!"sent".equals(state))sent=false;times.add(due(x.optString("due_at")));}
        String list=android.text.TextUtils.join(" · ",times);return missing?"Not on your phone yet · "+list:sent?"Sent · "+list:"Reminder "+list;}
    static List<JSONObject> chronological(JSONArray r){ArrayList<JSONObject> out=new ArrayList<>();for(int i=0;r!=null&&i<r.length();i++)if(r.optJSONObject(i)!=null)out.add(r.optJSONObject(i));
        Collections.sort(out,(a,b)->{try{return OffsetDateTime.parse(a.optString("due_at")).compareTo(OffsetDateTime.parse(b.optString("due_at")));}catch(Exception e){return 0;}});return out;}
    /** Colour and glyph flag: amber alert when any reminder is missing from the cloud, muted when none, success otherwise. */
    int[] reminderTone(JSONObject e){JSONArray r=e.optJSONArray("reminders");if(e.optBoolean("occurrence")||r==null||r.length()==0)return new int[]{ui.muted,0};for(int i=0;i<r.length();i++)if("missing".equals(r.optJSONObject(i).optString("state")))return new int[]{ui.warning,1};return new int[]{ui.success,0};}
    String due(String at){try{ZonedDateTime d=OffsetDateTime.parse(at).atZoneSameInstant(zone());long n=ChronoUnit.DAYS.between(today(),d.toLocalDate());String day=n==0?"today":n==1?"tomorrow":d.format(SHORT);return day+" "+d.format(TIME);}catch(Exception x){return at;}}

    /** Entries added on the phone that the laptop has not applied yet, and any it could not add. */
    void requests(){JSONArray all=data.optJSONArray("requests");for(int i=0;all!=null&&i<all.length();i++){JSONObject q=all.optJSONObject(i);if(q==null||"added".equals(q.optString("state")))continue;boolean failed="failed".equals(q.optString("state"));
        String day="";try{day=LocalDate.parse(q.optString("date")).format(SHORT);}catch(Exception ignored){}
        page.addView(new MainParts.Banner(ui,failed?"danger":"info",failed?"alert":"clock",q.optString("title")+" · "+day,failed?"Not added: "+q.optString("detail"):"Waiting for your laptop to add it",null),MainParts.params(ui,-1,-2,0,0,0,10));}}

    /** One entry in full; changes go through the assistant, which owns the calendar. */
    void details(JSONObject e){Sheet s=new Sheet(e.optString("title"));
        s.body.addView(entry(e,false),MainParts.params(ui,-1,-2,0,0,0,14));
        if(!e.optString("notes").isEmpty()){s.body.addView(ui.label("Notes"),MainParts.params(ui,-1,-2,4,4,0,6));s.body.addView(ui.type(e.optString("notes"),15,22,400,0,ui.text),MainParts.params(ui,-1,-2,4,0,4,14));}
        JSONArray r=e.optJSONArray("reminders");if(r!=null&&r.length()>0){s.body.addView(ui.label("Reminders"),MainParts.params(ui,-1,-2,4,4,0,6));for(JSONObject x:chronological(r)){String state=x.optString("state");
            s.body.addView(ui.type(due(x.optString("due_at"))+" · "+("sent".equals(state)?"sent":"scheduled".equals(state)?"scheduled on your server":"missing".equals(state)?"not on your phone yet":"waiting"),14,20,400,0,"missing".equals(state)?ui.warning:ui.text),MainParts.params(ui,-1,-2,4,0,4,6));}}
        String origin=e.optString("origin");s.body.addView(ui.detail(("companion".equals(origin)?"Added on this phone. ":origin.isEmpty()?"Added by your assistant. ":"Added by your assistant from "+origin+". ")+"To change or cancel it, ask your assistant."),MainParts.params(ui,-1,-2,4,14,4,0));
        s.show();}

    /** A day: its entries, the daylight it has, and a small form to add one entry. */
    void day(LocalDate day){Sheet s=new Sheet(day.format(DAY));List<JSONObject> list=on(day);
        String light=daylight(day);s.body.addView(ui.detail((list.isEmpty()?"Nothing booked":list.size()==1?"1 entry":list.size()+" entries")+(light.isEmpty()?"":" · "+light)),MainParts.params(ui,-1,-2,4,0,4,14));
        for(JSONObject e:list)s.body.addView(entry(e,true),MainParts.params(ui,-1,-2,0,0,0,8));
        if(day.isBefore(today())){s.show();return;}
        s.body.addView(ui.label("Add on this day"),MainParts.params(ui,-1,-2,4,16,0,8));
        EditText name=ui.field("Title","");name.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);name.setTag("calendar_title");s.body.addView(name,MainParts.params(ui,-1,-2,0,0,0,10));
        final String[] kind={"timed"};final LocalTime[] times={LocalTime.of(10,0),LocalTime.of(11,0)};
        LinearLayout kinds=ui.row();LinearLayout timeRow=ui.row();TextView preview=ui.type("",13,18,500,0,ui.muted);
        Button from=ui.quietButton("",null),to=ui.quietButton("",null);
        Runnable[] update=new Runnable[1];
        update[0]=()->{from.setText("From "+times[0].format(TIME));to.setText("To "+times[1].format(TIME));timeRow.setVisibility("timed".equals(kind[0])?View.VISIBLE:View.GONE);preview.setText(preview(day,kind[0],times[0]));
            for(int i=0;i<kinds.getChildCount();i++){View c=kinds.getChildAt(i);boolean on=c.getTag().equals("calendar_kind_"+kind[0]);c.setActivated(on);c.setAlpha(on?1f:.7f);if(c instanceof TextView){((TextView)c).setTextColor(on?ui.accent:ui.muted);c.setBackground(ui.outline(on?ui.accentSoft:0,18,on?0:ui.strokeStrong,on?0:1));}}};
        String[][] choices={{"timed","Timed"},{"all_day","All day"},{"birthday","Birthday"}};
        for(String[] c:choices){TextView chip=ui.type(c[1],14,20,600,0,ui.muted);chip.setGravity(Gravity.CENTER);chip.setTag("calendar_kind_"+c[0]);chip.setMinHeight(ui.dp(44));chip.setPadding(ui.dp(16),0,ui.dp(16),0);chip.setOnClickListener(v->{kind[0]=c[0];update[0].run();});kinds.addView(chip,MainParts.params(ui,-2,ui.dp(44),0,0,8,0));}
        s.body.addView(kinds,MainParts.params(ui,-1,-2,0,0,0,10));
        from.setOnClickListener(v->new TimePickerDialog(activity,(p,h,m)->{long len=Duration.between(times[0],times[1]).toMinutes();times[0]=LocalTime.of(h,m);times[1]=times[0].plusMinutes(len>0?len:60);if(times[1].isBefore(times[0]))times[1]=LocalTime.of(23,59);update[0].run();},times[0].getHour(),times[0].getMinute(),true).show());
        to.setOnClickListener(v->new TimePickerDialog(activity,(p,h,m)->{times[1]=LocalTime.of(h,m);update[0].run();},times[1].getHour(),times[1].getMinute(),true).show());
        timeRow.addView(from,MainParts.weighted(ui,1,0,0,4,0));timeRow.addView(to,MainParts.weighted(ui,1,4,0,0,0));s.body.addView(timeRow,MainParts.params(ui,-1,-2,0,0,0,10));
        s.body.addView(preview,MainParts.params(ui,-1,-2,4,0,4,14));
        AppUi.Pill add=ui.primaryButton("Add to calendar",()->{String t=name.getText().toString().trim();if(t.isEmpty()){name.setError("Enter a title");return;}if("timed".equals(kind[0])&&!times[1].isAfter(times[0])){preview.setText("The end must be after the start.");return;}submit(s,t,day,kind[0],times[0],times[1]);});
        add.setTag("calendar_add");s.body.addView(add,MainParts.params(ui,-1,-2,0,0,0,8));
        s.body.addView(ui.detail("Or ask your assistant from Voice."),MainParts.params(ui,-1,-2,4,4,4,0));
        update[0].run();s.show();}
    /** When the reminder rules will notify for this entry, so the owner can see before adding it. */
    String preview(LocalDate day,String kind,LocalTime start){JSONObject rules=data.optJSONObject("rules");JSONArray leads=rules==null?null:rules.optJSONArray("birthday".equals(kind)?"birthday":kind);if(leads==null||leads.length()==0)return "No reminder unless you ask your assistant for one.";
        ZonedDateTime at="timed".equals(kind)?day.atTime(start).atZone(zone()):day.atStartOfDay(zone());ArrayList<String> out=new ArrayList<>();for(int i=0;i<leads.length();i++){ZonedDateTime d=at.minusMinutes(leads.optLong(i));out.add(d.format(DateTimeFormatter.ofPattern("EEE d MMM 'at' HH:mm")));}
        Collections.sort(out);return "You'll be reminded "+android.text.TextUtils.join(" and ",out)+".";}
    String daylight(LocalDate day){try{double[] place=AppUi.meridianPlace(activity);long noon=day.atTime(12,0).atZone(zone()).toInstant().toEpochMilli();long[] sun=MeridianSky.sunTimes(noon,place[0],place[1]);if(sun[0]<=0||sun[1]<=sun[0])return "";
        DateTimeFormatter f=TIME.withZone(zone());long minutes=(sun[1]-sun[0])/60000;return "sunrise "+f.format(Instant.ofEpochMilli(sun[0]))+" · sunset "+f.format(Instant.ofEpochMilli(sun[1]))+" · "+(minutes/60)+" h "+(minutes%60)+" min of daylight";}catch(Exception e){return "";}}

    void submit(Sheet s,String title,LocalDate day,String kind,LocalTime start,LocalTime end){JSONObject body=new JSONObject();String id="ph-"+UUID.randomUUID().toString().replace("-","");
        try{body.put("id",id).put("title",title).put("date",day.toString()).put("all_day",!"timed".equals(kind)).put("kind","birthday".equals(kind)?"birthday":"event");if("timed".equals(kind))body.put("start",start.format(TIME)).put("end",end.format(TIME));}catch(JSONException ignored){}
        Toast.makeText(activity,"Sending to your laptop…",Toast.LENGTH_SHORT).show();
        new Thread(()->{String failure=null;try{Cloud.call(activity,"calendar/requests",body,true);}catch(Exception e){failure=e instanceof Cloud.HttpError&&((Cloud.HttpError)e).status==422?"Check the title and times.":"Couldn't reach your server. Try again.";}
            String message=failure;activity.runOnUiThread(()->{if(message!=null){Toast.makeText(activity,message,Toast.LENGTH_LONG).show();return;}s.dismiss();try{JSONArray q=data.optJSONArray("requests");if(q==null)data.put("requests",q=new JSONArray());q.put(new JSONObject(body.toString()).put("state","pending"));}catch(JSONException ignored){}render();refresh();});}).start();}

    /** Full-height sheet with a back control, like task details. */
    final class Sheet{final Dialog dialog;final LinearLayout body;
        Sheet(String heading){dialog=ui.sheet();LinearLayout root=ui.column();root.setBackgroundColor(ui.background);root.setFitsSystemWindows(true);
            LinearLayout bar=ui.row();bar.setPadding(ui.dp(8),ui.dp(8),ui.dp(16),ui.dp(4));bar.addView(ui.iconButton("back","Back",this::dismiss),new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));TextView h=ui.type(heading,20,26,700,0,ui.text);h.setMaxLines(2);bar.addView(h,MainParts.weighted(ui,1,4,0,0,0));root.addView(bar);
            ScrollView scroll=new ScrollView(activity);body=ui.column();body.setPadding(ui.dp(20),ui.dp(8),ui.dp(20),ui.dp(28));scroll.addView(body);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));dialog.setContentView(root);}
        void show(){dialog.show();Window w=dialog.getWindow();if(w!=null)w.setLayout(-1,-1);}
        void dismiss(){dialog.dismiss();}}

    /** Six-week month: today in the aurora pill, a dot per entry (rose for birthdays), and every day opens its sheet. */
    final class MonthGrid extends View{final Paint p=new Paint(Paint.ANTI_ALIAS_FLAG);final String[] heads=new String[7];LocalDate pressed;
        MonthGrid(){super(activity);setClickable(true);DayOfWeek d=DayOfWeek.MONDAY;for(int i=0;i<7;i++){heads[i]=d.getDisplayName(java.time.format.TextStyle.NARROW,Locale.getDefault());d=d.plus(1);}setContentDescription("Month of "+month.format(MONTH)+". Tap a day to see it.");}
        LocalDate start(){LocalDate f=month.atDay(1);return f.minusDays(f.getDayOfWeek().getValue()-1);}
        float cell(){return getWidth()/7f;}float row(){return (getHeight()-ui.dpf(22))/6f;}
        @Override protected void onDraw(Canvas c){float w=cell(),h=row(),top=ui.dpf(22);p.setTextAlign(Paint.Align.CENTER);p.setTypeface(AppUi.face(500));p.setTextSize(ui.dpf(11));p.setColor(ui.muted);
            for(int i=0;i<7;i++)c.drawText(heads[i],w*(i+.5f),ui.dpf(13),p);
            LocalDate d=start(),today=today();HashMap<LocalDate,int[]> marks=new HashMap<>();ZoneId z=zone();
            for(JSONObject e:events())try{LocalDate a=first(e,z),b=last(e,z);for(LocalDate x=a;!x.isAfter(b)&&!x.isAfter(d.plusDays(42));x=x.plusDays(1)){int[] m=marks.get(x);if(m==null)marks.put(x,m=new int[3]);if(birthday(e))m[1]++;else m[0]++;if(!a.equals(b))m[2]=1;}}catch(Exception ignored){}
            for(int i=0;i<42;i++,d=d.plusDays(1)){float cx=w*(i%7+.5f),cy=top+h*(i/7)+h*.42f;boolean inMonth=d.getMonth()==month.getMonth(),isToday=d.equals(today);
                if(isToday){p.setShader(new LinearGradient(cx-w*.4f,cy-h*.4f,cx+w*.4f,cy+h*.4f,ui.aurora[0],ui.aurora[1],Shader.TileMode.CLAMP));c.drawRoundRect(cx-w*.42f,cy-h*.42f,cx+w*.42f,cy+h*.48f,ui.dpf(12),ui.dpf(12),p);p.setShader(null);}
                else if(d.equals(pressed)){p.setColor(ui.accentSoft);c.drawRoundRect(cx-w*.42f,cy-h*.42f,cx+w*.42f,cy+h*.48f,ui.dpf(12),ui.dpf(12),p);}
                p.setTypeface(AppUi.face(isToday?700:500));p.setTextSize(ui.dpf(15));p.setColor(isToday?ui.onAccent:!inMonth?AppUi.alpha(ui.muted,.45f):d.isBefore(today)?ui.muted:ui.text);c.drawText(String.valueOf(d.getDayOfMonth()),cx,cy+ui.dpf(4),p);
                int[] m=marks.get(d);if(m!=null){int n=Math.min(3,m[0])+Math.min(2,m[1]);float y=cy+h*.3f,gap=ui.dpf(7),x=cx-gap*(n-1)/2f;
                    for(int k=0;k<n;k++){p.setColor(isToday?ui.onAccent:k<Math.min(3,m[0])?ui.accent:ui.aurora[2]);if(!inMonth)p.setAlpha(110);c.drawCircle(x+gap*k,y,ui.dpf(2.6f),p);p.setAlpha(255);}}}}
        LocalDate at(float x,float y){float top=ui.dpf(22);if(y<top)return null;int col=Math.max(0,Math.min(6,(int)(x/cell()))),r=Math.max(0,Math.min(5,(int)((y-top)/row())));return start().plusDays(r*7+col);}
        @Override public boolean onTouchEvent(MotionEvent e){LocalDate d=at(e.getX(),e.getY());if(e.getAction()==MotionEvent.ACTION_DOWN){pressed=d;invalidate();return true;}
            if(e.getAction()==MotionEvent.ACTION_UP){pressed=null;invalidate();if(d!=null){if(d.getMonth()!=month.getMonth()){month=YearMonth.from(d);render();}day(d);performClick();}return true;}
            if(e.getAction()==MotionEvent.ACTION_CANCEL){pressed=null;invalidate();}return super.onTouchEvent(e);}
        @Override public boolean performClick(){return super.performClick();}}
}
