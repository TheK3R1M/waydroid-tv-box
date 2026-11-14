# 10 · Security hardening and the security gate

[← Index](../README.md) · [Checklist](../CHECKLIST.md) · [Agent entry point](../SKILL.md)


### 10.1 Threat model (say this to the owner in plain terms)

Waydroid runs as a **privileged LXC on the Proxmox host** (no idmap → container root = host root). AppArmor profiles `lxc-waydroid` / `android_app` run in complain mode, and the build is `userdebug`. An APK that roots Android and escapes the container can own the Proxmox host and everything on it. The hardening below limits the blast radius; it does not make the container a sandbox.

### 10.2 LAN isolation (internet kept)

`files/usr/local/bin/tv-net-isolate.sh` (run by `tv-android` ExecStartPost via `isolate.conf`, by `waydroid-container` ExecStartPost after `sleep 5`, and every 2 min by `tv-net-isolate.timer`):

- chain `TV-ISOLATE` on FORWARD for `-i waydroid0`: `ESTABLISHED,RELATED → RETURN`, then DROP to `192.168.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12`, `169.254.0.0/16`, `100.64.0.0/10`, `224.0.0.0/4`;
- chain `TV-HOST` on INPUT for `-i waydroid0`: allow established, DNS (53), DHCP (67); DROP the rest;
- IPv6 on `waydroid0` is dropped.

So Android keeps the internet (streaming works) and loses the LAN, the host services and the modem. Inbound adb from the PC still works (replies are ESTABLISHED).

Waydroid re-inserts its own `-i waydroid0 -j ACCEPT` at the top at every container start, so a plain `iptables -C … || -I` leaves the jump below it and nothing is blocked. The script deletes every copy of its jumps and inserts at position 1. Keep it that way.

Verify **from inside Android**, with a verdict printed inside the probe (`waydroid shell -- cmd` does not return the inner exit code):

```bash
waydroid shell -- sh -c 'ping -c1 -W2 8.8.8.8 >/dev/null 2>&1 && echo OPEN || echo CLOSED'         # internet: OPEN
waydroid shell -- sh -c 'nc -z -w2 __GATEWAY_IP__ 80 >/dev/null 2>&1 && echo OPEN || echo CLOSED'  # modem: CLOSED
waydroid shell -- sh -c 'nc -z -w2 __TV_HOST_IP__ 8006 >/dev/null 2>&1 && echo OPEN || echo CLOSED' # host GUI: CLOSED
```

Expected: internet / YouTube / DNS OPEN; host 8006 and 22, other LAN hosts, modem, admin PC CLOSED. (The original run produced this table; `nc` may be missing on the Android image, then use `toybox`/`curl` equivalents.) ❔ Re-run this table after any change.

### 10.3 Remove the debugfs bind

Android gets `/sys/kernel/debug` by default. It is not needed:
- `config_nodes` line: removed in 5.2 (generated only by `waydroid init`/`upgrade`, not at each start);
- `lxc.py` (`/usr/lib/waydroid/tools/helpers/lxc.py`): `files/usr/local/bin/waydroid-no-debugfs.sh` comments out `make_entry("/sys/kernel/debug", …)`. It runs before each container start (`no-debugfs.conf` drop-in), so `waydroid init/upgrade` does not bring it back. Keep a backup `lxc.py.orig` before the first run.

Verify: `waydroid shell -- ls /sys/kernel/debug` prints nothing.

### 10.4 AppArmor

Do **not** switch AppArmor to enforce. The `ALLOWED` audit lines are GMS/gRPC unix-socket operations that enforce mode breaks. Leave complain mode and rely on 10.2 and 10.3.

### 10.5 Real isolation (only if the hardware allows)

The container is the final answer on this box. On a machine with IOMMU enabled in BIOS (check `ls /sys/kernel/iommu_groups | wc -l` > 0 and `AMD-Vi` in `journalctl -k`): the better design is a VM for Android with the iGPU and HDMI audio passed through, LAN-firewalled, and other workloads in separate guests. Vega/Raven iGPU passthrough can need a VBIOS ROM and can hit the reset bug (VM restart → host reboot). Keep the container setup as the fallback. Do not put the stock backend on the TV host.

### 10.6 Security gate (applies to any new network exposure)

1. **Nothing in the house gets a public name, port or certificate without the owner's explicit OK for that exposure** — even "just a DNS record to a LAN IP". The TV remote is LAN-only on purpose.
2. **Public DNS is public information.** A record to a private IP leaks the layout. A public Let's Encrypt cert is written to Certificate Transparency logs forever (the name cannot be un-published). Prefer local DNS on the router. The name `tv.example.lan` in this kit is a placeholder for local DNS only.
3. **Audit from the attacker's side.** WAN IPv4 may be CGNAT (no inbound), but IPv6 can be native and global: every host gets a public IPv6 address and only the router's IPv6 firewall protects it. Services must bind IPv4/LAN only unless the owner says otherwise. The tv-remote binds `0.0.0.0` on IPv4 only (the code uses `AF_INET` sockets).
4. **LAN web UIs resist browser attacks** (Host allowlist, Origin on POST, X-Frame-Options, nosniff, no-referrer) — [§9.2](09-web-remote.md).
5. **Credentials stay on the admin PC.** The Cloudflare token and the router login never go on the TV host (it runs untrusted APKs). The host only receives results (a cert, a device list).
6. **Log every exposure-related change** (DNS, cert, router entry, open port) with how to undo it.

### 10.7 Optional HTTPS (only for the phone gyro)

HTTPS is needed only for the gyro (Chrome requires a secure context). It is optional.

- Local DNS on the router: `tv.example.lan → __TV_HOST_IP__` (static host entry, not public DNS).
- Certificate: Let's Encrypt via **lego DNS-01** from the admin PC (the Cloudflare token scoped to the zone stays on the PC). `pc/renew-cert.sh` runs lego, pushes `fullchain.pem`/`privkey.pem` to `/etc/tv/tls/` (mode 600), and reports one status line. Run it from a scheduler on the PC (weekly is enough). tv-remote reloads the cert when the file changes; no restart.
- ❔ Trade-off: the name stays in CT logs forever. The owner must approve that before you request a certificate.
- Phones with Android "Private DNS" enabled bypass the router's DNS; use the HTTP :8090 address there (no gyro).

## 10.8 See also

- tv-guard (firewall anti-bot chain, one-minute checker, quarantine of owner-chosen apps): [§15](15-tv-guard.md) ❔
- Agent rules for exposure and approvals: [§13](13-agent-rules.md)
