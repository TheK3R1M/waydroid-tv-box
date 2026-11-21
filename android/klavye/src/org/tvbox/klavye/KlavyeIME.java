package org.tvbox.klavye;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.inputmethodservice.InputMethodService;
import android.os.Build;
import android.os.SystemClock;
import android.util.Log;
import android.util.Base64;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.ExtractedText;
import android.view.inputmethod.ExtractedTextRequest;
import android.view.inputmethod.InputConnection;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.nio.charset.Charset;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * TV Klavye: on-screen Turkish Q keyboard for Android TV, D-pad / pointer driven,
 * plus ADBKeyboard-compatible broadcast injection (protected by android.permission.DUMP).
 */
public class KlavyeIME extends InputMethodService implements View.OnClickListener, AdbRx.Sink {

    private static final int T_CHAR = 0, T_SHIFT = 1, T_BACK = 2, T_SPACE = 3,
            T_SYM = 4, T_CLEAR = 5, T_ENTER = 6, T_HIDE = 7, T_WORD = 8, T_MIC = 9;
    private static final Locale TR = new Locale("tr", "TR");
    private static final String PERM = "android.permission.DUMP";
    private static final int KEY_H_DP = 54, MARGIN_DP = 3;
    private static final long BACK_REPEAT_MS = 250;

    private static final class K {
        final String label, out;
        final int type;
        final float w;
        int r, c;

        K(String label, String out, int type, float w) {
            this.label = label;
            this.out = out;
            this.type = type;
            this.w = w;
        }
    }

    private final List<List<K>> rows = new ArrayList<>();
    private final List<List<TextView>> views = new ArrayList<>();
    LinearLayout root;
    private FrameLayout frame, hintLayer;
    private final TextView[] hintViews = new TextView[3];
    volatile Predictor pred;
    private List<String> sugg = new ArrayList<>();
    private List<String> hints = new ArrayList<>();
    private boolean hintsOn;      // 3 likely next letters shown above the focused key
    private int hsel = -1;        // chip highlighted while the swap window is open (0 left, 1 centre, 2 right)
    private boolean swapping;     // UP typed the centre letter; LEFT/RIGHT now swap it for a side letter
    private long swapUntil;
    private static final long SWAP_MS = 1400;
    private final Runnable swapEnd = new SwapEnd(this);

    private static final class SwapEnd implements Runnable {
        private final KlavyeIME ime;
        SwapEnd(KlavyeIME ime) { this.ime = ime; }
        public void run() { if (ime.swapping && SystemClock.uptimeMillis() >= ime.swapUntil) ime.endSwap(); }
    }
    private boolean shift, symbols;
    int fr = 2, fc = 0;
    private long lastBackMs;
    private BroadcastReceiver rx;

    /** Loads the word list off the UI thread (named class: this d8 can't dex anonymous classes). */
    private static final class Loader implements Runnable {
        private final KlavyeIME ime;
        private boolean ui;
        Loader(KlavyeIME ime) { this.ime = ime; }
        public void run() {
            if (ui) { ime.refresh(); return; }
            ime.pred = new Predictor(ime);
            ui = true;
            if (ime.root != null) ime.root.post(this);
        }
    }

    // ---------- lifecycle ----------

    @Override
    public void onCreate() {
        super.onCreate();
        rx = new AdbRx(this);
        new Thread(new Loader(this)).start();
        IntentFilter f = new IntentFilter();
        f.addAction("ADB_INPUT_TEXT");
        f.addAction("ADB_INPUT_B64");
        f.addAction("ADB_INPUT_CODE");
        f.addAction("ADB_INPUT_MCODE");
        f.addAction("ADB_EDITOR_CODE");
        f.addAction("ADB_CLEAR_TEXT");
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(rx, f, PERM, null, Context.RECEIVER_EXPORTED);
        } else {
            registerReceiver(rx, f, PERM, null);
        }
    }

    @Override
    public void onDestroy() {
        if (rx != null) {
            try {
                unregisterReceiver(rx);
            } catch (IllegalArgumentException ignored) {
            }
            rx = null;
        }
        super.onDestroy();
    }

    @Override
    public View onCreateInputView() {
        frame = new FrameLayout(this);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable bg = new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, new int[]{0xF2161B24, 0xF20A0D12});
        bg.setCornerRadii(new float[]{dp(18), dp(18), dp(18), dp(18), 0, 0, 0, 0});
        root.setBackground(bg);
        int p = dp(6);
        root.setPadding(p, p, p, p);
        int sw = getResources().getDisplayMetrics().widthPixels;
        FrameLayout.LayoutParams rl = new FrameLayout.LayoutParams((int) (sw * 0.74f), ViewGroup.LayoutParams.WRAP_CONTENT);
        rl.gravity = Gravity.CENTER_HORIZONTAL;
        frame.addView(root, rl);
        hintLayer = new FrameLayout(this);
        frame.addView(hintLayer, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        for (int i = 0; i < 3; i++) {
            TextView t = new TextView(this);
            t.setGravity(Gravity.CENTER);
            t.setTextSize(22);
            t.setTypeface(null, Typeface.BOLD);
            t.setVisibility(View.GONE);
            hintViews[i] = t;
            hintLayer.addView(t, new FrameLayout.LayoutParams(dp(40), dp(KEY_H_DP)));
        }
        symbols = false;
        shift = false;
        fr = 2;
        fc = 0;
        buildKeys();
        return frame;
    }

    @Override
    public void onStartInputView(EditorInfo info, boolean restarting) {
        super.onStartInputView(info, restarting);
        if (root != null) {
            symbols = false;
            shift = false;
            fr = 2;
            fc = 0;
            hintsOn = false;
            hsel = -1;
            buildKeys();
            refresh();
        }
    }

    @Override
    public void onUpdateSelection(int os, int oe, int ns, int ne, int cs, int ce) {
        super.onUpdateSelection(os, oe, ns, ne, cs, ce);
        refreshWords();
    }

    @Override
    public boolean onEvaluateInputViewShown() {
        return true;
    }

    @Override
    public boolean onEvaluateFullscreenMode() {
        return false;
    }

    // ---------- layout ----------

    private static List<K> keys(String s) {
        List<K> l = new ArrayList<>();
        for (String t : s.split(" ")) {
            if (t.length() > 0) l.add(new K(t, t, T_CHAR, 1f));
        }
        return l;
    }

    private static List<K> keys(String s, float w) {
        List<K> l = new ArrayList<>();
        for (String t : s.split(" ")) {
            if (t.length() > 0) l.add(new K(t, t, T_CHAR, w));
        }
        return l;
    }

    /** Layout B (Kerim's pick): compact Turkish Q in the middle + a fixed action column on the right.
     *  Every row = 12 units of keys + 2.6 units of action key, so the column lines up vertically. */
    private void buildLayout() {
        final float A = 2.6f;
        rows.clear();
        List<K> sw = new ArrayList<>();
        for (int i = 0; i < 3; i++) sw.add(new K(i < sugg.size() ? sugg.get(i) : "", "", T_WORD, 4f));
        sw.add(new K("Gizle", "", T_HIDE, A));
        rows.add(sw);
        List<K> r1, r2, r3;
        if (symbols) {
            r1 = keys("1 2 3 4 5 6 7 8 9 0 - _", 1f);
            r2 = keys("@ # $ % & * ( ) / : ;", 12f / 11);
            r3 = new ArrayList<>();
            r3.add(new K("ABC", "", T_SYM, 1.5f));
            r3.addAll(keys("! ? \" ' + = ~ |", 10.5f / 8));
        } else {
            r1 = keys("q w e r t y u \u0131 o p \u011f \u00fc", 1f);
            r2 = keys("a s d f g h j k l \u015f i", 12f / 11);
            r3 = new ArrayList<>();
            r3.add(new K("\u21E7", "", T_SHIFT, 1.5f));
            r3.addAll(keys("z x c v b n m \u00f6 \u00e7", 10.5f / 9));
        }
        r1.add(new K("\u232B Sil", "", T_BACK, A));
        r2.add(new K("Temizle", "", T_CLEAR, A));
        r3.add(new K("Ara \u23CE", "", T_ENTER, A));
        rows.add(r1);
        rows.add(r2);
        rows.add(r3);
        List<K> r4 = new ArrayList<>();
        r4.add(new K(symbols ? "ABC" : "123", "", T_SYM, 1.5f));
        r4.add(new K(",", ",", T_CHAR, 1f));
        r4.add(new K("Bo\u015fluk", " ", T_SPACE, 5f));
        r4.add(new K(".", ".", T_CHAR, 1f));
        r4.add(new K("@", "@", T_CHAR, 1f));
        r4.add(new K(".com", ".com", T_CHAR, 2.5f));
        r4.add(new K("\uD83C\uDFA4 Ses", "", T_MIC, A));
        rows.add(r4);
    }

    private void buildKeys() {
        buildLayout();
        root.removeAllViews();
        views.clear();
        for (int r = 0; r < rows.size(); r++) {
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            List<TextView> rv = new ArrayList<>();
            List<K> kr = rows.get(r);
            for (int c = 0; c < kr.size(); c++) {
                TextView t = makeKey(kr.get(c), r, c);
                rv.add(t);
                row.addView(t);
            }
            views.add(rv);
            root.addView(row, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, dp(KEY_H_DP)));
        }
        clampFocus();
        updateFocus();
    }

    private TextView makeKey(final K k, final int r, final int c) {
        TextView t = new TextView(this);
        t.setText(shown(k));
        t.setGravity(Gravity.CENTER);
        t.setTextSize(k.type == T_CHAR && k.label.length() == 1 ? 24 : 19);
        t.setSingleLine(true);
        t.setTextColor(Color.WHITE);
        t.setFocusable(false);
        t.setClickable(true);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.MATCH_PARENT, k.w);
        int m = dp(MARGIN_DP);
        lp.setMargins(m, m, m, m);
        t.setLayoutParams(lp);
        k.r = r;
        k.c = c;
        t.setTag(k);
        t.setOnClickListener(this);
        return t;
    }

    @Override
    public void onClick(View v) {
        K k = (K) v.getTag();
        fr = k.r;
        fc = k.c;
        press(k);
    }

    @Override
    public void onAdb(Intent i) {
        handleAdb(i);
    }

    private void clampFocus() {
        if (fr >= rows.size()) fr = rows.size() - 1;
        if (fr < 0) fr = 0;
        int n = rows.get(fr).size();
        if (fc >= n) fc = n - 1;
        if (fc < 0) fc = 0;
    }

    private String shown(K k) {
        if (k.type == T_CHAR && shift && isLetterKey(k)) return up(k.label);
        return k.label;
    }

    private static boolean isLetterKey(K k) {
        return k.label.length() == 1 && Character.isLetter(k.label.charAt(0));
    }

    private static String up(String s) {
        return s.toUpperCase(TR);
    }

    private void updateFocus() {
        for (int r = 0; r < rows.size(); r++) {
            for (int c = 0; c < rows.get(r).size(); c++) {
                K k = rows.get(r).get(c);
                TextView t = views.get(r).get(c);
                boolean sel = (r == fr && c == fc);
                int base = (k.type == T_CHAR) ? 0xFF262C36 : 0xFF353D4A;
                if (k.type == T_MIC) base = 0xFF7A3B52;
                if (k.type == T_BACK || k.type == T_CLEAR || k.type == T_HIDE) base = 0xFF3A4250;
                if (k.type == T_SHIFT && shift) base = 0xFF5E8E5E;
                if (k.type == T_ENTER) base = 0xFF5E81AC;
                if (k.type == T_WORD) base = k.label.isEmpty() ? 0xFF12161C : 0xFF1F4E5F;
                GradientDrawable g = new GradientDrawable();
                g.setCornerRadius(dp(12));
                if (sel) {
                    g.setColor(0xFFFFD54F);
                    g.setStroke(dp(3), 0xFFFFFFFF);
                    t.setTextColor(0xFF000000);
                    t.setTypeface(null, Typeface.BOLD);
                } else {
                    g.setColor(base);
                    t.setTextColor(0xFFECEFF4);
                    t.setTypeface(null, Typeface.NORMAL);
                }
                t.setBackground(g);
                t.setText(shown(k));
            }
        }
    }

    // ---------- navigation ----------

    private double centre(int r, int c) {
        List<K> row = rows.get(r);
        double total = 0, before = 0;
        for (int i = 0; i < row.size(); i++) {
            total += row.get(i).w;
            if (i < c) before += row.get(i).w;
        }
        return (before + row.get(c).w / 2.0) / total;
    }

    private void moveH(int d) {
        int n = rows.get(fr).size();
        fc = Math.max(0, Math.min(n - 1, fc + d));
        updateFocus();
    }

    private void moveV(int d) {
        int nr = fr + d;
        if (nr < 0 || nr >= rows.size()) return;
        double cx = centre(fr, fc);
        int best = 0;
        double bd = Double.MAX_VALUE;
        for (int c = 0; c < rows.get(nr).size(); c++) {
            double dd = Math.abs(centre(nr, c) - cx);
            if (dd < bd) {
                bd = dd;
                best = c;
            }
        }
        fr = nr;
        fc = best;
        updateFocus();
    }

    // ---------- actions ----------

    void press(K k) {
        switch (k.type) {
            case T_CHAR: {
                String s = (shift && isLetterKey(k)) ? up(k.out) : k.out;
                commit(s);
                if (shift) {
                    shift = false;
                    updateFocus();
                }
                showHints(isLetterKey(k));
                break;
            }
            case T_SHIFT:
                shift = !shift;
                updateFocus();
                break;
            case T_BACK:
                sendDownUpKeyEvents(KeyEvent.KEYCODE_DEL);
                break;
            case T_SPACE:
                learnCurrent();
                commit(" ");
                break;
            case T_SYM:
                symbols = !symbols;
                shift = false;
                buildKeys();
                break;
            case T_CLEAR:
                clearText();
                break;
            case T_ENTER:
                learnCurrent();
                doEnter();
                break;
            case T_HIDE:
                requestHideSelf(0);
                break;
            case T_WORD:
                if (!k.label.isEmpty()) applyWord(k.label);
                break;
            case T_MIC:
                Log.i("KlavyeMic", "start");   // host tv-voice watches this tag and records the remote's mic
                break;
            default:
                break;
        }
    }

    private void commit(String s) {
        InputConnection ic = getCurrentInputConnection();
        if (ic != null) ic.commitText(s, 1);
    }

    private void doEnter() {
        EditorInfo ei = getCurrentInputEditorInfo();
        int action = (ei == null) ? EditorInfo.IME_ACTION_NONE
                : (ei.imeOptions & EditorInfo.IME_MASK_ACTION);
        if (action == EditorInfo.IME_ACTION_NONE || action == EditorInfo.IME_ACTION_UNSPECIFIED) {
            sendDownUpKeyEvents(KeyEvent.KEYCODE_ENTER);
        } else {
            InputConnection ic = getCurrentInputConnection();
            if (ic != null) ic.performEditorAction(action);
        }
    }

    private void clearText() {
        InputConnection ic = getCurrentInputConnection();
        if (ic == null) return;
        ExtractedText et = ic.getExtractedText(new ExtractedTextRequest(), 0);
        if (et != null && et.text != null) {
            ic.setSelection(0, et.text.length());
        } else {
            ic.performContextMenuAction(android.R.id.selectAll);
        }
        ic.commitText("", 1);
    }

    // ---------- keys ----------

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent ev) {
        if (root == null || !isInputViewShown()) return super.onKeyDown(keyCode, ev);
        boolean ok = keyCode == KeyEvent.KEYCODE_DPAD_CENTER || keyCode == KeyEvent.KEYCODE_ENTER
                || keyCode == KeyEvent.KEYCODE_NUMPAD_ENTER;
        if (swapping) {                         // UP just typed the centre letter
            if (keyCode == KeyEvent.KEYCODE_DPAD_LEFT || keyCode == KeyEvent.KEYCODE_DPAD_RIGHT) {
                int np = hsel + (keyCode == KeyEvent.KEYCODE_DPAD_LEFT ? -1 : 1);
                if (np >= 0 && np <= 2 && hintAt(np) != null) {
                    InputConnection ic = getCurrentInputConnection();
                    if (ic != null) { ic.deleteSurroundingText(1, 0); ic.commitText(hintAt(np), 1); }
                    hsel = np;
                    armSwap();
                    drawHints();
                }
                return true;
            }
            endSwap();
            if (ok || keyCode == KeyEvent.KEYCODE_DPAD_DOWN || keyCode == KeyEvent.KEYCODE_BACK) return true;
        }
        if (hintsOn && keyCode == KeyEvent.KEYCODE_DPAD_UP && hintAt(1) != null) {
            commit(shift ? up(hintAt(1)) : hintAt(1));
            if (shift) { shift = false; updateFocus(); }
            hsel = 1;
            swapping = true;
            armSwap();
            drawHints();
            return true;
        }
        if (keyCode == KeyEvent.KEYCODE_MENU && !sugg.isEmpty()) {   // jump to the word suggestions
            hideHints();
            fr = 0;
            fc = 0;
            updateFocus();
            return true;
        }
        switch (keyCode) {
            case KeyEvent.KEYCODE_DPAD_UP:
                hideHints();
                moveV(-1);
                return true;
            case KeyEvent.KEYCODE_DPAD_DOWN:
                hideHints();
                moveV(1);
                return true;
            case KeyEvent.KEYCODE_DPAD_LEFT:
                hideHints();
                moveH(-1);
                return true;
            case KeyEvent.KEYCODE_DPAD_RIGHT:
                hideHints();
                moveH(1);
                return true;
            case KeyEvent.KEYCODE_DPAD_CENTER:
            case KeyEvent.KEYCODE_ENTER:
            case KeyEvent.KEYCODE_NUMPAD_ENTER: {
                K k = rows.get(fr).get(fc);
                if (k.type == T_BACK) {
                    // Sil: allow hold-to-repeat, but at most one press per BACK_REPEAT_MS.
                    long now = SystemClock.uptimeMillis();
                    if (ev.getRepeatCount() > 0 && now - lastBackMs < BACK_REPEAT_MS) return true;
                    lastBackMs = now;
                } else if (ev.getRepeatCount() > 0) {
                    // Character / action keys: ignore auto-repeat so holding OK does not spam.
                    return true;
                }
                if (k.type != T_CHAR) hideHints();
                press(k);
                return true;
            }
            case KeyEvent.KEYCODE_BACK:
                hideHints();
                requestHideSelf(0);
                return true;
            default:
                return super.onKeyDown(keyCode, ev);
        }
    }

    // ---------- prediction ----------

    private String before() {
        InputConnection ic = getCurrentInputConnection();
        CharSequence cs = ic == null ? null : ic.getTextBeforeCursor(64, 0);
        return cs == null ? "" : cs.toString();
    }

    private static int wordStart(String b) {
        int i = b.length();
        while (i > 0 && Character.isLetter(b.charAt(i - 1))) i--;
        return i;
    }

    private String curWord() {
        String b = before();
        return b.substring(wordStart(b)).toLowerCase(TR);
    }

    private String prevWord() {
        String b = before();
        b = b.substring(0, wordStart(b)).trim();
        int i = wordStart(b);
        return b.substring(i).toLowerCase(TR);
    }

    void refresh() {
        refreshWords();
    }

    private void refreshWords() {
        if (root == null || symbols) return;
        Predictor pr = pred;
        List<String> n = pr == null ? new ArrayList<String>() : pr.words(curWord(), prevWord(), 3);
        if (n.equals(sugg)) return;
        sugg = n;
        List<K> sw = rows.get(0);
        for (int i = 0; i < 3; i++) {
            K old = sw.get(i);
            K k = new K(i < sugg.size() ? sugg.get(i) : "", "", T_WORD, 1f);
            k.r = old.r;
            k.c = old.c;
            sw.set(i, k);
            views.get(0).get(i).setTag(k);
        }
        updateFocus();
    }

    /** Replace the word being typed with w and add a space. */
    private void applyWord(String w) {
        InputConnection ic = getCurrentInputConnection();
        if (ic == null) return;
        String b = before();
        int n = b.length() - wordStart(b);
        String typed = b.substring(b.length() - n);
        if (n > 0 && Character.isUpperCase(typed.charAt(0))) w = w.substring(0, 1).toUpperCase(TR) + w.substring(1);
        String prev = prevWord();
        ic.beginBatchEdit();
        if (n > 0) ic.deleteSurroundingText(n, 0);
        ic.commitText(w + " ", 1);
        ic.endBatchEdit();
        Predictor pr = pred;
        if (pr != null) pr.learn(prev, w.toLowerCase(TR));
        hideHints();
    }

    private void learnCurrent() {
        Predictor pr = pred;
        if (pr != null) pr.learn(prevWord(), curWord());
    }

    /** hint position 0 = left, 1 = centre (most likely), 2 = right. */
    private String hintAt(int pos) {
        int i = pos == 1 ? 0 : (pos == 0 ? 1 : 2);
        return i < hints.size() ? hints.get(i) : null;
    }

    private void showHints(boolean letter) {
        if (true) { hideHints(); return; }   // layout B: no letter chips (Kerim found them confusing)
        Predictor pr = pred;
        hsel = -1;
        if (!letter || symbols || pr == null) { hideHints(); return; }
        String w = curWord();
        hints = w.isEmpty() ? new ArrayList<String>() : pr.letters(w, 3);
        hintsOn = !hints.isEmpty();
        drawHints();
    }

    private void hideHints() {
        hintsOn = false;
        hsel = -1;
        swapping = false;
        drawHints();
    }

    private void drawHints() {
        if (hintLayer == null) return;
        if (!hintsOn || fr < 1 || fr >= views.size() || fc >= views.get(fr).size()) {
            for (TextView t : hintViews) t.setVisibility(View.GONE);
            return;
        }
        TextView key = views.get(fr).get(fc);
        View row = (View) key.getParent();
        int w = key.getWidth(), h = key.getHeight();
        int x = row.getLeft() + key.getLeft();
        int y = row.getTop() + key.getTop() - h - dp(MARGIN_DP * 2);
        int x0 = Math.max(0, Math.min(frame.getWidth() - 3 * w, x - w));   // keep all 3 on screen
        for (int pos = 0; pos < 3; pos++) {
            TextView t = hintViews[pos];
            String s = hintAt(pos);
            if (s == null) { t.setVisibility(View.GONE); continue; }
            t.setText((shift ? up(s) : s) + (pos == 1 && !swapping ? " \u25B2" : ""));
            boolean sel = pos == hsel;
            GradientDrawable g = new GradientDrawable();
            g.setCornerRadius(dp(10));
            g.setColor(sel ? 0xFFFFD54F : (pos == 1 ? 0xFFFFA94D : 0xFFD9822B));
            g.setStroke(dp(2), 0xFFFFFFFF);
            t.setBackground(g);
            t.setTextColor(sel ? 0xFF000000 : 0xFF0B0E12);
            FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(w, h);
            lp.leftMargin = x0 + pos * w;
            lp.topMargin = Math.max(0, y);
            t.setLayoutParams(lp);
            t.setVisibility(View.VISIBLE);
        }
    }

    private void armSwap() {
        swapUntil = SystemClock.uptimeMillis() + SWAP_MS;
        root.removeCallbacks(swapEnd);
        root.postDelayed(swapEnd, SWAP_MS + 20);
    }

    /** Close the swap window: focus moves to the letter that stayed, its hints appear. */
    void endSwap() {
        if (!swapping) return;
        swapping = false;
        root.removeCallbacks(swapEnd);
        String s = hintAt(hsel);
        hsel = -1;
        if (s != null) {
            for (int r = 1; r < rows.size(); r++) {
                for (int c = 0; c < rows.get(r).size(); c++) {
                    K k = rows.get(r).get(c);
                    if (k.type == T_CHAR && k.out.equals(s)) { fr = r; fc = c; }
                }
            }
        }
        updateFocus();
        showHints(true);
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent ev) {
        if (root != null && isInputViewShown()) {
            switch (keyCode) {
                case KeyEvent.KEYCODE_DPAD_UP:
                case KeyEvent.KEYCODE_DPAD_DOWN:
                case KeyEvent.KEYCODE_DPAD_LEFT:
                case KeyEvent.KEYCODE_DPAD_RIGHT:
                case KeyEvent.KEYCODE_DPAD_CENTER:
                case KeyEvent.KEYCODE_ENTER:
                case KeyEvent.KEYCODE_NUMPAD_ENTER:
                case KeyEvent.KEYCODE_BACK:
                case KeyEvent.KEYCODE_MENU:
                    return true;
                default:
                    break;
            }
        }
        return super.onKeyUp(keyCode, ev);
    }

    // ---------- ADBKeyboard-compatible injection ----------

    void handleAdb(Intent i) {
        String a = i.getAction();
        if (a == null) return;
        switch (a) {
            case "ADB_INPUT_TEXT": {
                String m = i.getStringExtra("msg");
                if (m != null) commit(m);
                break;
            }
            case "ADB_INPUT_B64": {
                String m = i.getStringExtra("msg");
                if (m != null) {
                    try {
                        commit(new String(Base64.decode(m, Base64.DEFAULT), Charset.forName("UTF-8")));
                    } catch (IllegalArgumentException ignored) {
                    }
                }
                break;
            }
            case "ADB_INPUT_CODE": {
                int code = i.getIntExtra("code", -1);
                if (code > 0) sendDownUpKeyEvents(code);
                break;
            }
            case "ADB_INPUT_MCODE": {
                int[] cs = i.getIntArrayExtra("code");
                if (cs == null) cs = i.getIntArrayExtra("codes");
                if (cs != null) {
                    for (int code : cs) {
                        if (code > 0) sendDownUpKeyEvents(code);
                    }
                }
                break;
            }
            case "ADB_EDITOR_CODE": {
                int code = i.getIntExtra("code", -1);
                InputConnection ic = getCurrentInputConnection();
                if (ic != null && code > 0) ic.performEditorAction(code);
                break;
            }
            case "ADB_CLEAR_TEXT":
                clearText();
                break;
            default:
                break;
        }
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
