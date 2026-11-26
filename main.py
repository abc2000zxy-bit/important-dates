import hashlib
import json
import os
from datetime import date, datetime, time as dtime, timedelta
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.utils import escape_markup, platform
REMIND = [("On the day", 0), ("1 day before", 1), ("3 days before", 3),
          ("1 week before", 7), ("2 weeks before", 14), ("1 month before", 30)]
ACCENT = (0.76, 0.25, 0.05, 1)
class Speaker:
    """Android text-to-speech through pyjnius."""
    def __init__(self):
        self.tts = None
        self.ready = False
        self.pending = None
        self.keep = None
        if platform != "android":
            return
        try:
            from jnius import PythonJavaClass, java_method, autoclass
            class Init(PythonJavaClass):
                __javainterfaces__ = ["android/speech/tts/TextToSpeech$OnInitListener"]
                __javacontext__ = "app"
                def __init__(self, cb):
                    super().__init__()
                    self.cb = cb
                @java_method("(I)V")
                def onInit(self, status):
                    self.cb(status)
            self.TTS = autoclass("android.speech.tts.TextToSpeech")
            self.Locale = autoclass("java.util.Locale")
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            self.keep = Init(self._on_init)
            self.tts = self.TTS(activity, self.keep)
        except Exception as e:
            print("TTS init failed:", e)
    def _on_init(self, status):
        if status != 0:
            return
        try:
            self.tts.setLanguage(self.Locale.getDefault())
        except Exception:
            pass
        self.ready = True
        if self.pending:
            text, self.pending = self.pending, None
            self.speak(text)
    def speak(self, text):
        if self.tts is None:
            return False
        if not self.ready:
            self.pending = text
            return True
        try:
            self.tts.speak(text, self.TTS.QUEUE_FLUSH, None, "dates")
            return True
        except Exception as e:
            print("TTS speak failed:", e)
            return False
class Notifier:
    """Post a real Android system notification via pyjnius (no plyer needed)."""
    def __init__(self):
        self.nm = None
        if platform != "android":
            return
        try:
            from jnius import autoclass
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            self.activity = activity
            self.Context = autoclass("android.content.Context")
            self.nm = activity.getSystemService(self.Context.NOTIFICATION_SERVICE)
            # Notification channel (required on Android 8+)
            if int(str(autoclass("android.os.Build$VERSION").SDK_INT)) >= 26:
                Channel = autoclass("android.app.NotificationChannel")
                ch = Channel("dates", "Important Dates",
                             self.nm.IMPORTANCE_HIGH)
                ch.setDescription("Reminders for your important dates")
                self.nm.createNotificationChannel(ch)
        except Exception as e:
            print("Notifier init failed:", e)
    def notify(self, title, text):
        if self.nm is None:
            return False
        try:
            from jnius import autoclass
            Builder = autoclass("android.app.Notification$Builder")
            Intent = autoclass("android.content.Intent")
            PendingIntent = autoclass("android.app.PendingIntent")
            # Tap notification -> open the app
            intent = Intent(self.activity, self.activity.getClass())
            intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                            | Intent.FLAG_ACTIVITY_CLEAR_TASK)
            pi = PendingIntent.getActivity(
                self.activity, 0, intent,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE)
            b = Builder(self.activity, "dates") \
                .setContentTitle(title) \
                .setContentText(text) \
                .setSmallIcon(self.activity.getApplicationInfo().icon) \
                .setContentIntent(pi) \
                .setAutoCancel(True) \
                .setPriority(Builder.PRIORITY_HIGH if hasattr(Builder, "PRIORITY_HIGH") else 1)
            # setPriority is deprecated on API 26+ but harmless; channel controls it
            self.nm.notify(abs(hash(title + text)) % 100000, b.build())
            return True
        except Exception as e:
            print("Notify failed:", e)
            return False
class AlarmScheduler:
    """Schedule reminders using explicit Android broadcast PendingIntents.

    AlarmReceiver posts the notification without trying to launch the app.
    BootReceiver restores alarms after a device restart. The same SHA-256
    request-code algorithm is used by Python and BootReceiver.java.
    Trigger time: 9:00 AM on (occurrence - remind_days).
    """
    ACTION_REMINDER = "org.importantdates.REMINDER"

    def __init__(self):
        self.am = None
        self.activity = None
        if platform != "android":
            return
        try:
            from jnius import autoclass
            self.activity = autoclass("org.kivy.android.PythonActivity").mActivity
            Context = autoclass("android.content.Context")
            self.am = self.activity.getSystemService(Context.ALARM_SERVICE)
        except Exception as e:
            print("AlarmManager init failed:", e)

    def _request_code(self, item):
        digest = hashlib.sha256(str(item["id"]).encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big") & 0x7fffffff

    def _intent(self, item, occ, trigger):
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")
        AlarmReceiver = autoclass("org.importantdates.AlarmReceiver")
        intent = Intent(self.activity, AlarmReceiver)
        intent.setAction(self.ACTION_REMINDER)
        intent.putExtra("reminder_title", str(item["title"]))
        intent.putExtra("reminder_date", occ.isoformat())
        intent.putExtra("reminder_id", str(item["id"]))
        return intent

    def _pending(self, item, occ, trigger, flags=None):
        from jnius import autoclass
        PendingIntent = autoclass("android.app.PendingIntent")
        if flags is None:
            flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        return PendingIntent.getBroadcast(
            self.activity, self._request_code(item),
            self._intent(item, occ, trigger), flags)

    def trigger_datetime(self, item):
        """When this item's reminder should fire, or None if already past."""
        occ = next_occ(item)
        trig_date = occ - timedelta(days=int(item.get("remind", 0)))
        trig = datetime.combine(trig_date, dtime(9, 0))
        return trig if trig > datetime.now() else None

    def schedule(self, item):
        if self.am is None:
            return False
        trig = self.trigger_datetime(item)
        if trig is None:
            return False
        try:
            from jnius import autoclass
            Calendar = autoclass("java.util.Calendar")
            cal = Calendar.getInstance()
            cal.set(trig.year, trig.month - 1, trig.day, trig.hour, trig.minute, 0)
            cal.set(Calendar.MILLISECOND, 0)
            pi = self._pending(item, next_occ(item), trig)
            try:
                sdk = int(autoclass("android.os.Build$VERSION").SDK_INT)
                # canScheduleExactAlarms() only exists on API 31+
                exact_ok = sdk < 31 or self.am.canScheduleExactAlarms()
                if exact_ok:
                    self.am.setExactAndAllowWhileIdle(
                        self.am.RTC_WAKEUP, cal.getTimeInMillis(), pi)
                else:
                    self.am.setAndAllowWhileIdle(
                        self.am.RTC_WAKEUP, cal.getTimeInMillis(), pi)
            except Exception:
                self.am.setAndAllowWhileIdle(
                    self.am.RTC_WAKEUP, cal.getTimeInMillis(), pi)
            return True
        except Exception as e:
            print("Schedule alarm failed:", e)
            return False

    def cancel(self, item):
        if self.am is None:
            return
        try:
            from jnius import autoclass
            PendingIntent = autoclass("android.app.PendingIntent")
            flags = PendingIntent.FLAG_NO_CREATE | PendingIntent.FLAG_IMMUTABLE
            pi = self._pending(item, next_occ(item), None, flags)
            if pi is not None:
                self.am.cancel(pi)
                pi.cancel()
        except Exception as e:
            print("Cancel alarm failed:", e)

    def reschedule_all(self, items):
        for item in items:
            self.schedule(item)

def request_notification_permission():
    """Android 13+ needs runtime POST_NOTIFICATIONS permission."""
    if platform != "android":
        return
    try:
        from android.permissions import request_permissions, Permission
        request_permissions([Permission.POST_NOTIFICATIONS])
    except Exception as e:
        print("Permission request failed:", e)
def parse_date(s):
    s = s.strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None
def parse_date_parts(dd, mm, yyyy):
    """Validate separate DD / MM / YYYY fields.
    Returns (date_or_None, error_message_or_None).
    Kept separate from parse_date() so old stored ISO dates still load.
    """
    dd, mm, yyyy = dd.strip(), mm.strip(), yyyy.strip()
    if not dd or not mm or not yyyy:
        return None, "Enter day, month and year."
    if len(yyyy) != 4:
        return None, "Enter a 4-digit year, e.g. 2026."
    try:
        d, m, y = int(dd), int(mm), int(yyyy)
    except ValueError:
        return None, "Day, month and year must be numbers."
    if not 1 <= m <= 12:
        return None, "Month must be 1 to 12."
    if not 1 <= d <= 31:
        return None, "Day must be 1 to 31."
    if not 1900 <= y <= 2100:
        return None, "Year must be 1900 to 2100."
    try:
        return date(y, m, d), None
    except ValueError:
        # e.g. 31 Feb, 30 Feb, 31 Apr - date() rejects impossible days
        return None, "That date doesn't exist, e.g. 31 Feb."
def with_year(d, y):
    try:
        return d.replace(year=y)
    except ValueError:  # 29 Feb in a non-leap year
        return date(y, 2, 28)
def next_occ(it):
    d = date.fromisoformat(it["date"])
    if not it.get("yearly"):
        return d
    today = date.today()
    c = with_year(d, today.year)
    if c < today:
        c = with_year(d, today.year + 1)
    return c
def label(n):
    if n < 0:
        return "Passed"
    if n == 0:
        return "Today"
    if n == 1:
        return "Tomorrow"
    if n < 14:
        return "In %d days" % n
    if n < 60:
        return "In %d weeks" % round(n / 7)
    return "In %d months" % round(n / 30)
class DatesApp(App):
    def build(self):
        self.title = "Important Dates"
        Window.softinput_mode = "below_target"
        self.path = os.path.join(self.user_data_dir, "dates.json")
        self.items, self.auto = self.load()
        self.speaker = Speaker()
        self.notifier = Notifier()
        self.scheduler = AlarmScheduler()
        request_notification_permission()
        # FIX 2 + FIX 3: re-schedule on every launch (backup for the
        # BootReceiver, which now does this at boot without opening the app).
        self.scheduler.reschedule_all(self.items)
        root = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        root.add_widget(Label(text="Important Dates", font_size="24sp", bold=True,
                              size_hint_y=None, height=dp(44)))
        self.t_in = TextInput(hint_text="What's the occasion?", multiline=False,
                              size_hint_y=None, height=dp(44))
        root.add_widget(self.t_in)
        # FIX 1: Separate DD / MM / YYYY fields.
        # Old code used ONE field with input_type="number" but expected
        # "DD-MM-YYYY" - the numeric keyboard has no "-" or "/" key,
        # so users could not type a date at all on Android.
        # Each field below is numeric-only, so the number keyboard works.
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
        self.dd_in = TextInput(hint_text="DD", multiline=False,
                               input_type="number", input_filter="int")
        self.mm_in = TextInput(hint_text="MM", multiline=False,
                               input_type="number", input_filter="int")
        self.yyyy_in = TextInput(hint_text="YYYY", multiline=False,
                                 input_type="number", input_filter="int")
        # Auto-advance: DD (2 digits) -> MM, MM (2 digits) -> YYYY
        self.dd_in.bind(text=lambda _i, v: self._advance(self.dd_in, self.mm_in, 2, v))
        self.mm_in.bind(text=lambda _i, v: self._advance(self.mm_in, self.yyyy_in, 2, v))
        self.r_in = Spinner(text="1 week before", values=[r[0] for r in REMIND])
        row.add_widget(self.dd_in)
        row.add_widget(self.mm_in)
        row.add_widget(self.yyyy_in)
        row.add_widget(self.r_in)
        root.add_widget(row)
        row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self.y_in = CheckBox(size_hint_x=None, width=dp(40))
        row.add_widget(self.y_in)
        row.add_widget(Label(text="Repeats every year", halign="left"))
        root.add_widget(row)
        add = Button(text="Add date", size_hint_y=None, height=dp(48),
                     background_normal="", background_color=ACCENT, bold=True)
        add.bind(on_release=self.add_item)
        root.add_widget(add)
        self.status = Label(text="", size_hint_y=None, height=dp(22), font_size="13sp")
        root.add_widget(self.status)
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        read = Button(text="Read my upcoming dates")
        read.bind(on_release=lambda *_: self.read_upcoming())
        row.add_widget(read)
        self.auto_cb = CheckBox(active=self.auto, size_hint_x=None, width=dp(40))
        self.auto_cb.bind(active=self.set_auto)
        row.add_widget(self.auto_cb)
        row.add_widget(Label(text="Speak on open", size_hint_x=None, width=dp(100),
                             font_size="13sp"))
        root.add_widget(row)
        self.banner = Label(text="", markup=True, size_hint_y=None, height=0, halign="left",
                            valign="middle", color=(1, 0.65, 0.4, 1))
        self.banner.bind(size=lambda i, s: setattr(i, "text_size", (s[0], None)),
                         texture_size=lambda i, t: setattr(i, "height", t[1] + dp(8) if i.text else 0))
        root.add_widget(self.banner)
        sv = ScrollView()
        self.box = GridLayout(cols=1, spacing=dp(8), size_hint_y=None)
        self.box.bind(minimum_height=self.box.setter("height"))
        sv.add_widget(self.box)
        root.add_widget(sv)
        self.refresh()
        if self.auto:
            Clock.schedule_once(lambda dt: self.read_upcoming(), 1.5)
        Clock.schedule_interval(lambda dt: self.refresh(), 3600)
        return root
    # storage
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("items", []), bool(data.get("auto", False))
        except Exception:
            return [], False
    def shared_path(self):
        """Path Java BootReceiver can read (Python's user_data_dir is not
        reliably the same path from Java, so use getFilesDir() directly)."""
        if platform == "android":
            try:
                from jnius import autoclass
                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                return os.path.join(activity.getFilesDir().getAbsolutePath(),
                                    "dates_reminders.json")
            except Exception:
                pass
        return os.path.join(os.path.dirname(self.path), "dates_reminders.json")
    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"items": self.items, "auto": self.auto}, f)
        except Exception as e:
            self.status.text = "Couldn't save: %s" % e
            return
        # FIX 3: keep the Java-readable copy in sync on EVERY save.
        # BootReceiver reads this file at boot - if it is stale, the
        # re-scheduled alarms will be stale too. add_item/remove/set_auto
        # all go through save(), so one place covers them all.
        try:
            with open(self.shared_path(), "w", encoding="utf-8") as f:
                json.dump({"items": self.items, "auto": self.auto}, f)
        except Exception as e:
            print("Shared reminders save failed:", e)
    def set_auto(self, _cb, value):
        self.auto = value
        self.save()
    # actions
    def _advance(self, current, nxt, max_len, value):
        """Move focus to the next date field once this one is full."""
        if len(value) >= max_len:
            # Truncate pasted / over-typed digits instead of overflowing
            current.text = value[:max_len]
            nxt.focus = True
    def add_item(self, *_):
        title = self.t_in.text.strip()
        d, err = parse_date_parts(self.dd_in.text, self.mm_in.text,
                                  self.yyyy_in.text)
        if not title:
            self.status.text = "Enter a title."
            return
        if d is None:
            self.status.text = err
            return
        remind = dict(REMIND).get(self.r_in.text, 7)
        self.items.append({"id": str(datetime.now().timestamp()), "title": title,
                           "date": d.isoformat(), "yearly": self.y_in.active,
                           "remind": remind})
        self.save()
        self.scheduler.schedule(self.items[-1])
        self.t_in.text = ""
        self.dd_in.text = ""
        self.mm_in.text = ""
        self.yyyy_in.text = ""
        self.y_in.active = False
        self.status.text = "Added."
        self.refresh()
    def remove(self, item_id):
        doomed = [i for i in self.items if i["id"] == item_id]
        for i in doomed:
            self.scheduler.cancel(i)
        self.items = [i for i in self.items if i["id"] != item_id]
        self.save()
        self.refresh()
    def rows(self):
        today = date.today()
        out = []
        for it in self.items:
            o = next_occ(it)
            n = (o - today).days
            out.append({"it": it, "o": o, "n": n, "soon": 0 <= n <= it.get("remind", 0)})
        out.sort(key=lambda r: (r["n"] < 0, abs(r["n"])))
        return out
    def phrase(self, r):
        return "%s, %s, %s." % (r["it"]["title"], label(r["n"]).lower(),
                                r["o"].strftime("%A %d %B"))
    def say(self, text):
        if not self.speaker.speak(text):
            self.status.text = "Speech isn't available on this device."
    def read_upcoming(self):
        rows = self.rows()
        sel = [r for r in rows if r["soon"]] or [r for r in rows if r["n"] >= 0][:3]
        if not sel:
            self.say("You have no upcoming dates.")
            return
        self.say("Here are your upcoming dates. " + " ".join(self.phrase(r) for r in sel))
    def refresh(self):
        rows = self.rows()
        self.box.clear_widgets()
        if not rows:
            self.box.add_widget(Label(text="No dates yet. Add your first one above.",
                                      size_hint_y=None, height=dp(60)))
        soon = [r for r in rows if r["soon"]]
        self.banner.text = ("[b]Coming up[/b]\n" + "\n".join(
            "%s - %s" % (escape_markup(r["it"]["title"]), label(r["n"]).lower())
            for r in soon)) if soon else ""
        for r in rows:
            row = BoxLayout(size_hint_y=None, height=dp(72), spacing=dp(6))
            txt = "[b]%s[/b]\n%s - %s%s" % (
                escape_markup(r["it"]["title"]), label(r["n"]),
                r["o"].strftime("%a %d %b %Y"), "  (yearly)" if r["it"].get("yearly") else "")
            lb = Label(text=txt, markup=True, halign="left", valign="middle",
                       color=(1, 0.65, 0.4, 1) if r["soon"] else (1, 1, 1, 0.5 if r["n"] < 0 else 1))
            lb.bind(size=lambda i, s: setattr(i, "text_size", s))
            sp = Button(text="Say", size_hint_x=None, width=dp(56))
            sp.bind(on_release=lambda _b, rr=r: self.say(self.phrase(rr)))
            x = Button(text="X", size_hint_x=None, width=dp(48))
            x.bind(on_release=lambda _b, i=r["it"]["id"]: self.remove(i))
            row.add_widget(lb)
            row.add_widget(sp)
            row.add_widget(x)
            self.box.add_widget(row)
if __name__ == "__main__":
    DatesApp().run()
