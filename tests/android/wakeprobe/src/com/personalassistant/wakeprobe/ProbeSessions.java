package com.personalassistant.wakeprobe;
import android.service.voice.*;
import android.os.Bundle;
/** A role-eligible session with no microphone or activation behavior. */
public final class ProbeSessions extends VoiceInteractionSessionService {
    @Override public VoiceInteractionSession onNewSession(Bundle args){return new VoiceInteractionSession(this);}
}
