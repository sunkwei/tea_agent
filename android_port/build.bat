@echo off
set JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot
cd /d C:\Users\Hetin\work\git\tea_agent\android_port\tea_agent_android
call gradlew.bat assembleDebug
