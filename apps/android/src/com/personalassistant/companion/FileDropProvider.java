package com.personalassistant.companion;
import android.content.*;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.Environment;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;
import java.util.List;

/** Read-only sharing of received files saved in app-specific Downloads before Android 10. Android 10+ uses MediaStore URIs. */
public class FileDropProvider extends ContentProvider{
    static Uri uri(Context c,File file){return Uri.parse("content://"+c.getPackageName()+".files/"+Uri.encode(file.getName()));}
    @Override public boolean onCreate(){return true;}
    File file(Uri uri)throws FileNotFoundException{
        File folder=getContext().getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS);List<String> parts=uri.getPathSegments();
        if(folder==null||!(getContext().getPackageName()+".files").equals(uri.getAuthority())||parts.size()!=1)throw new FileNotFoundException("Unknown file");
        // One plain name inside the folder: a decoded separator or dot segment never resolves elsewhere.
        File file=new File(folder,parts.get(0));
        if(!file.getName().equals(parts.get(0))||!file.isFile())throw new FileNotFoundException("Unknown file");
        return file;
    }
    @Override public String getType(Uri uri){try{return FileDrops.mime(null,file(uri).getName());}catch(FileNotFoundException missing){return null;}}
    @Override public ParcelFileDescriptor openFile(Uri uri,String mode)throws FileNotFoundException{if(!"r".equals(mode))throw new FileNotFoundException("Read-only file");return ParcelFileDescriptor.open(file(uri),ParcelFileDescriptor.MODE_READ_ONLY);}
    @Override public Cursor query(Uri uri,String[] projection,String selection,String[] args,String sort){
        MatrixCursor cursor=new MatrixCursor(new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE});
        try{File file=file(uri);cursor.addRow(new Object[]{file.getName(),file.length()});}catch(FileNotFoundException missing){}
        return cursor;
    }
    @Override public Uri insert(Uri u,ContentValues v){throw new UnsupportedOperationException();}
    @Override public int update(Uri u,ContentValues v,String s,String[] a){throw new UnsupportedOperationException();}
    @Override public int delete(Uri u,String s,String[] a){throw new UnsupportedOperationException();}
}
