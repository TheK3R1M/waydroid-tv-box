package org.tvbox.klavye;

import android.content.Context;
import android.content.SharedPreferences;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Offline Turkish word + next-letter prediction.
 * Base: assets/words.txt (word\tfrequency, FrequencyWords tr, CC-BY-SA 4.0) sorted lexicographically.
 * Learning: words and word pairs the user typed are counted locally (SharedPreferences, never leave the box).
 */
final class Predictor {
    @SuppressWarnings({"rawtypes", "unchecked"})
    private static final Comparator BY_WORD = new ByWord(), BY_SCORE = new ByScore();

    private static final class ByWord implements Comparator {
        public int compare(Object x, Object y) { return ((String[]) x)[0].compareTo(((String[]) y)[0]); }
    }

    private static final class ByScore implements Comparator {
        public int compare(Object x, Object y) {
            return Long.compare((Long) ((Map.Entry) y).getValue(), (Long) ((Map.Entry) x).getValue());
        }
    }

    private String[] words = new String[0];
    private long[] freq = new long[0];
    private long top = 1;
    private final SharedPreferences sp;
    private final Map<String, Integer> learned = new HashMap<>();
    private final Map<String, Integer> pairs = new HashMap<>();

    Predictor(Context c) {
        sp = c.getSharedPreferences("learn", Context.MODE_PRIVATE);
        for (Map.Entry<String, ?> e : sp.getAll().entrySet()) {
            if (!(e.getValue() instanceof Integer)) continue;
            String k = e.getKey();
            if (k.startsWith("w:")) learned.put(k.substring(2), (Integer) e.getValue());
            else if (k.startsWith("p:")) pairs.put(k.substring(2), (Integer) e.getValue());
        }
        try {
            BufferedReader r = new BufferedReader(new InputStreamReader(c.getAssets().open("words.txt"), "UTF-8"));
            List<String[]> l = new ArrayList<>();
            String line;
            while ((line = r.readLine()) != null) {
                int t = line.indexOf('\t');
                if (t > 0) l.add(new String[]{line.substring(0, t), line.substring(t + 1)});
            }
            r.close();
            String[][] a = l.toArray(new String[0][]);
            //noinspection unchecked
            Arrays.sort(a, BY_WORD);
            words = new String[a.length];
            freq = new long[a.length];
            for (int i = 0; i < a.length; i++) {
                words[i] = a[i][0];
                freq[i] = Long.parseLong(a[i][1]);
                if (freq[i] > top) top = freq[i];
            }
        } catch (Exception ignored) {
        }
        // TV phrases + channel names: seed word pairs (next-word prediction) and boost their words.
        try {
            BufferedReader r = new BufferedReader(new InputStreamReader(c.getAssets().open("phrases.txt"), "UTF-8"));
            String line;
            while ((line = r.readLine()) != null) {
                String[] w = line.trim().split(" +");
                for (int i = 0; i < w.length; i++) {
                    if (w[i].length() > 1 && !learned.containsKey(w[i])) seedWords.put(w[i], 3);
                    if (i > 0) {
                        String k = w[i - 1] + " " + w[i];
                        if (!pairs.containsKey(k)) pairs.put(k, 3);
                    }
                }
            }
            r.close();
        } catch (Exception ignored) {
        }
    }

    private final Map<String, Integer> seedWords = new HashMap<>();

    private long boost(String w) {
        Integer n = learned.get(w);
        Integer s = seedWords.get(w);
        return (n == null ? 0 : (long) n * (top / 100)) + (s == null ? 0 : top / 8);
    }

    private int lower(String p) {
        int lo = 0, hi = words.length;
        while (lo < hi) {
            int m = (lo + hi) >>> 1;
            if (words[m].compareTo(p) < 0) lo = m + 1; else hi = m;
        }
        return lo;
    }

    /** Up to n completions for the word being typed; empty prefix = likely next words after prev. */
    List<String> words(String prefix, String prev, int n) {
        Map<String, Long> score = new HashMap<>();
        if (prefix.isEmpty()) {
            if (prev == null || prev.isEmpty()) return new ArrayList<>();
            String k = prev + " ";
            for (Map.Entry<String, Integer> e : pairs.entrySet()) {
                if (e.getKey().startsWith(k)) score.put(e.getKey().substring(k.length()), (long) e.getValue());
            }
        } else {
            for (int i = lower(prefix); i < words.length && words[i].startsWith(prefix); i++) {
                if (words[i].length() > prefix.length()) score.put(words[i], freq[i] + boost(words[i]));
            }
            for (String w : learned.keySet()) {
                if (w.startsWith(prefix) && w.length() > prefix.length() && !score.containsKey(w)) score.put(w, boost(w));
            }
            for (String w : seedWords.keySet()) {
                if (w.startsWith(prefix) && w.length() > prefix.length() && !score.containsKey(w)) score.put(w, boost(w));
            }
            if (prev != null && !prev.isEmpty()) {
                String k = prev + " ";
                for (Map.Entry<String, Integer> e : pairs.entrySet()) {
                    String w = e.getKey().startsWith(k) ? e.getKey().substring(k.length()) : null;
                    if (w != null && w.startsWith(prefix) && score.containsKey(w)) score.put(w, score.get(w) + e.getValue() * (top / 20));
                }
            }
        }
        return topN(score, n);
    }

    /** The n most likely letters after prefix (empty when nothing continues it). */
    List<String> letters(String prefix, int n) {
        Map<String, Long> score = new HashMap<>();
        int L = prefix.length();
        for (int i = lower(prefix); i < words.length && words[i].startsWith(prefix); i++) {
            if (words[i].length() > L) {
                String ch = words[i].substring(L, L + 1);
                Long s = score.get(ch);
                score.put(ch, (s == null ? 0 : s) + freq[i] + boost(words[i]));
            }
        }
        return topN(score, n);
    }

    @SuppressWarnings("unchecked")
    private static List<String> topN(Map<String, Long> m, int n) {
        List<Map.Entry<String, Long>> l = new ArrayList<>(m.entrySet());
        Collections.sort(l, BY_SCORE);
        List<String> out = new ArrayList<>();
        for (int i = 0; i < l.size() && out.size() < n; i++) out.add(l.get(i).getKey());
        return out;
    }

    /** Remember a finished word (and the pair with the word before it). */
    void learn(String prev, String w) {
        if (w == null || w.length() < 2 || w.length() > 30) return;
        SharedPreferences.Editor e = sp.edit();
        int c = (learned.containsKey(w) ? learned.get(w) : 0) + 1;
        learned.put(w, c);
        e.putInt("w:" + w, c);
        if (prev != null && prev.length() > 0) {
            String k = prev + " " + w;
            int p = (pairs.containsKey(k) ? pairs.get(k) : 0) + 1;
            pairs.put(k, p);
            e.putInt("p:" + k, p);
        }
        e.apply();
    }
}
