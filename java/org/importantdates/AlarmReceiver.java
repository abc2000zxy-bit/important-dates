package org.importantdates;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.util.Log;

public class AlarmReceiver extends BroadcastReceiver {
    private static final String TAG = "ImportantDatesAlarm";
    private static final String CHANNEL_ID = "dates";

    private static int safeId(String a, String b) {
        return (a + "|" + b).hashCode() & 0x7fffffff;
    }

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !ReminderScheduler.ACTION_REMINDER.equals(intent.getAction())) return;
        String id = intent.getStringExtra("reminder_id");
        String title = intent.getStringExtra("reminder_title");
        String date = intent.getStringExtra("reminder_date");
        if (title == null || title.trim().isEmpty()) title = "Important date";
        if (date == null) date = "";

        // Re-arm next year's alarm first, so it happens even if the
        // notification below is skipped (e.g. permission denied).
        try {
            ReminderScheduler.rearmYearly(context, id, date);
        } catch (Exception e) {
            Log.e(TAG, "Yearly re-arm failed", e);
        }

        NotificationManager nm = (NotificationManager)
            context.getSystemService(Context.NOTIFICATION_SERVICE);
        if (nm == null) return;

        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, "Important Dates", NotificationManager.IMPORTANCE_HIGH);
            channel.setDescription("Reminders for your important dates");
            nm.createNotificationChannel(channel);
        }

        if (Build.VERSION.SDK_INT >= 33 &&
            context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            Log.w(TAG, "POST_NOTIFICATIONS not granted; notification skipped");
            return;
        }

        Intent open = context.getPackageManager()
            .getLaunchIntentForPackage(context.getPackageName());
        PendingIntent content = null;
        if (open != null) {
            open.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            content = PendingIntent.getActivity(context, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        }

        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
            ? new Notification.Builder(context, CHANNEL_ID)
            : new Notification.Builder(context);
        builder.setSmallIcon(context.getApplicationInfo().icon)
            .setContentTitle("Reminder: " + title)
            .setContentText(date)
            .setAutoCancel(true)
            .setPriority(Notification.PRIORITY_HIGH);
        if (content != null) builder.setContentIntent(content);
        nm.notify(safeId(title, date), builder.build());
    }
}
