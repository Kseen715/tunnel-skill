#!/usr/bin/env python3
"""Move IP packets between an existing tun device and stdin/stdout.

Each packet on the stream is prefixed with its length (2 bytes, big endian).
Run one copy on each end of an ssh connection.

Usage: tunbridge.py tunN
The device must exist (ip tuntap add) and be owned by this user, or run as root.
Exits when the stream or the device closes; the device then loses carrier.
"""
import fcntl
import os
import struct
import sys
import threading

TUNSETIFF, IFF_TUN, IFF_NO_PI = 0x400454CA, 0x0001, 0x1000


def read_exact(fd, n):
    buf = b""
    while len(buf) < n:
        chunk = os.read(fd, n - len(buf))
        if not chunk:
            os._exit(0)
        buf += chunk
    return buf


def write_all(fd, data):
    while data:
        data = data[os.write(fd, data):]


def tun_to_stream(tun):
    try:
        while True:
            pkt = os.read(tun, 65535)
            write_all(1, struct.pack("!H", len(pkt)) + pkt)
    finally:
        os._exit(1)


tun = os.open("/dev/net/tun", os.O_RDWR)
fcntl.ioctl(tun, TUNSETIFF, struct.pack("16sH", sys.argv[-1].encode(), IFF_TUN | IFF_NO_PI))
threading.Thread(target=tun_to_stream, args=(tun,), daemon=True).start()
while True:
    (size,) = struct.unpack("!H", read_exact(0, 2))
    pkt = read_exact(0, size)
    try:
        os.write(tun, pkt)
    except OSError:
        pass  # malformed packet or device briefly down: drop it
