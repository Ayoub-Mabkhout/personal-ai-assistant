package com.personalassistant.companion;

import android.service.quicksettings.TileService;

/** Quick Settings tile: Last task. Task details are private, so from the lock screen it asks for unlock first. */
public final class LastTaskTile extends TileService {
    @Override public void onStartListening(){super.onStartListening();TaskTiles.idle(this);}
    @Override public void onClick(){if(isLocked())unlockAndRun(()->TaskTiles.launch(this,LastTaskActivity.class,72));else TaskTiles.launch(this,LastTaskActivity.class,72);}
}
