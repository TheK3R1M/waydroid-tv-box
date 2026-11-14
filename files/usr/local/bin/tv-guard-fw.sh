#!/bin/sh
# tv-guard firewall part (called from tv-net-isolate.sh, idempotent).
# Android may stream and browse, but must never act like a bot:
#  - typical botnet/abuse ports out of Android are dropped (telnet scan, SMTP spam, SMB/RDP/SSH spread, IRC C2)
#  - NEW connections are capped per second (normal TV use opens a few per second; a DDoS/scan opens hundreds)
# Every drop is counted (iptables counters) and logged with prefix TVGUARD so tv-guard-check.sh can alert.
set -e
iptables -N TV-GUARD 2>/dev/null || iptables -F TV-GUARD
iptables -A TV-GUARD -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
iptables -A TV-GUARD -p tcp -m multiport --dports 22,23,25,135,139,445,465,587,1433,2323,3389,5555,6667,7547 \
  -m limit --limit 6/min -j LOG --log-prefix "TVGUARD-PORT " --log-level 4
iptables -A TV-GUARD -p tcp -m multiport --dports 22,23,25,135,139,445,465,587,1433,2323,3389,5555,6667,7547 -j DROP
iptables -A TV-GUARD -m conntrack --ctstate NEW -m hashlimit --hashlimit-name tvguard --hashlimit-mode srcip \
  --hashlimit-above 40/second --hashlimit-burst 300 -m limit --limit 6/min -j LOG --log-prefix "TVGUARD-FLOOD " --log-level 4
iptables -A TV-GUARD -m conntrack --ctstate NEW -m hashlimit --hashlimit-name tvguard2 --hashlimit-mode srcip \
  --hashlimit-above 40/second --hashlimit-burst 300 -j DROP
iptables -A TV-GUARD -j RETURN
while iptables -D TV-ISOLATE -j TV-GUARD 2>/dev/null; do :; done
iptables -I TV-ISOLATE 2 -j TV-GUARD   # after the ESTABLISHED shortcut, before the LAN drops
