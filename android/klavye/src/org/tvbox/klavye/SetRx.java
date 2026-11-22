package org.tvbox.klavye;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/**
 * Manifest-declared receiver for org.tvbox.klavye.SET (permission DUMP, so only adb shell can send).
 * Works before the IME was ever shown: the process starts on demand and the option is written to
 * SharedPreferences; the keyboard picks it up on its next start (Settings.sig / onStartInputView).
 * Top-level class: this d8 toolchain cannot dex anonymous or non-static inner classes.
 */
public class SetRx extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent i) {
        String key = i.getStringExtra("key"), value = i.getStringExtra("value");
        boolean ok = Settings.set(c, key, value);
        android.util.Log.i("KlavyeSet", (ok ? "applied " : "rejected ") + key + "=" + value);
        setResultCode(ok ? 1 : 0);
    }
}
