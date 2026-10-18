package com.personalassistant.companion;

import android.service.quicksettings.TileService;

/** Quick Settings tile: New task, usable from the lock screen's shade. */
public final class NewTaskTile extends TileService {
    @Override public void onStartListening(){super.onStartListening();TaskTiles.idle(this);}
    @Override public void onClick(){TaskTiles.launch(this,QuickTaskActivity.class,71);}
}
