# Native instrumentation and persisted Android component names share the app API.
# App code is small; Firebase's bundled dependencies are the useful shrink target.
-keep class com.personalassistant.companion.** { *; }

# Wake adapters discover optional engines, constructors and methods by reflection.
-keep class org.vosk.** { *; }
-keep class com.sun.jna.** { *; }
-keep class com.k2fsa.sherpa.onnx.** { *; }
-keep class ai.onnxruntime.** { *; }
-dontwarn com.sun.jna.platform.**
-dontwarn java.awt.**

# Firebase SDK AAR consumer rules keep component registrars and service dispatch.
# Do not add Analytics, crash reporting, or blanket Firebase keep rules.
