[app]
title = Important Dates
package.name = importantdates
package.domain = org.importantdates
source.dir = .
source.include_exts = py
version = 1.1
requirements = python3,kivy==2.3.0,pyjnius
orientation = portrait
fullscreen = 0
android.archs = arm64-v8a
android.api = 33
android.minapi = 24
android.accept_sdk_license = True
android.permissions = POST_NOTIFICATIONS,SCHEDULE_EXACT_ALARM,RECEIVE_BOOT_COMPLETED,WAKE_LOCK
android.add_src = java
android.add_receivers = org.importantdates.BootReceiver,org.importantdates.AlarmReceiver

[buildozer]
log_level = 2
warn_on_root = 1
