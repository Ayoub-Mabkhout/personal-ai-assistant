package com.personalassistant.companion;
import android.app.Activity;
import android.content.*;
import android.os.Bundle;
import android.net.Uri;
import android.widget.Toast;
import java.util.ArrayList;

/** System document picker grants access only to selected originals; no storage permission. */
public final class AttachmentPickerActivity extends Activity {
    @Override public void onCreate(Bundle state){super.onCreate(state);if(state==null){Intent pick=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(getIntent().getBooleanExtra("images",false)?"image/*":"*/*").putExtra(Intent.EXTRA_ALLOW_MULTIPLE,true).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);try{startActivityForResult(pick,401);}catch(Exception e){Toast.makeText(this,"No file picker is available",Toast.LENGTH_LONG).show();finish();}}}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request!=401)return;if(result!=RESULT_OK||data==null){finish();return;}ArrayList<Uri> selected=new ArrayList<>();if(data.getClipData()!=null){for(int n=0;n<data.getClipData().getItemCount();n++)selected.add(data.getClipData().getItemAt(n).getUri());}else if(data.getData()!=null)selected.add(data.getData());
        String key=getIntent().getStringExtra("draft");Toast.makeText(this,"Saving selected files…",Toast.LENGTH_SHORT).show();new Thread(()->{String error="";try{for(Uri uri:selected)TaskAttachments.add(this,key,uri);}catch(Exception e){error=e.getMessage();}String message=error;runOnUiThread(()->{if(!message.isEmpty())Toast.makeText(this,message,Toast.LENGTH_LONG).show();NativeTasks.changed(this);finish();});}).start();}
}
