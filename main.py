import json
import os
from datetime import date, datetime

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


def parse_date(s):
    s = s.strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


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

        root = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        root.add_widget(Label(text="Important Dates", font_size="24sp", bold=True,
                              size_hint_y=None, height=dp(44)))

        self.t_in = TextInput(hint_text="What's the occasion?", multiline=False,
                              size_hint_y=None, height=dp(44))
        root.add_widget(self.t_in)

        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        self.d_in = TextInput(hint_text="DD-MM-YYYY", multiline=False, input_type="number")
        self.r_in = Spinner(text="1 week before", values=[r[0] for r in REMIND])
        row.add_widget(self.d_in)
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

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"items": self.items, "auto": self.auto}, f)
        except Exception as e:
            self.status.text = "Couldn't save: %s" % e

    def set_auto(self, _cb, value):
        self.auto = value
        self.save()

    # actions
    def add_item(self, *_):
        title = self.t_in.text.strip()
        d = parse_date(self.d_in.text)
        if not title:
            self.status.text = "Enter a title."
            return
        if d is None:
            self.status.text = "Enter the date like 25-12-2026."
            return
        remind = dict(REMIND).get(self.r_in.text, 7)
        self.items.append({"id": str(datetime.now().timestamp()), "title": title,
                           "date": d.isoformat(), "yearly": self.y_in.active,
                           "remind": remind})
        self.save()
        self.t_in.text = ""
        self.d_in.text = ""
        self.y_in.active = False
        self.status.text = "Added."
        self.refresh()

    def remove(self, item_id):
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
