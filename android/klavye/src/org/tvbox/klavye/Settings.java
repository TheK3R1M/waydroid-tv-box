package org.tvbox.klavye;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.Locale;

/** TV Klavye settings, stored in SharedPreferences "settings". Values returned below are the fresh-install defaults. */
final class Settings {
    static final String FILE = "settings";
    static final String SUGGEST = "suggest", HINTS = "letter_hints", MIC = "mic", LEARN = "learn",
            LAYOUT = "layout", KEYSIZE = "keysize", LANG = "lang", RESET = "reset_learned";
    private static final String GEN = "reset_gen";

    private Settings() {
    }

    static SharedPreferences sp(Context c) {
        return c.getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    static boolean suggest(Context c) { return sp(c).getBoolean(SUGGEST, true); }

    static boolean letterHints(Context c) { return sp(c).getBoolean(HINTS, false); }

    static boolean mic(Context c) { return sp(c).getBoolean(MIC, false); }

    static boolean learn(Context c) { return sp(c).getBoolean(LEARN, true); }

    /** square | classic | compact */
    static String layout(Context c) { return sp(c).getString(LAYOUT, "square"); }

    /** normal | large */
    static String keysize(Context c) { return sp(c).getString(KEYSIZE, "normal"); }

    /** tr | en */
    static String lang(Context c) { return sp(c).getString(LANG, "tr"); }

    /** Changes when the word list must be reloaded (language, learning, or learned-words reset). */
    static String sig(Context c) {
        return lang(c) + "|" + learn(c) + "|" + sp(c).getInt(GEN, 0);
    }

    static void resetLearned(Context c) {
        c.getSharedPreferences("learn", Context.MODE_PRIVATE).edit().clear().commit();
        c.getSharedPreferences("learn_en", Context.MODE_PRIVATE).edit().clear().commit();
        sp(c).edit().putInt(GEN, sp(c).getInt(GEN, 0) + 1).commit();
    }

    /** Applies one option (also used by the org.tvbox.klavye.SET broadcast). False = unknown key or bad value. */
    static boolean set(Context c, String key, String value) {
        if (key == null || value == null) return false;
        String v = value.trim().toLowerCase(Locale.ROOT);
        if (RESET.equals(key)) {
            resetLearned(c);
            return true;
        }
        SharedPreferences.Editor e = sp(c).edit();
        if (SUGGEST.equals(key) || HINTS.equals(key) || MIC.equals(key) || LEARN.equals(key)) {
            Boolean b = bool(v);
            if (b == null) return false;
            e.putBoolean(key, b.booleanValue());
        } else if (LAYOUT.equals(key)) {
            if (!"square".equals(v) && !"classic".equals(v) && !"compact".equals(v)) return false;
            e.putString(key, v);
        } else if (KEYSIZE.equals(key)) {
            if (!"normal".equals(v) && !"large".equals(v)) return false;
            e.putString(key, v);
        } else if (LANG.equals(key)) {
            if (!"tr".equals(v) && !"en".equals(v)) return false;
            e.putString(key, v);
        } else {
            return false;
        }
        return e.commit();
    }

    private static Boolean bool(String v) {
        if ("true".equals(v) || "1".equals(v) || "on".equals(v) || "yes".equals(v)) return Boolean.TRUE;
        if ("false".equals(v) || "0".equals(v) || "off".equals(v) || "no".equals(v)) return Boolean.FALSE;
        return null;
    }
}
