package com.personalassistant.companion;
/** Sample-count boundaries: wake pre-roll never counts as fresh command speech. */
final class CaptureTurnPolicy {
    static boolean finished(int elapsed,int freshSpeech,int quiet,boolean wake){return elapsed>=480000||(freshSpeech>=2400&&quiet>=19200&&(!wake||freshSpeech>=12800||elapsed>=80000));}
    static boolean expired(int elapsed,int freshSpeech){return elapsed>=128000&&freshSpeech<2400;}
}
