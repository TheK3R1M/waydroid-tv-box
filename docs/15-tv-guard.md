# 15 · tv-guard: firewall anti-bot chain and app quarantine ❔

[← Index](../README.md) · [Checklist](../CHECKLIST.md) · [Agent entry point](../SKILL.md)

Status: ❔ deployed on the reference box (firewall chain and the one-minute timer are active). The reference
notes do not record a result for the planned flood test, so treat the behaviour as unverified until you run §15.5.

## 15.1 What it protects against

Android runs third-party APKs as a privileged container on the host (see [§10.1](10-security.md)). Even with the
LAN isolation, an app that turns into a bot could flood the internet, scan ports, or open many connections. tv-guard
limits the damage and quarantines the suspect app. It never touches the TV stack.

## 15.2 Two parts

**A. Firewall (`tv-guard-fw.sh`, idempotent, called from `tv-net-isolate.sh`)**

- Creates chain `TV-GUARD`, inserted at position 2 of `TV-ISOLATE` (after the ESTABLISHED shortcut, before the LAN drops).
- Drops outbound NEW connections to ports typically used by botnets and spam: telnet, SMTP submission and
  relay, SMB/NetBIOS, RDP, SSH, IRC, MSSQL, and similar. Logs the first few per minute with prefix `TVGUARD-PORT`.
- Caps NEW connections per source at 40/s (burst 300); the excess is dropped and logged as `TVGUARD-FLOOD`.
- Drop counters are read by the checker.

**B. Checker (`tv-guard-check.py`, run by `tv-guard.timer` every minute)**

It compares against a calm baseline and reports anomalies:

| Check | Threshold |
|---|---|
| Upload from Android (host rx on `waydroid0`) | > 15 Mbit/s over the minute |
| Firewall drops grew | > 20 in one minute |
| Android conntrack entries / distinct destinations | > 1500 / > 250 |
| New listening socket on the host (vs. baseline at first run) | any (UDP high ports ignored) |
| New executable (ELF) in Android user data outside app dirs | any sha256 not in `ELF_ALLOW` (re-hashed after 4 s to avoid mid-write false alarms) |

On an anomaly it writes `/var/log/tv-guard.log` and a line to the remote's audit log (actor "Güvenlik").
Then **quarantine**: `am force-stop` + `pm disable-user --user 0` for every package in `WATCH`.
`WATCH` is empty by default, so the default action is log-only. Undo a quarantine with `pm enable <pkg>`.

State files: `/var/lib/tv-guard/state.json`, `/var/lib/tv-guard/baseline.json` (created on the first run).

## 15.3 Files (in the kit)

| File | Installed to |
|---|---|
| `files/usr/local/bin/tv-guard-fw.sh` | `/usr/local/bin/tv-guard-fw.sh` (run by `tv-net-isolate.sh`) |
| `files/usr/local/bin/tv-guard-check.py` | `/usr/local/bin/tv-guard-check.py` |
| `files/etc/systemd/system/tv-guard.service` + `tv-guard.timer` | `/etc/systemd/system/` |

Requirements: `python3`, `iptables`, `ss` (iproute2), `conntrack` (the `conntrack` package; it is **not** in the
package list of [§3.1](03-host-base.md), so install it), and `adb` (already in §3.1).

## 15.4 Install

```bash
install -m 755 tv-guard-fw.sh tv-guard-check.py /usr/local/bin/
install -m 644 tv-guard.service tv-guard.timer /etc/systemd/system/
systemctl daemon-reload
/usr/local/bin/tv-net-isolate.sh                 # adds the TV-GUARD chain (idempotent)
systemctl enable --now tv-guard.timer
```

Set the app list (owner decision, see §15.6) in `tv-guard-check.py` (`WATCH`) before relying on quarantine.

## 15.5 Verify ❔

1. `iptables -S TV-GUARD` lists the port drops and the hashlimit rules; `iptables -S TV-ISOLATE | head -3` shows
   `-j TV-GUARD` at position 2.
2. `systemctl list-timers tv-guard.timer` shows the next run; `/var/lib/tv-guard/baseline.json` exists after the first run.
3. Port test from **inside** Android (read-only, harmless): `waydroid shell -- sh -c 'curl -m4 -sS telnet://1.1.1.1:23 >/dev/null 2>&1 && echo OPEN || echo CLOSED'`
   should print CLOSED and increase the `TVGUARD-PORT` counter. Do not run flood tests while the family watches.
4. Flood test (only with nobody watching): 25 quick connection attempts from Android; the `TVGUARD-FLOOD` log line
   and the drop counter should rise. Record the result in your own log; the reference box did not record one.

## 15.6 Owner decisions

- Which packages go in `WATCH`. Only apps the owner approved (see [§6.2](06-apps-and-signin.md)).
- Whether to whitelist ELF hashes (`ELF_ALLOW`) for packed libraries of an approved app. Each hash fingerprints a
  specific build; add them only after reading the checker's log.
- The checker is a heuristic, not an antivirus. It is a second line behind the LAN isolation, not a replacement.

Back to: [§10 Security](10-security.md) · [§14 Physical remote](14-physical-remote.md)
