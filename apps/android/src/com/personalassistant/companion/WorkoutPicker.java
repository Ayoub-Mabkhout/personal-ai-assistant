package com.personalassistant.companion;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import java.util.function.Consumer;

/** Transparent host for the system document picker, since sheets can't receive activity results. No storage permission is needed. */
public final class WorkoutPicker extends Activity {
    static Consumer<Uri> waiting;
    static void pick(Activity a,String type,Consumer<Uri> done){waiting=done;a.startActivity(new Intent(a,WorkoutPicker.class).putExtra("type",type));}
    @Override public void onCreate(Bundle state){super.onCreate(state);if(state==null)startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(getIntent().getStringExtra("type")),403);}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);Consumer<Uri> done=waiting;waiting=null;if(result==RESULT_OK&&data!=null&&data.getData()!=null&&done!=null)done.accept(data.getData());finish();}
}
