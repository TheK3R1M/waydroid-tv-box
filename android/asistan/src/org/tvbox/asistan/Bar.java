package org.tvbox.asistan;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Handler;
import android.os.Looper;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * Voice-assistant bar for the TV (Google-Assistant style), drawn as a non-focusable overlay at
 * the bottom of the screen, so the app underneath keeps focus (a search field stays open while you dictate).
 * Not FLAG_NOT_TOUCHABLE: Android 12+ caps such pass-through overlays at 80 % opacity (unreadable over video).
 * Driven only by the host over adb:
 *   am broadcast -f 0x20 -n org.tvbox.asistan/.Bar --es state listen|think|say|err|hide --es text T [--es sub S]
 * The receiver is protected by android.permission.DUMP (held by the adb shell, not by normal apps).
 */
public class Bar extends BroadcastReceiver {
    static View root;
    static TextView title, sub;
    static Dots dots;
    static WindowManager wm;
    static final Handler H = new Handler(Looper.getMainLooper());
    static final Runnable HIDE = new Runnable() { public void run() { hide(); } };

    @Override
    public void onReceive(Context c, Intent i) {
        String st = i.getStringExtra("state");
        if (st == null || "hide".equals(st)) { hide(); return; }
        ensure(c.getApplicationContext());
        String t = i.getStringExtra("text"), s = i.getStringExtra("sub");
        dots.mode = "think".equals(st) ? 1 : "say".equals(st) ? 2 : "err".equals(st) ? 3 : 0;
        title.setText(t == null ? "" : t);
        int col = i.getIntExtra("color", 0);       // optional title colour (volume boost = orange)
        title.setTextColor(col != 0 ? (0xFF000000 | col) : Color.WHITE);
        sub.setText(s == null ? "" : s);
        sub.setVisibility(s == null || s.isEmpty() ? View.GONE : View.VISIBLE);
        H.removeCallbacks(HIDE);
        int ms = i.getIntExtra("ms", "listen".equals(st) ? 9000 : "think".equals(st) ? 20000 : 4000);
        H.postDelayed(HIDE, ms);
    }

    static float dp(Context c, float v) {
        return TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, c.getResources().getDisplayMetrics());
    }

    static void ensure(Context a) {
        if (root != null) return;
        wm = (WindowManager) a.getSystemService(Context.WINDOW_SERVICE);
        LinearLayout row = new LinearLayout(a);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        int p = (int) dp(a, 18);
        row.setPadding(p + p / 2, p, p * 2, p);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.rgb(24, 26, 32));
        bg.setCornerRadius(dp(a, 40));
        bg.setStroke((int) dp(a, 1.5f), Color.argb(90, 255, 255, 255));
        row.setBackground(bg);
        row.setMinimumWidth((int) dp(a, 420));
        dots = new Dots(a);
        row.addView(dots, new LinearLayout.LayoutParams((int) dp(a, 92), (int) dp(a, 44)));
        LinearLayout col = new LinearLayout(a);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(p, 0, 0, 0);
        title = new TextView(a);
        title.setTextColor(Color.WHITE);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setSingleLine(true);
        title.setEllipsize(android.text.TextUtils.TruncateAt.END);
        title.setMaxWidth((int) dp(a, 900));
        sub = new TextView(a);
        sub.setTextColor(Color.argb(210, 200, 205, 215));
        sub.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        sub.setSingleLine(true);
        sub.setEllipsize(android.text.TextUtils.TruncateAt.END);
        sub.setMaxWidth((int) dp(a, 900));
        row.setGravity(Gravity.CENTER_VERTICAL | Gravity.START);
        col.addView(title);
        col.addView(sub);
        row.addView(col, new LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f));
        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                PixelFormat.TRANSLUCENT);
        lp.width = (int) (a.getResources().getDisplayMetrics().widthPixels * 0.62);   // wrap_content + ellipsize
        lp.gravity = Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL;                         // measured too narrow
        lp.y = (int) dp(a, 36);
        lp.setTitle("TV Asistan");
        root = row;
        wm.addView(root, lp);
    }

    static void hide() {
        H.removeCallbacks(HIDE);
        if (root != null) {
            try { wm.removeView(root); } catch (Exception ignored) { }
            root = null;
        }
    }

    /** Four coloured dots: bounce = listening, pulse = thinking, still = answer, red = error. */
    static class Dots extends View {
        int mode;
        final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        final int[] colors = {0xFF4285F4, 0xFFEA4335, 0xFFFBBC05, 0xFF34A853};
        final long t0 = System.currentTimeMillis();

        Dots(Context c) { super(c); }

        @Override
        protected void onDraw(Canvas cv) {
            float w = getWidth(), h = getHeight(), t = (System.currentTimeMillis() - t0) / 1000f;
            float step = w / 4f, r0 = Math.min(step, h) * 0.22f;
            for (int k = 0; k < 4; k++) {
                float cx = step * (k + 0.5f), cy = h / 2f, r = r0;
                if (mode == 0) cy = h / 2f - (h * 0.28f) * Math.abs((float) Math.sin(t * 5.5 + k * 0.7));
                else if (mode == 1) r = r0 * (0.75f + 0.45f * (float) Math.abs(Math.sin(t * 6 - k * 0.9)));
                paint.setColor(mode == 3 ? 0xFFEA4335 : colors[k]);
                cv.drawCircle(cx, cy, r, paint);
            }
            if (mode == 0 || mode == 1) postInvalidateOnAnimation();
        }
    }
}
