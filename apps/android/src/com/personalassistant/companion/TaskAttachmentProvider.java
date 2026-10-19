package com.personalassistant.companion;
import android.content.*;
import android.database.*;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.*;

/** Read-only, temporary URI grants for originals opened from a task conversation. */
public final class TaskAttachmentProvider extends ContentProvider {
    public boolean onCreate(){return true;}
    private String id(Uri uri)throws FileNotFoundException{if(!uri.getAuthority().equals(getContext().getPackageName()+".taskattachments")||uri.getPathSegments().size()!=1||!uri.getLastPathSegment().matches("[A-Za-z0-9_-]{8,64}"))throw new FileNotFoundException();return uri.getLastPathSegment();}
    public String getType(Uri uri){try{return TaskAttachments.metadata(getContext(),id(uri)).optString("mime","application/octet-stream");}catch(Exception e){return null;}}
    public ParcelFileDescriptor openFile(Uri uri,String mode)throws FileNotFoundException{if(!mode.equals("r"))throw new FileNotFoundException("Read only");return ParcelFileDescriptor.open(TaskAttachments.file(getContext(),id(uri)),ParcelFileDescriptor.MODE_READ_ONLY);}
    public Cursor query(Uri uri,String[] projection,String selection,String[] args,String sort){MatrixCursor cursor=new MatrixCursor(new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE});try{org.json.JSONObject row=TaskAttachments.metadata(getContext(),id(uri));cursor.addRow(new Object[]{row.optString("name"),row.optLong("size")});}catch(Exception ignored){}return cursor;}
    public Uri insert(Uri uri,ContentValues values){throw new UnsupportedOperationException();}public int update(Uri uri,ContentValues v,String s,String[] a){throw new UnsupportedOperationException();}public int delete(Uri uri,String s,String[] a){throw new UnsupportedOperationException();}
}
