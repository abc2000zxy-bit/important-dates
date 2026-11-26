"""python-for-android hook: register the Java receivers in AndroidManifest.xml.

Buildozer has no 'android.add_receivers' option, so we patch the generated
manifest after p4a creates it and before Gradle packages the APK.
"""
from pathlib import Path

RECEIVERS = """
    <receiver android:name="org.importantdates.AlarmReceiver"
              android:enabled="true"
              android:exported="false" />
    <receiver android:name="org.importantdates.BootReceiver"
              android:enabled="true"
              android:exported="true">
        <intent-filter>
            <action android:name="android.intent.action.BOOT_COMPLETED" />
        </intent-filter>
    </receiver>
"""


def after_apk_build(toolchain):
    manifest = Path(toolchain._dist.dist_dir) / "src" / "main" / "AndroidManifest.xml"
    text = manifest.read_text(encoding="utf-8")
    if "org.importantdates.AlarmReceiver" in text:
        print("[hook] receivers already present")
        return
    if "</application>" not in text:
        raise RuntimeError("[hook] </application> not found in " + str(manifest))
    manifest.write_text(text.replace("</application>", RECEIVERS + "</application>", 1),
                        encoding="utf-8")
    print("[hook] AlarmReceiver + BootReceiver added to manifest")
