package org.importantdates;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.security.MessageDigest;
import java.util.Calendar;
import java.util.Locale;

/** Shared scheduling logic for BootReceiver and AlarmReceiver. */
final class ReminderScheduler {
    private static final String TAG = "ImportantDatesSched";
    static final String ACTION_REMINDER = "org.importantdates.REMINDER";

    private ReminderScheduler() {}

    /** Same algorithm as Python: first 4 bytes of SHA-256(id), masked positive. */
    static int requestCode(String id) throws Exception {
        byte[] d = MessageDigest.getInstance("SHA-256").digest(id.getBytes("UTF-8"));
        int v = ((d[0] & 0xff) << 24) | ((d[1] & 0xff) << 16)
              | ((d[2] & 0xff) << 8) | (d[3] & 0xff);
        return v & 0x7fffffff;
    }

    static JSONArray loadItems(Context ctx) throws Exception {
        File f = new File(ctx.getFilesDir(), "dates_reminders.json");
        if (!f.exists()) return null;
        return new JSONObject(readFile(f)).optJSONArray("items");
    }

    /** Boot: re-create every future alarm. */
    static void rescheduleAll(Context ctx) throws Exception {
        JSONArray items = loadItems(ctx);
        if (items == null) return;
        Calendar now = Calendar.getInstance();
        for (int i = 0; i < items.length(); i++) {
            JSONObject it = items.optJSONObject(i);
            if (it == null) continue;
            try {
                Calendar occ = nextOccurrence(it, now);
                if (occ != null) schedule(ctx, it, occ);
            } catch (Exception e) {
                Log.e(TAG, "Skipping bad item", e);
            }
        }
    }

    /** After a yearly alarm fires: arm the same date one year later. */
    static void rearmYearly(Context ctx, String id, String firedIso) throws Exception {
        if (id == null || id.isEmpty() || firedIso == null || firedIso.length() < 10) return;
        JSONArray items = loadItems(ctx);
        if (items == null) return;
        for (int i = 0; i < items.length(); i++) {
            JSONObject it = items.optJSONObject(i);
            if (it == null || !id.equals(it.optString("id", ""))) continue;
            if (!it.optBoolean("yearly", false)) return;
            String ds = it.optString("date", "");
            if (ds.length() < 10) return;
            int month = Integer.parseInt(ds.substring(5, 7));
            int day = Integer.parseInt(ds.substring(8, 10));
            int firedYear = Integer.parseInt(firedIso.substring(0, 4));
            Calendar next = Calendar.getInstance();
            setSafeDate(next, firedYear + 1, month, day);
            schedule(ctx, it, next);
            return;
        }
    }

    static Calendar nextOccurrence(JSONObject it, Calendar now) {
        String ds = it.optString("date", "");
        if (ds.length() < 10) return null;
        int y = Integer.parseInt(ds.substring(0, 4));
        int m = Integer.parseInt(ds.substring(5, 7));
        int d = Integer.parseInt(ds.substring(8, 10));
        Calendar occ = Calendar.getInstance();
        if (it.optBoolean("yearly", false)) {
            int year = now.get(Calendar.YEAR);
            setSafeDate(occ, year, m, d);
            if (occ.before(todayStart(now))) setSafeDate(occ, year + 1, m, d);
        } else {
            setSafeDate(occ, y, m, d);
        }
        return occ;
    }

    /** Arm one alarm: trigger = occurrence - remind days, at 09:00. */
    static void schedule(Context ctx, JSONObject it, Calendar occ) throws Exception {
        String id = it.optString("id", "");
        if (id.isEmpty()) return;
        int remind = Math.max(0, it.optInt("remind", 7));
        Calendar trig = (Calendar) occ.clone();
        trig.add(Calendar.DAY_OF_YEAR, -remind);
        trig.set(Calendar.HOUR_OF_DAY, 9);
        trig.set(Calendar.MINUTE, 0);
        trig.set(Calendar.SECOND, 0);
        trig.set(Calendar.MILLISECOND, 0);
        if (!trig.after(Calendar.getInstance())) return;

        Intent in = new Intent(ctx, AlarmReceiver.class);
        in.setAction(ACTION_REMINDER);
        in.putExtra("reminder_id", id);
        in.putExtra("reminder_title", it.optString("title", "Important date"));
        in.putExtra("reminder_date", String.format(Locale.US, "%04d-%02d-%02d",
            occ.get(Calendar.YEAR), occ.get(Calendar.MONTH) + 1,
            occ.get(Calendar.DAY_OF_MONTH)));
        PendingIntent pi = PendingIntent.getBroadcast(ctx, requestCode(id), in,
            PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

        AlarmManager am = (AlarmManager) ctx.getSystemService(Context.ALARM_SERVICE);
        long t = trig.getTimeInMillis();
        try {
            if (Build.VERSION.SDK_INT < 31 || am.canScheduleExactAlarms()) {
                am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, t, pi);
            } else {
                am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, t, pi);
            }
        } catch (SecurityException e) {
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, t, pi);
        }
        Log.i(TAG, "Armed " + id + " at " + trig.getTime());
    }

    private static Calendar todayStart(Calendar src) {
        Calendar c = (Calendar) src.clone();
        c.set(Calendar.HOUR_OF_DAY, 0); c.set(Calendar.MINUTE, 0);
        c.set(Calendar.SECOND, 0); c.set(Calendar.MILLISECOND, 0);
        return c;
    }

    /** Clamp the day to the month's length (29 Feb -> 28 Feb in non-leap years). */
    static void setSafeDate(Calendar c, int year, int month, int day) {
        c.clear();
        c.set(Calendar.YEAR, year);
        c.set(Calendar.MONTH, month - 1);
        c.set(Calendar.DAY_OF_MONTH, 1);
        int max = c.getActualMaximum(Calendar.DAY_OF_MONTH);
        c.set(Calendar.DAY_OF_MONTH, Math.min(day, max));
    }

    private static String readFile(File f) throws Exception {
        FileInputStream in = new FileInputStream(f);
        try {
            byte[] data = new byte[(int) f.length()];
            int off = 0, n;
            while (off < data.length && (n = in.read(data, off, data.length - off)) > 0) off += n;
            return new String(data, "UTF-8");
        } finally { in.close(); }
    }
}
