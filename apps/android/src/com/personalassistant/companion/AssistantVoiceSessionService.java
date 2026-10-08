package com.personalassistant.companion;
import android.service.voice.*;
import android.os.Bundle;
public class AssistantVoiceSessionService extends VoiceInteractionSessionService {
    @Override public VoiceInteractionSession onNewSession(Bundle args){return new AssistantVoiceSession(this);}
}
