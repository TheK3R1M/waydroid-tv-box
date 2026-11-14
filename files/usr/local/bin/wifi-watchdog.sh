#!/bin/sh
# If gateway unreachable 3x in a row -> bounce wlp3s0
GW=__GATEWAY_IP__; fail=0
while true; do
  if ping -c1 -W2 $GW >/dev/null 2>&1; then fail=0; else fail=$((fail+1)); fi
  if [ $fail -ge 3 ]; then logger -t wifi-watchdog "gateway unreachable, restarting wlp3s0"; ifdown --force wlp3s0; sleep 2; ifup wlp3s0; fail=0; sleep 30; fi
  sleep 10
done
