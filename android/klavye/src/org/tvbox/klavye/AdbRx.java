package org.tvbox.klavye;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Top-level receiver (no anonymous/inner classes: D8 on this toolchain chokes on them). */
public class AdbRx extends BroadcastReceiver {
    public interface Sink {
        void onAdb(Intent i);
    }

    private final Sink sink;

    public AdbRx(Sink sink) {
        this.sink = sink;
    }

    @Override
    public void onReceive(Context c, Intent i) {
        sink.onAdb(i);
    }
}
