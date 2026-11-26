[app]
title = Important Dates
package.name = importantdates
package.domain = org.importantdates
source.dir = .
source.include_exts = py
version = 1.2
requirements = python3==3.11.5,hostpython3==3.11.5,kivy==2.3.0,pyjnius
orientation = portrait
fullscreen = 0
android.archs = arm64-v8a
android.api = 33
android.minapi = 24
android.accept_sdk_license = True
android.permissions = POST_NOTIFICATIONS,SCHEDULE_EXACT_ALARM,RECEIVE_BOOT_COMPLETED,WAKE_LOCK
android.add_src = java
p4a.hook = p4a/hook.py
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
