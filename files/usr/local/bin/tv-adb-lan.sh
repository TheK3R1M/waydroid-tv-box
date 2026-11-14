#!/bin/sh
# Expose Android adb (5555) ONLY to admin PC (__ADMIN_PC_IP__). ro.adb.secure=1: new PCs must be accepted on TV.
PC=__ADMIN_PC_IP__
for i in $(seq 1 60); do [ "$(waydroid shell -- getprop sys.boot_completed 2>/dev/null)" = "1" ] && break; sleep 2; done
IP=$(waydroid status | awk "/IP address/{print \$3}")
waydroid shell -- setprop service.adb.tcp.port 5555; waydroid shell -- stop adbd; waydroid shell -- start adbd
iptables -t nat -S PREROUTING | grep -- "--dport 5555" | sed "s/^-A/-D/" | while read r; do iptables -t nat $r; done
iptables -S FORWARD | grep -- "--dport 5555" | sed "s/^-A/-D/" | while read r; do iptables $r; done
iptables -t nat -A PREROUTING -s $PC -p tcp --dport 5555 -j DNAT --to-destination $IP:5555
iptables -I FORWARD -s $PC -d $IP -p tcp --dport 5555 -j ACCEPT
# Close boot-time notification side panel, land on launcher
sleep 8; waydroid shell -- input keyevent 4; sleep 1; waydroid shell -- input keyevent 3
