---
name: ssh-internet-tunnel
description: Give a remote Linux host that has no internet access temporary internet through the user's own machine, using an SSH layer-3 tunnel (ssh -w) and NAT on the user's machine, preferably out of the user's VPN. Use only when you work on a remote host over SSH, that host cannot reach the internet, the user's machine can, and the user explicitly asks to give the remote host internet access (for example to install packages, pull images or clone repositories). Do not use for ordinary SSH work or start it on your own after a failed download; offer it and wait for the user's request.
---

# SSH internet tunnel

Routes a remote host's IPv4 internet traffic through the user's machine:

```
remote host --- ssh -w (tunN) ---> user's machine --- NAT ---> egress interface (VPN or default) ---> internet
10.254.N.2                         10.254.N.1
```

Requirements: both hosts are Linux with iproute2; the user's machine has `iptables`
(the nft backend is fine); root (sudo) on both hosts; the remote OpenSSH server allows
tunnels (step 3 can enable it); `ssh H` works without a password prompt.

## Rules

1. **Show, then ask.** Before every step, show the user the exact block you will run with
   all values filled in, say which host it runs on and what it changes, and wait for a yes.
   Show the output afterwards. Read-only steps are shown and asked too.
2. **Never handle passwords.** If step 1 reports `sudo: needs password` for a host, do not
   run its root blocks yourself. Give the user the part from `sudo sh -s <<'EOF'` to `EOF`
   (with `-n` removed) and ask them to paste it into a terminal on that host (for the
   remote host: inside `ssh H`), then paste the output back to you.
3. **Edit only the values at the top of a block.** Everything else stays as written.
4. **Stop on failure.** Show the error, check the troubleshooting table, and offer step 9.
5. **Tear down when done.** When the user's task is finished, ask and then run step 9.

Before step 1, tell the user in a few lines what will happen:

- The remote host's internet traffic leaves through the user's machine and interface E
  (their VPN if there is one), with the user's public IP.
- While active, the remote host uses public DNS (`8.8.8.8` by default); internal names may
  not resolve. Its private ranges (10/8, 172.16/12, 192.168/16) and the SSH connection to
  the user keep their current routes.
- The user's machine drops tunnel traffic to itself and to private ranges: the remote host
  gets the internet only, not the user's LAN or VPN-internal networks.
- IPv4 only. A watchdog restores the remote network if the tunnel drops.

## Values

| Value | Meaning | Source |
|---|---|---|
| `H` | ssh destination exactly as the user uses it (alias or `user@host`) | conversation |
| `N` | tunnel number: device `tunN` on both hosts, `10.254.N.1` local, `10.254.N.2` remote | step 1: smallest N from 9 up with no `tunN` and no `10.254.N.` address on either host |
| `U` | local user name | step 1 `user:` |
| `LOGIN` | remote login user | step 1 `login:` |
| `CLIENT` | the user's address as the remote host sees it | step 1 `client:` |
| `E` | egress interface on the user's machine | step 2 |
| `FORCE` | `yes` only when E is a VPN that is not the current internet route | step 2 |
| `DNS` | DNS server for the remote host, default `8.8.8.8` | ask only if it fails |

## Step 1. Discover (read-only, both hosts)

User's machine:

```sh
echo "user: $(id -un)"
ip -4 route get 1.1.1.1
echo "vpn-like:"; ip -o -d link show | grep -E 'POINTOPOINT|wireguard|tun type' | cut -d: -f2
curl -sS -m 5 -o /dev/null -w 'internet: http %{http_code}\n' https://example.com
echo "ip_forward: $(cat /proc/sys/net/ipv4/ip_forward)"
echo "links: $(ls /sys/class/net | tr '\n' ' ')"
echo "10.254 in use: $(ip -4 addr | grep -o '10\.254\.[0-9]*\.' | sort -u | tr '\n' ' ')"
sudo -n true 2>/dev/null && echo "sudo: ok" || echo "sudo: needs password"
```

Remote host:

```sh
ssh H sh -s <<'EOF'
echo "login: $USER"
echo "client: ${SSH_CLIENT%% *}"
echo "default route: $(ip -4 route show default)"
echo "links: $(ls /sys/class/net | tr '\n' ' ')"
echo "10.254 in use: $(ip -4 addr | grep -o '10\.254\.[0-9]*\.' | sort -u | tr '\n' ' ')"
(curl -sS -m 5 -o /dev/null https://example.com || wget -q -T 5 -O /dev/null https://example.com) 2>/dev/null \
  && echo "internet: yes" || echo "internet: no"
sudo -n true 2>/dev/null && echo "sudo: ok" || echo "sudo: needs password"
sudo -n sshd -T 2>/dev/null | grep -i '^permittunnel' || echo "permittunnel: unknown (needs root)"
EOF
```

Stop if the remote host already has internet or the user's machine has none. Show the
user a short summary of the values found and the N you picked.

## Step 2. Choose the egress interface E

`ip -4 route get 1.1.1.1` shows `dev X`: where internet traffic really goes now. It includes
VPN policy routing, so trust it over `ip route show default`. The `vpn-like` list holds
point-to-point, tun and WireGuard links (OpenVPN, WireGuard, sing-box or clash TUN, ppp,
tailscale). Their names vary, so judge by this list, not by name.

- X is in the vpn-like list: propose `E=X`, `FORCE=no`.
- X is not, but the list is not empty: ask the user to choose between `E=X`, `FORCE=no`
  (current route) and `E=<vpn>`, `FORCE=yes` (policy route into the VPN; works only if that
  VPN carries internet traffic, which split-tunnel corporate VPNs often do not).
- The list is empty: propose `E=X`, `FORCE=no`.

Always confirm E with the user; they may name another interface. Tunnel traffic may only
leave through E: if E goes down, the remote host loses internet instead of leaking out of
another interface.

## Step 3. Allow tunnels in the remote sshd (only if PermitTunnel is `no` or `ethernet`)

Tell the user this changes the sshd configuration until step 9 reverts it, and reloads
sshd (open sessions stay).

```sh
ssh H 'sudo -n sh -s' <<'EOF'
set -eu
if grep -Eqs '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/' /etc/ssh/sshd_config; then
  echo 'PermitTunnel point-to-point' > /etc/ssh/sshd_config.d/00-ssh-internet-tunnel.conf
else
  printf '\n# ssh-internet-tunnel\nPermitTunnel point-to-point\n' >> /etc/ssh/sshd_config
fi
sshd -t
if [ -d /run/systemd/system ]; then
  for u in ssh sshd; do systemctl try-reload-or-restart "$u" 2>/dev/null || true; done
else
  kill -HUP "$(cat /run/sshd.pid)"
fi
sshd -T | grep -i '^permittunnel'
EOF
```

It must print `permittunnel point-to-point` or `yes`. If not, an earlier line wins (sshd uses
the first value it reads); show `sudo grep -rni permittunnel /etc/ssh/` to the user and ask.
If the reload fails (no systemd and no `/run/sshd.pid`), ask the user how sshd is reloaded on that host.

## Step 4. Prepare the user's machine (root)

Creates `tunN` owned by U, enables forwarding, adds firewall and NAT rules, and writes
the undo script `/run/ssh-inet-tunnel-N/restore.sh`.

```sh
sudo -n sh -s <<'EOF'
set -eu
N=9           # tunnel number
E=wg0         # egress interface
FORCE=no      # yes: policy-route tunnel traffic into E (VPN that is not the current route)
U=alice       # local user that runs ssh in step 6
T=tun$N L=10.254.$N.1 R=10.254.$N.2 D=/run/ssh-inet-tunnel-$N TABLE=$((25400 + N))
PRIVATE=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16,100.64.0.0/10
mkdir -m 700 "$D"
cat > "$D/restore.sh" <<UNDO
ip link del $T
iptables -D INPUT -i $T -j DROP
iptables -D FORWARD -i $T -d $PRIVATE -j REJECT
iptables -D FORWARD -i $T -o $E -j ACCEPT
iptables -D FORWARD -i $E -o $T -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
iptables -t nat -D POSTROUTING -s $R -o $E -j MASQUERADE
ip rule del from $R lookup $TABLE 2>/dev/null
ip route flush table $TABLE 2>/dev/null
sysctl -qw net.ipv4.ip_forward=$(cat /proc/sys/net/ipv4/ip_forward)
rm -rf $D
UNDO
ip tuntap add dev $T mode tun user $U
ip addr add $L peer $R dev $T
ip link set $T up
sysctl -qw net.ipv4.ip_forward=1
iptables -I INPUT -i $T -j DROP
iptables -I FORWARD -i $E -o $T -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
iptables -I FORWARD -i $T -o $E -j ACCEPT
iptables -I FORWARD -i $T -d $PRIVATE -j REJECT
iptables -t nat -A POSTROUTING -s $R -o $E -j MASQUERADE
if [ "$FORCE" = yes ]; then
  ip route add default dev $E table $TABLE
  ip rule add from $R lookup $TABLE priority 100
fi
echo "local side ready: $T $L <-> $R, egress $E"
EOF
```

## Step 5. Prepare the remote host (root)

Creates `tunN` owned by LOGIN, so the tunnel needs no root SSH login.
`ignore_routes_with_linkdown` makes the kernel stop using the tunnel routes the moment the
tunnel drops, before the watchdog cleans up.

```sh
ssh H 'sudo -n sh -s' <<'EOF'
set -eu
N=9           # tunnel number
LOGIN=bob     # remote login user
T=tun$N
ip tuntap add dev $T mode tun user $LOGIN
ip addr add 10.254.$N.2 peer 10.254.$N.1 dev $T
sysctl -qw net.ipv4.conf.$T.ignore_routes_with_linkdown=1
ip link set $T up
echo "remote side ready: $T"
EOF
```

## Step 6. Start the tunnel (user's machine, no root)

```sh
ssh -f -N -S none -w 9:9 -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 H
cat /sys/class/net/tun9/carrier
ssh H cat /sys/class/net/tun9/carrier
ip -4 route get 1.1.1.1 from 10.254.9.2 iif tun9
```

Replace 9 with N. Both carriers must print `1`, and the last line must show `dev E`.
`-f` puts ssh in the background once the tunnel is up; it keeps running after you return.

## Step 7. Route the remote host through the tunnel (root)

Pins the route back to CLIENT, keeps private ranges on the current gateway, sends the rest
into the tunnel, switches DNS, writes `/run/ssh-inet-tunnel-N/restore.sh` and starts the
watchdog that runs it when the tunnel drops.

```sh
ssh H 'sudo -n sh -s' <<'EOF'
set -eu
N=9               # tunnel number
CLIENT=192.0.2.10 # the user's address as seen by the remote host
DNS=8.8.8.8
T=tun$N D=/run/ssh-inet-tunnel-$N
[ "$(cat /sys/class/net/$T/carrier 2>/dev/null)" = 1 ] || { echo "$T is not connected, run step 6" >&2; exit 1; }
mkdir -m 700 "$D"
echo "ip link del $T 2>/dev/null" > "$D/restore.sh"

# Keep the user's SSH connection on its current route.
if [ -z "$(ip -4 route show exact "$CLIENT/32")" ]; then
  VIA=$(ip -4 route get "$CLIENT" | awk 'NR == 1 { for (i = 2; i <= NF && $i != "src"; i++) printf "%s ", $i }')
  ip route add "$CLIENT/32" $VIA
  echo "ip route del $CLIENT/32 $VIA 2>/dev/null" >> "$D/restore.sh"
fi

# Keep private ranges on the current default gateway.
set -- $(ip -4 route show default | head -n 1)
if [ "${2:-}" = via ]; then
  for NET in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16; do
    [ -z "$(ip -4 route show exact $NET)" ] || continue
    ip route add $NET via "$3" dev "$5"
    echo "ip route del $NET via $3 dev $5 2>/dev/null" >> "$D/restore.sh"
  done
fi

# Everything else goes into the tunnel. Two /1 routes beat the default route
# without touching it, and the kernel removes them together with the device.
ip route add 0.0.0.0/1 dev $T
ip route add 128.0.0.0/1 dev $T

# Public DNS while the tunnel is up.
cp -P /etc/resolv.conf "$D/resolv.conf"
if [ -L /etc/resolv.conf ]; then
  echo "rm -f /etc/resolv.conf; cp -P $D/resolv.conf /etc/resolv.conf" >> "$D/restore.sh"
  rm /etc/resolv.conf
else
  echo "cat $D/resolv.conf > /etc/resolv.conf" >> "$D/restore.sh"
fi
{ echo "nameserver $DNS" > /etc/resolv.conf; } 2>/dev/null || echo "warning: cannot write /etc/resolv.conf, DNS unchanged" >&2

# Watchdog: restore everything once the tunnel loses carrier.
echo "rm -rf $D" >> "$D/restore.sh"
cat > "$D/watchdog.sh" <<WATCH
while [ "\$(cat /sys/class/net/$T/carrier 2>/dev/null)" = 1 ]; do sleep 2; done
sh $D/restore.sh
WATCH
if ! systemd-run --quiet --collect --unit "ssh-inet-tunnel-$N" sh "$D/watchdog.sh" 2>/dev/null; then
  setsid sh "$D/watchdog.sh" </dev/null >/dev/null 2>&1 &
fi
echo "remote host routed through $T"
EOF
```

## Step 8. Verify, then do the user's task

```sh
ssh H 'getent hosts example.com; curl -sSI -m 10 https://example.com | head -n 1'
```

Then run what the user asked for. If curl works but a package manager does not, check
the remote proxy settings (`env | grep -i proxy`, `/etc/apt/apt.conf.d/`, `/etc/dnf/dnf.conf`).

## Step 9. Tear down

Ask the user first. Run in this order, replacing 9 with N:

1. Stop the tunnel (user's machine):
   ```sh
   pkill -f 'ssh -f -N -S none -w 9:9 '
   ```
2. Remote host: the watchdog restores routes and DNS and deletes `tun9` within a few
   seconds. Check:
   ```sh
   ssh H 'ls -d /run/ssh-inet-tunnel-9 /sys/class/net/tun9 2>&1; cat /etc/resolv.conf'
   ```
   Both paths must be gone and resolv.conf back to the original. If not, run
   `ssh H 'sudo -n sh /run/ssh-inet-tunnel-9/restore.sh'`. If step 7 never ran, run
   `ssh H 'sudo -n ip link del tun9'`.
3. User's machine: show the undo script, then run it:
   ```sh
   sudo -n cat /run/ssh-inet-tunnel-9/restore.sh
   sudo -n sh /run/ssh-inet-tunnel-9/restore.sh
   ```
   Errors about missing rules are harmless if step 4 stopped halfway.
4. If step 3 changed sshd, ask whether to revert it:
   ```sh
   ssh H 'sudo -n sh -s' <<'EOF'
   rm -f /etc/ssh/sshd_config.d/00-ssh-internet-tunnel.conf
   sed -i '/^# ssh-internet-tunnel$/,+1d' /etc/ssh/sshd_config
   sshd -t
   if [ -d /run/systemd/system ]; then
     for u in ssh sshd; do systemctl try-reload-or-restart "$u" 2>/dev/null || true; done
   else
     kill -HUP "$(cat /run/sshd.pid)"
   fi
   EOF
   ```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `administratively prohibited: open failed` | PermitTunnel is off on the remote host: step 3. |
| `Tunnel device open failed` / `Failed to open the tunnel device` | `tunN` is missing or owned by another user on that side: check U (step 4) and LOGIN (step 5). |
| step 6 route check shows a dev other than E | Traffic would leave elsewhere and the NAT rule would not match. Pick that dev as E, or use `FORCE=yes`. |
| carriers are 1, remote curl times out | Another firewall drops forwarding on the user's machine (firewalld, plain nftables): show `sudo nft list ruleset \| grep -iE 'drop\|reject'` to the user. |
| IPs work, names do not | DNS is blocked on the egress path: ask the user for a public DNS server reachable through E and rerun the DNS part of step 7. A private DNS server is rejected by the step 4 firewall. |
| small requests work, TLS or large downloads hang | MTU: run `ip link set tunN mtu 1280` as root on both hosts. |
| remote internet stops while working | Tunnel dropped and the watchdog restored the network: rerun steps 4 to 7. |
