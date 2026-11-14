#!/bin/bash
mkdir -p /dev/binderfs
mount -t binder binder /dev/binderfs 2>/dev/null
python3 -c '
import fcntl, os, struct
BINDER_CTL_ADD = 0xC1086201
try:
    fd = os.open("/dev/binderfs/binder-control", os.O_RDWR)
    for name in [b"binder", b"hwbinder", b"vndbinder"]:
        req = bytearray(struct.pack("256sII", name, 0, 0))
        try:
            fcntl.ioctl(fd, BINDER_CTL_ADD, req)
        except Exception:
            pass
    os.close(fd)
except Exception:
    pass
'
ln -sf /dev/binderfs/binder /dev/binder
ln -sf /dev/binderfs/hwbinder /dev/hwbinder
ln -sf /dev/binderfs/vndbinder /dev/vndbinder
chmod 666 /dev/binder /dev/hwbinder /dev/vndbinder 2>/dev/null
chmod 666 /dev/binderfs/* 2>/dev/null

if ! ip link show waydroid0 >/dev/null 2>&1; then
    ip link add name waydroid0 type bridge
    ip addr add 192.168.240.1/24 dev waydroid0
    ip link set dev waydroid0 up
fi
