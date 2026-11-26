package org.importantdates;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;

public class BootReceiver extends BroadcastReceiver {
    private static final String TAG = "ImportantDatesBoot";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null || !Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) return;
        try {
            ReminderScheduler.rescheduleAll(context);
        } catch (Exception e) {
            Log.e(TAG, "Boot reschedule failed", e);
        }
    }
}
