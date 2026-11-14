#!/bin/sh
# Remove /sys/kernel/debug bind from Waydroid container (re-applied each start, survives waydroid package updates)
F=/usr/lib/waydroid/tools/helpers/lxc.py
grep -q "^ *make_entry(\"/sys/kernel/debug\"" $F && sed -i "s|^\( *\)make_entry(\"/sys/kernel/debug\"|\1pass  # hermes no-debugfs: make_entry(\"/sys/kernel/debug\"|" $F
exit 0
