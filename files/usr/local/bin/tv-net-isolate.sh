#!/bin/sh
# Android (waydroid0) -> internet only. No LAN, no host services (except DNS/DHCP). Inbound adb from PC still works (ESTABLISHED).
set -e
for t in iptables; do
  $t -N TV-ISOLATE 2>/dev/null || $t -F TV-ISOLATE
  $t -A TV-ISOLATE -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
  for n in 192.168.0.0/16 10.0.0.0/8 172.16.0.0/12 169.254.0.0/16 100.64.0.0/10 224.0.0.0/4; do $t -A TV-ISOLATE -d $n -j DROP; done
  while $t -D FORWARD -i waydroid0 -j TV-ISOLATE 2>/dev/null; do :; done; $t -I FORWARD 1 -i waydroid0 -j TV-ISOLATE
  $t -N TV-HOST 2>/dev/null || $t -F TV-HOST
  $t -A TV-HOST -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  $t -A TV-HOST -p udp -m multiport --dports 53,67 -j ACCEPT
  $t -A TV-HOST -p tcp --dport 53 -j ACCEPT
  $t -A TV-HOST -j DROP
  while $t -D INPUT -i waydroid0 -j TV-HOST 2>/dev/null; do :; done; $t -I INPUT 1 -i waydroid0 -j TV-HOST
done
ip6tables -C INPUT -i waydroid0 -j DROP 2>/dev/null || ip6tables -I INPUT 1 -i waydroid0 -j DROP
ip6tables -C FORWARD -i waydroid0 -j DROP 2>/dev/null || ip6tables -I FORWARD 1 -i waydroid0 -j DROP
/usr/local/bin/tv-guard-fw.sh
