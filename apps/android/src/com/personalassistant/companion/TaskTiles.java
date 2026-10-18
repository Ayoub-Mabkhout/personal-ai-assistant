package com.personalassistant.companion;

import android.app.PendingIntent;
import android.content.Intent;
import android.os.Build;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

/** Quick Settings tiles; both work from the lock screen's pulled-down shade. */
final class TaskTiles {
    static void launch(TileService service,Class<?> target,int code){
        Intent intent=new Intent(service,target).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        if(Build.VERSION.SDK_INT>=34)service.startActivityAndCollapse(PendingIntent.getActivity(service,code,intent,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT));
        else service.startActivityAndCollapse(intent);
    }
    static void idle(TileService service){Tile tile=service.getQsTile();if(tile!=null){tile.setState(Tile.STATE_INACTIVE);tile.updateTile();}}
}
