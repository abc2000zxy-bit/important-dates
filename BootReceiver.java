package org.importantdates;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
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

public class BootReceiver extends BroadcastReceiver {
    private static final String TAG = "ImportantDatesBoot";
    private static final String ACTION_REMINDER = "org.importantdates.REMINDER";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) return;
        try {
            File file = new File(context.getFilesDir(), "dates_reminders.json");
            if (!file.exists()) return;
            JSONObject root = new JSONObject(readFile(file));
            JSONArray items = root.optJSONArray("items");
            if (items == null) return;

            AlarmManager am = (AlarmManager) context.getSystemService(Context.ALARM_SERVICE);
            Calendar now = Calendar.getInstance();
            for (int i = 0; i < items.length(); i++) {
                JSONObject item = items.optJSONObject(i);
                if (item == null) continue;
                String id = item.optString("id", "");
                String title = item.optString("title", "Important date");
                String dateText = item.optString("date", "");
                int remind = Math.max(0, item.optInt("remind", 7));
                boolean yearly = item.optBoolean("yearly", false);
                if (id.isEmpty() || dateText.length() < 10) continue;

                int y = Integer.parseInt(dateText.substring(0, 4));
                int m = Integer.parseInt(dateText.substring(5, 7));
                int d = Integer.parseInt(dateText.substring(8, 10));

                Calendar occurrence = Calendar.getInstance();
                occurrence.clear();
                if (yearly) {
                    int year = now.get(Calendar.YEAR);
                    setSafeDate(occurrence, year, m, d);
                    if (occurrence.before(todayStart(now))) setSafeDate(occurrence, year + 1, m, d);
                } else {
                    setSafeDate(occurrence, y, m, d);
                }

                Calendar trigger = (Calendar) occurrence.clone();
                trigger.add(Calendar.DAY_OF_YEAR, -remind);
                trigger.set(Calendar.HOUR_OF_DAY, 9);
                trigger.set(Calendar.MINUTE, 0);
                trigger.set(Calendar.SECOND, 0);
                trigger.set(Calendar.MILLISECOND, 0);
                if (!trigger.after(now)) continue;

                Intent alarmIntent = new Intent(context, AlarmReceiver.class);
                alarmIntent.setAction(ACTION_REMINDER);
                alarmIntent.putExtra("reminder_id", id);
                alarmIntent.putExtra("reminder_title", title);
                alarmIntent.putExtra("reminder_date", String.format(
                    java.util.Locale.US, "%04d-%02d-%02d",
                    occurrence.get(Calendar.YEAR), occurrence.get(Calendar.MONTH) + 1,
                    occurrence.get(Calendar.DAY_OF_MONTH)));

                PendingIntent pi = PendingIntent.getBroadcast(
                    context, requestCode(id), alarmIntent,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);

                try {
                    if (Build.VERSION.SDK_INT >= 31 && am.canScheduleExactAlarms()) {
                        am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,
                            trigger.getTimeInMillis(), pi);
                    } else {
                        am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,
                            trigger.getTimeInMillis(), pi);
                    }
                } catch (SecurityException ex) {
                    am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP,
                        trigger.getTimeInMillis(), pi);
                }
            }
        } catch (Exception e) {
            Log.e(TAG, "Boot reschedule failed", e);
        }
    }

    static int requestCode(String id) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(id.getBytes("UTF-8"));
        int value = ((digest[0] & 0xff) << 24) | ((digest[1] & 0xff) << 16)
                  | ((digest[2] & 0xff) << 8) | (digest[3] & 0xff);
        return value & 0x7fffffff;
    }

    private static Calendar todayStart(Calendar source) {
        Calendar c = (Calendar) source.clone();
        c.set(Calendar.HOUR_OF_DAY, 0); c.set(Calendar.MINUTE, 0);
        c.set(Calendar.SECOND, 0); c.set(Calendar.MILLISECOND, 0);
        return c;
    }

    private static void setSafeDate(Calendar c, int year, int month, int day) {
        c.clear();
        c.set(Calendar.YEAR, year);
        c.set(Calendar.MONTH, month - 1);
        c.set(Calendar.DAY_OF_MONTH, 1);
        int max = c.getActualMaximum(Calendar.DAY_OF_MONTH);
        c.set(Calendar.DAY_OF_MONTH, Math.min(day, max)); // 29 Feb -> 28 Feb if needed
    }

    private static String readFile(File f) throws Exception {
        FileInputStream in = new FileInputStream(f);
        try {
            byte[] data = new byte[(int) f.length()];
            int offset = 0, count;
            while ((count = in.read(data, offset, data.length - offset)) > 0) offset += count;
            return new String(data, "UTF-8");
        } finally { in.close(); }
    }
}
