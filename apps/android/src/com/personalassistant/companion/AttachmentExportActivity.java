package com.personalassistant.companion;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.widget.Toast;
import java.io.*;
import org.json.JSONObject;

/** Save a verified original to a user-selected document, including Downloads. */
public final class AttachmentExportActivity extends Activity {
    @Override public void onCreate(Bundle state){super.onCreate(state);if(state!=null)return;try{
        JSONObject row=TaskAttachments.metadata(this,getIntent().getStringExtra("id"));
        startActivityForResult(new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(row.optString("mime","application/octet-stream")).putExtra(Intent.EXTRA_TITLE,row.getString("name")),402);
    }catch(Exception e){Toast.makeText(this,"A file-saving app is unavailable",Toast.LENGTH_LONG).show();finish();}}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request!=402)return;if(result!=RESULT_OK||data==null||data.getData()==null){finish();return;}Uri uri=data.getData();new Thread(()->{
        String message="File saved";try{JSONObject row=TaskAttachments.metadata(this,getIntent().getStringExtra("id"));File original=TaskAttachments.cached(this,row);try(InputStream in=new FileInputStream(original);OutputStream out=getContentResolver().openOutputStream(uri)){if(out==null)throw new IOException("Destination is unavailable");FileDrops.copy(in,out);}}
        catch(Exception e){message="Could not save file: "+e.getMessage();try{getContentResolver().delete(uri,null,null);}catch(Exception ignored){}}
        String shown=message;runOnUiThread(()->{Toast.makeText(this,shown,Toast.LENGTH_LONG).show();finish();});
    }).start();}
}
