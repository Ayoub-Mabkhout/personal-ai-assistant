package com.personalassistant.companion;

import android.Manifest;
import android.app.Dialog;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Matrix;
import android.graphics.SurfaceTexture;
import android.hardware.Camera;
import android.media.ExifInterface;
import android.view.Gravity;
import android.view.Surface;
import android.view.TextureView;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;

/** Live camera and review for a workout check-in. No URI or file-picker input enters this flow. */
@SuppressWarnings("deprecation")
final class WorkoutProofCamera implements TextureView.SurfaceTextureListener {
    static final int MAX_JPEG=1024*1024;
    static final int PERMISSION_REQUEST=304;
    interface UsePhoto {void use(byte[] jpeg,boolean share);}

    private final MainActivity a;
    private final AppUi ui;
    private final UsePhoto use;
    private Dialog dialog;
    private Camera camera;
    private TextureView preview;
    private ImageView review;
    private Button shutter,flip,retake,accept;
    private Switch sharing;
    private TextView help;
    private int cameraId;
    private byte[] photo;
    private Bitmap reviewed;

    private WorkoutProofCamera(MainActivity activity,AppUi style,UsePhoto callback){
        a=activity;ui=style;use=callback;
    }

    static void open(MainActivity a,AppUi ui,UsePhoto use){
        if(a.proofCamera!=null)return;
        WorkoutProofCamera capture=new WorkoutProofCamera(a,ui,use);
        a.proofCamera=capture;
        if(a.checkSelfPermission(Manifest.permission.CAMERA)==PackageManager.PERMISSION_GRANTED)capture.show();
        else a.requestPermissions(new String[]{Manifest.permission.CAMERA},PERMISSION_REQUEST);
    }

    void permissionResult(boolean granted){
        if(granted)show();
        else{
            a.proofCamera=null;
            Toast.makeText(a,"Allow Camera in app settings to finish the workout.",Toast.LENGTH_LONG).show();
        }
    }

    void pause(){if(dialog!=null)dialog.dismiss();}

    private void show(){
        int count=Camera.getNumberOfCameras();
        if(count==0){
            a.proofCamera=null;
            Toast.makeText(a,"A camera is needed to finish the workout.",Toast.LENGTH_LONG).show();
            return;
        }
        for(int i=0;i<count;i++){
            Camera.CameraInfo info=new Camera.CameraInfo();Camera.getCameraInfo(i,info);
            if(info.facing==Camera.CameraInfo.CAMERA_FACING_FRONT){cameraId=i;break;}
        }
        dialog=ui.sheet();
        LinearLayout content=ui.column();
        content.setFitsSystemWindows(true);
        content.setPadding(ui.dp(16),ui.dp(10),ui.dp(16),ui.dp(14));
        content.setBackgroundColor(ui.background);
        LinearLayout header=ui.row();
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.addView(ui.iconButton("back","Close camera",ui.text,dialog::dismiss),new LinearLayout.LayoutParams(ui.dp(46),ui.dp(46)));
        header.addView(ui.type("Workout check-in",22,28,750,0,ui.text),MainParts.weighted(ui,1,8,0,0,0));
        content.addView(header);
        help=ui.detail("Take a photo of yourself training.");
        content.addView(help,WorkoutViews.gap(ui,10));
        FrameLayout image=new FrameLayout(a);
        image.setBackground(ui.outline(ui.surfaceAlt,18,0,0));
        image.setClipToOutline(true);
        preview=new TextureView(a);
        preview.setSurfaceTextureListener(this);
        image.addView(preview,new FrameLayout.LayoutParams(-1,-1));
        review=new ImageView(a);
        review.setContentDescription("Your workout photo");
        review.setScaleType(ImageView.ScaleType.FIT_CENTER);
        review.setVisibility(View.GONE);
        image.addView(review,new FrameLayout.LayoutParams(-1,-1));
        content.addView(image,new LinearLayout.LayoutParams(-1,0,1));
        sharing=ui.switchControl(false,"Share to Friends feed");
        sharing.setText("Share to Friends feed");
        sharing.setVisibility(View.GONE);
        content.addView(sharing,WorkoutViews.gap(ui,6));
        LinearLayout tools=ui.row();
        flip=ui.quietButton("Flip camera",()->{
            cameraId=(cameraId+1)%count;
            startPreview();
        });
        shutter=ui.primaryButton("Take photo",this::capture);
        shutter.setEnabled(false);
        retake=ui.quietButton("Retake",this::reset);
        accept=ui.primaryButton("Finish workout",()->{
            byte[] imageBytes=photo;
            boolean share=sharing.isChecked();
            dialog.dismiss();
            use.use(imageBytes,share);
        });
        for(Button b:new Button[]{flip,shutter,retake,accept})tools.addView(b,MainParts.weighted(ui,1,4,0,4,0));
        content.addView(tools,WorkoutViews.gap(ui,10));
        dialog.setContentView(content);
        dialog.setOnDismissListener(ignored->{release();clearPhoto();a.proofCamera=null;});
        dialog.show();
        Window window=dialog.getWindow();
        if(window!=null){window.setLayout(-1,-1);window.addFlags(WindowManager.LayoutParams.FLAG_SECURE);}
        showReview(false);
    }

    private void startPreview(){
        release();
        if(!preview.isAvailable())return;
        shutter.setEnabled(false);
        try{
            camera=Camera.open(cameraId);
            Camera.CameraInfo info=new Camera.CameraInfo();
            Camera.getCameraInfo(cameraId,info);
            int rotation=a.getWindowManager().getDefaultDisplay().getRotation();
            int degrees=rotation==Surface.ROTATION_90?90:rotation==Surface.ROTATION_180?180:rotation==Surface.ROTATION_270?270:0;
            boolean front=info.facing==Camera.CameraInfo.CAMERA_FACING_FRONT;
            int upright=(info.orientation+(front?degrees:-degrees)+360)%360;
            camera.setDisplayOrientation(front?(360-upright)%360:upright);
            Camera.Parameters params=camera.getParameters();
            Camera.Size current=params.getPictureSize();
            long best=0;
            for(Camera.Size size:params.getSupportedPictureSizes()){
                long pixels=(long)size.width*size.height;
                if(pixels<=5_000_000&&pixels>best){best=pixels;current=size;}
            }
            params.setPictureSize(current.width,current.height);
            params.setRotation((info.orientation+(front?-degrees:degrees)+360)%360);
            camera.setParameters(params);
            camera.setPreviewTexture(preview.getSurfaceTexture());
            Camera.Size size=camera.getParameters().getPreviewSize();
            float width=preview.getWidth(),height=preview.getHeight();
            float frameAspect=upright%180==0?(float)size.width/size.height:(float)size.height/size.width;
            float viewAspect=width/Math.max(1,height);
            Matrix transform=new Matrix();
            transform.setScale(Math.max(1,frameAspect/viewAspect),Math.max(1,viewAspect/frameAspect),width/2,height/2);
            preview.setTransform(transform);
            camera.startPreview();
            help.setText("Take a photo of yourself training.");
            shutter.setEnabled(true);
        }catch(IOException|RuntimeException error){
            release();
            help.setText("Camera unavailable. Close other camera apps and reopen this screen.");
        }
    }

    private void capture(){
        if(camera==null)return;
        shutter.setEnabled(false);flip.setEnabled(false);
        try{
            camera.takePicture(null,null,(data,source)->{
                if(camera!=source||!dialog.isShowing())return;
                release();
                try{
                    photo=compress(data);
                    reviewed=BitmapFactory.decodeByteArray(photo,0,photo.length);
                    review.setImageBitmap(reviewed);
                    showReview(true);
                }catch(IOException|RuntimeException error){
                    reset();
                    help.setText("Couldn't capture that photo. Try again.");
                }
            });
        }catch(RuntimeException error){
            reset();
            help.setText("Couldn't capture that photo. Try again.");
        }
    }

    /** Reduce the frame and strip metadata before it enters the private outbox. */
    private static byte[] compress(byte[] data)throws IOException{
        BitmapFactory.Options opts=new BitmapFactory.Options();
        opts.inJustDecodeBounds=true;
        BitmapFactory.decodeByteArray(data,0,data.length,opts);
        opts.inJustDecodeBounds=false;opts.inSampleSize=1;
        while(Math.max(opts.outWidth,opts.outHeight)/opts.inSampleSize>1700)opts.inSampleSize*=2;
        Bitmap bitmap=BitmapFactory.decodeByteArray(data,0,data.length,opts);
        if(bitmap==null)throw new IOException("No frame");
        try{
            int orientation=new ExifInterface(new ByteArrayInputStream(data)).getAttributeInt(ExifInterface.TAG_ORIENTATION,ExifInterface.ORIENTATION_NORMAL);
            Matrix matrix=new Matrix();
            if(orientation==ExifInterface.ORIENTATION_ROTATE_90)matrix.postRotate(90);
            else if(orientation==ExifInterface.ORIENTATION_ROTATE_180)matrix.postRotate(180);
            else if(orientation==ExifInterface.ORIENTATION_ROTATE_270)matrix.postRotate(270);
            if(!matrix.isIdentity()){
                Bitmap upright=Bitmap.createBitmap(bitmap,0,0,bitmap.getWidth(),bitmap.getHeight(),matrix,true);
                if(upright!=bitmap){bitmap.recycle();bitmap=upright;}
            }
            ByteArrayOutputStream jpeg=new ByteArrayOutputStream();
            for(int quality:new int[]{85,70,55}){
                jpeg.reset();
                if(bitmap.compress(Bitmap.CompressFormat.JPEG,quality,jpeg)&&jpeg.size()<=MAX_JPEG)return jpeg.toByteArray();
            }
            throw new IOException("Frame too large");
        }finally{bitmap.recycle();}
    }

    private void showReview(boolean ready){
        preview.setVisibility(ready?View.INVISIBLE:View.VISIBLE);
        review.setVisibility(ready?View.VISIBLE:View.GONE);
        sharing.setVisibility(ready?View.VISIBLE:View.GONE);
        shutter.setVisibility(ready?View.GONE:View.VISIBLE);
        flip.setVisibility(!ready&&Camera.getNumberOfCameras()>1?View.VISIBLE:View.GONE);
        flip.setEnabled(!ready);
        retake.setVisibility(ready?View.VISIBLE:View.GONE);
        accept.setVisibility(ready?View.VISIBLE:View.GONE);
        help.setText(ready?"If shared, signed-in Iron League members can see this photo and workout when progress sharing is on.":"Take a photo of yourself training.");
    }

    private void reset(){
        clearPhoto();showReview(false);startPreview();
    }

    private void clearPhoto(){
        photo=null;
        if(review!=null)review.setImageDrawable(null);
        if(reviewed!=null){reviewed.recycle();reviewed=null;}
    }

    private void release(){
        if(camera!=null){camera.release();camera=null;}
    }

    @Override public void onSurfaceTextureAvailable(SurfaceTexture surface,int w,int h){if(photo==null)startPreview();}
    @Override public void onSurfaceTextureSizeChanged(SurfaceTexture surface,int w,int h){if(photo==null)startPreview();}
    @Override public boolean onSurfaceTextureDestroyed(SurfaceTexture surface){release();return true;}
    @Override public void onSurfaceTextureUpdated(SurfaceTexture surface){}
}
