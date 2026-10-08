package com.personalassistant.companion;
import android.content.*;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.FileNotFoundException;

public class UpdateProvider extends ContentProvider{
    @Override public boolean onCreate(){return true;}
    void verify(Uri uri){if(!"/companion.apk".equals(uri.getPath())||!uri.getAuthority().equals(getContext().getPackageName()+".updates"))throw new IllegalArgumentException("Unknown update file");}
    @Override public String getType(Uri uri){verify(uri);return "application/vnd.android.package-archive";}
    @Override public ParcelFileDescriptor openFile(Uri uri,String mode)throws FileNotFoundException{verify(uri);if(!"r".equals(mode))throw new FileNotFoundException("Read-only update");return ParcelFileDescriptor.open(Updates.apk(getContext()),ParcelFileDescriptor.MODE_READ_ONLY);}
    @Override public Cursor query(Uri uri,String[] projection,String selection,String[] args,String sort){verify(uri);MatrixCursor cursor=new MatrixCursor(new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE});cursor.addRow(new Object[]{"assistant-companion.apk",Updates.apk(getContext()).length()});return cursor;}
    @Override public Uri insert(Uri u,ContentValues v){throw new UnsupportedOperationException();}
    @Override public int update(Uri u,ContentValues v,String s,String[] a){throw new UnsupportedOperationException();}
    @Override public int delete(Uri u,String s,String[] a){throw new UnsupportedOperationException();}
}
