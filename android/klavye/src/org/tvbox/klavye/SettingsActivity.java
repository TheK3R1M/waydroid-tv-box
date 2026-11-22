package org.tvbox.klavye;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

/**
 * TV Klavye settings. D-pad: up/down moves between rows, OK toggles or cycles the focused row, Back exits.
 * No lambdas/anonymous classes: the D8 on the build host cannot dex them.
 */
public class SettingsActivity extends Activity {

    private static final String[] ROWS = {Settings.SUGGEST, Settings.HINTS, Settings.MIC, Settings.LEARN,
            Settings.LAYOUT, Settings.KEYSIZE, Settings.LANG, Settings.RESET};

    /** Click + focus handler per row (static nested, not anonymous). */
    static final class Row implements View.OnClickListener, View.OnFocusChangeListener {
        private final SettingsActivity act;
        private final String key;
        private final TextView view;

        Row(SettingsActivity act, String key, TextView view) {
            this.act = act;
            this.key = key;
            this.view = view;
        }

        @Override
        public void onClick(View v) {
            act.change(key);
            view.setText(act.label(key));
        }

        @Override
        public void onFocusChange(View v, boolean hasFocus) {
            act.paint(view, hasFocus);
        }
    }

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        ScrollView sv = new ScrollView(this);
        sv.setBackgroundColor(0xFF0A0D12);
        LinearLayout list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        list.setPadding(dp(40), dp(28), dp(40), dp(28));

        TextView head = new TextView(this);
        head.setText("TV Klavye 4.0 settings\nOK: change    Back: close");
        head.setTextColor(0xFFECEFF4);
        head.setTextSize(20);
        head.setTypeface(null, Typeface.BOLD);
        head.setPadding(0, 0, 0, dp(16));
        list.addView(head, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        for (String key : ROWS) {
            TextView t = new TextView(this);
            t.setText(label(key));
            t.setTextSize(20);
            t.setGravity(Gravity.CENTER_VERTICAL);
            t.setPadding(dp(20), 0, dp(20), 0);
            t.setFocusable(true);
            t.setClickable(true);
            Row row = new Row(this, key, t);
            t.setOnClickListener(row);
            t.setOnFocusChangeListener(row);
            paint(t, false);
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, dp(64));
            lp.setMargins(0, dp(6), 0, dp(6));
            list.addView(t, lp);
        }
        sv.addView(list);
        setContentView(sv);
    }

    String label(String key) {
        if (Settings.SUGGEST.equals(key)) return "Word suggestions: " + onOff(Settings.suggest(this));
        if (Settings.HINTS.equals(key)) return "Letter hints (next-letter chips): " + onOff(Settings.letterHints(this));
        if (Settings.MIC.equals(key)) return "Mic key: " + onOff(Settings.mic(this));
        if (Settings.LEARN.equals(key)) return "Learn from my typing: " + onOff(Settings.learn(this));
        if (Settings.LAYOUT.equals(key)) {
            String l = Settings.layout(this);
            String name = "classic".equals(l) ? "Classic QWERTY" : "compact".equals(l) ? "Compact QWERTY" : "Square ABC";
            return "Layout: " + name;
        }
        if (Settings.KEYSIZE.equals(key)) return "Key size: " + ("large".equals(Settings.keysize(this)) ? "Large" : "Normal");
        if (Settings.LANG.equals(key)) return "Language: " + ("en".equals(Settings.lang(this)) ? "English" : "Turkish");
        if (Settings.RESET.equals(key)) return "Reset learned words";
        return key;
    }

    void change(String key) {
        if (Settings.RESET.equals(key)) {
            Settings.resetLearned(this);
            Toast.makeText(this, "Learned words cleared", Toast.LENGTH_SHORT).show();
            return;
        }
        if (Settings.LAYOUT.equals(key)) {
            String l = Settings.layout(this);
            String next = "square".equals(l) ? "classic" : "classic".equals(l) ? "compact" : "square";
            Settings.sp(this).edit().putString(Settings.LAYOUT, next).commit();
        } else if (Settings.KEYSIZE.equals(key)) {
            String next = "large".equals(Settings.keysize(this)) ? "normal" : "large";
            Settings.sp(this).edit().putString(Settings.KEYSIZE, next).commit();
        } else if (Settings.LANG.equals(key)) {
            String next = "en".equals(Settings.lang(this)) ? "tr" : "en";
            Settings.sp(this).edit().putString(Settings.LANG, next).commit();
        } else {
            boolean cur = Settings.sp(this).getBoolean(key, !Settings.LEARN.equals(key) && !Settings.SUGGEST.equals(key)
                    ? false : true);
            Settings.sp(this).edit().putBoolean(key, !cur).commit();
        }
    }

    void paint(TextView t, boolean focused) {
        GradientDrawable g = new GradientDrawable();
        g.setCornerRadius(dp(12));
        if (focused) {
            g.setColor(0xFFFFD54F);
            g.setStroke(dp(3), 0xFFFFFFFF);
            t.setTextColor(Color.BLACK);
            t.setTypeface(null, Typeface.BOLD);
        } else {
            g.setColor(0xFF262C36);
            t.setTextColor(0xFFECEFF4);
            t.setTypeface(null, Typeface.NORMAL);
        }
        t.setBackground(g);
    }

    private static String onOff(boolean b) {
        return b ? "On" : "Off";
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
