---
name: ssh-internet-tunnel
description: Give a remote Linux host that has no internet access temporary internet through the user's own machine, using a layer-3 tunnel carried over a plain SSH connection and rootless NAT (pasta) on the user's machine, preferably out of the user's VPN. Use only when you work on a remote host over SSH, that host cannot reach the internet, the user's machine can, and the user explicitly asks to give the remote host internet access (for example to install packages, pull images or clone repositories). Do not use for ordinary SSH work or start it on your own after a failed download; offer it and wait for the user's request.
---

# SSH internet tunnel

Routes a remote host's IPv4 internet traffic through the user's machine:

```
remote host                                  user's machine, private network namespace (no root)
tunN 10.254.N.2 <-> tunbridge.py == ssh H == tunbridge.py <-> tunN 10.254.N.1 -- NAT -- pasta -- interface E -- internet
```

`tunbridge.py` (in this skill's directory) moves IP packets between a tun device and
stdin/stdout, so the tunnel rides on an ordinary `ssh H` session: no `ssh -w`, no sshd
change. On the user's machine everything runs in a network namespace made by `pasta`
as the normal user; pasta sends the traffic out through interface E with ordinary
sockets. Root is needed only on the remote host.

Requirements: both hosts are Linux; the user's machine has `pasta` (package `passt`) and
`python3`; the remote host has iproute2, `python3` and root (sudo); `ssh H` works without
a password prompt.

## Rules

1. **Do the work yourself; ask once.** Run read-only commands (step 1, the checks, the
   troubleshooting diagnostics) without asking. After step 2, ask for one approval of the
   whole plan, then run steps 3 to 6 one after another without further questions, showing
   each block's output briefly. Ask again only for a choice the user must make (E in
   step 2) or for a change this file does not describe.
2. **Never see passwords.** If step 1 reports `sudo: needs password` on the remote host,
   run its root blocks through a password dialog on the user's desktop (see "Root with a
   sudo password"). The password goes from the dialog straight into sudo; it never appears
   in the chat, your commands or their output. Only if no dialog can be shown, give the
   user the block to paste into a terminal on that host.
3. **Edit only the values at the top of a block** (and the first line, for a sudo
   password). Everything else stays as written.
4. **Fix failures yourself.** Show the error, run the matching troubleshooting entry, and
   retry. If that does not help, offer step 7.
5. **Tear down when done.** When the user's task is finished, ask once and run all of
   step 7.

The approval message after step 2 lists the values found, E, which steps change what on
which host, and in a few lines what will happen:

- The remote host's internet traffic leaves through the user's machine and interface E
  (their VPN if there is one), with the user's public IP.
- Nothing on the user's machine needs root or changes: the tunnel lives in a private
  network namespace that disappears when the tunnel stops.
- While active, the remote host uses public DNS (`8.8.8.8` by default); internal names may
  not resolve. Its private ranges (10/8, 172.16/12, 192.168/16) and the SSH connection to
  the user keep their current routes.
- Tunnel traffic to the user's machine and to private ranges is rejected: the remote host
  gets the internet only, not the user's LAN or VPN-internal networks.
- IPv4 only. A watchdog restores the remote network if the tunnel drops.

## Values

| Value | Meaning | Source |
|---|---|---|
| `H` | ssh destination exactly as the user uses it (alias or `user@host`) | conversation |
| `N` | tunnel number: device `tunN` on both ends, `10.254.N.1` local, `10.254.N.2` remote | step 1: smallest N from 9 up with no `tunN` and no `10.254.N.` address on the remote host |
| `LOGIN` | remote login user | step 1 `login:` |
| `CLIENT` | the user's address as the remote host sees it | step 1 `client:` |
| `PY` | python on the remote host | step 1 `python:` |
| `E` | egress interface on the user's machine | step 2 |
| `BRIDGE` | full path of `tunbridge.py` in this skill's directory | this skill |
| `DNS` | DNS server for the remote host, default `8.8.8.8` | troubleshooting, if it fails |

## Root with a sudo password

`askpass.sh` in this skill's directory opens a password dialog on the user's desktop
(ssh-askpass, zenity or kdialog) and prints the password. With `A` its full path, change
only the first line of a root block:

- Remote host: `ssh H 'sudo -n sh -s' <<'EOF'` becomes (the remote side reads the password
  line, validates it with `sudo -v`, then runs the rest of the block as root)
  ```
  P=$(A "sudo password for LOGIN on H") || exit
  { printf '%s\n' "$P"; cat; } <<'EOF' | ssh H 'IFS= read -r P; printf "%s\n" "$P" | sudo -S -p "" -v && sudo -n sh -s; exit $?'
  ```
  Keep this line as is: without a tty, sudo caches the password per parent process, so
  both sudo calls must be children of the same shell (no `exec`).
- User's machine (only to install `passt`): `sudo -n CMD` becomes `SUDO_ASKPASS=A sudo -A CMD`.

Turn a one-line root command (step 7) into such a block with the command as its body.
Never print `$P` or pass it anywhere else. If the user cancels the dialog, stop and ask.
If `askpass.sh` prints `askpass: no ...` (no dialog can be shown, exit 2), fall back to
handing the block, from `sudo sh -s <<'EOF'` to `EOF`, to the user to paste into a terminal
on that host (for the remote host: inside `ssh H`), and ask for the output.
If the remote host prints `a password is required` after a correct password, its sudo does
not cache credentials: fall back to pasting for that host.

## Step 1. Discover (read-only, both hosts)

User's machine:

```sh
ip -4 route get 1.1.1.1
echo "vpn-like:"; ip -o -d link show | grep -E 'POINTOPOINT|wireguard|tun type' | cut -d: -f2
curl -sS -m 5 -o /dev/null -w 'internet: http %{http_code}\n' https://example.com
command -v python3 >/dev/null && echo "python3: ok" || echo "python3: missing"
if pasta --config-net -q -- true 2>/dev/null; then echo "pasta: ok"
elif command -v pasta >/dev/null; then echo "pasta: blocked"; else echo "pasta: missing"; fi
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
echo "python: $(command -v python3 || command -v /usr/libexec/platform-python || echo none)"
sudo -n true 2>/dev/null && echo "sudo: ok" || echo "sudo: needs password"
EOF
```

Stop if the remote host already has internet or the user's machine has none. If
`python: none`, stop and tell the user the remote host has no Python. If `pasta: missing`,
include installing package `passt` (as root, through the password dialog) in the
approval message. For `pasta: blocked`, see troubleshooting.

## Step 2. Choose the egress interface E

`ip -4 route get 1.1.1.1` shows `dev X`: where internet traffic really goes now. It includes
VPN policy routing, so trust it over `ip route show default`. The `vpn-like` list holds
point-to-point, tun and WireGuard links (OpenVPN, WireGuard, sing-box or clash TUN, ppp,
tailscale). Their names vary, so judge by this list, not by name.

- X is in the vpn-like list, or the list is empty: `E=X`.
- X is not, but the list is not empty: in the approval message, ask the user to choose
  between `E=X` (current route) and `E=<vpn>` (works only if that VPN carries internet
  traffic, which split-tunnel corporate VPNs often do not).

Name E in the approval message (rule 1); the user may pick another interface. pasta binds
its sockets to E, so tunnel traffic leaves only through E, even when E is not the current
route; if E goes down, the remote host loses internet instead of leaking out of another
interface.

## Step 3. Prepare the remote host (root)

Creates `tunN` owned by LOGIN, so the remote bridge runs without root.
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

## Step 4. Start the tunnel (user's machine, no root)

Checks that pasta reaches the internet through E, then starts in the background, detached
from your shell: pasta with a private namespace holding `tunN`, NAT and the firewall, and
`ssh H` running the remote bridge. State and log go to
`$XDG_RUNTIME_DIR/ssh-inet-tunnel-N/` (or `/tmp/...`).

```sh
sh -s <<'EOF'
set -eu
N=9                    # tunnel number
E=wg0                  # egress interface
PY=python3             # python on the remote host
BRIDGE=/path/to/tunbridge.py
D=${XDG_RUNTIME_DIR:-/tmp}/ssh-inet-tunnel-$N
PASTA="pasta --config-net -q --no-map-gw --outbound-if4 $E"
BLOCK=0.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16,100.64.0.0/10
SELF=$(ip -4 -o addr show | tr -s ' ' | cut -d' ' -f4 | cut -d/ -f1 | paste -sd, -)
IP=$(getent ahostsv4 example.com | head -n 1 | cut -d' ' -f1)
$PASTA -- curl -sS -m 10 -o /dev/null --resolve "example.com:443:$IP" https://example.com \
  || { echo "pasta cannot reach the internet through $E" >&2; exit 1; }
mkdir -m 700 "$D"
mkfifo "$D/in"
cat > "$D/ns.sh" <<NS
set -eu
ip tuntap add dev tun$N mode tun
ip addr add 10.254.$N.1 peer 10.254.$N.2 dev tun$N
ip link set tun$N up
sysctl -qw net.ipv4.ip_forward=1
iptables -A INPUT -i tun$N -j DROP
iptables -A FORWARD -i tun$N -d $BLOCK,$SELF -j REJECT
iptables -t nat -A POSTROUTING -s 10.254.$N.2 -j MASQUERADE
echo "local side ready: tun$N 10.254.$N.1 <-> 10.254.$N.2, egress $E" >&2
exec python3 $BRIDGE tun$N
NS
D="$D" PASTA="$PASTA" REMOTE="$PY -c \"import base64; exec(base64.b64decode('$(base64 -w0 "$BRIDGE")'))\" tun$N" \
  setsid sh -c 'echo $$ > "$D/pid"
    $PASTA -- sh "$D/ns.sh" < "$D/in" \
      | ssh -T -o ServerAliveInterval=15 -o ServerAliveCountMax=3 H "$REMOTE" > "$D/in"' \
  < /dev/null > /dev/null 2> "$D/log" &
for i in 1 2 3 4 5 6 7 8 9 10; do
  sleep 1
  kill -0 "$(cat "$D/pid" 2>/dev/null)" 2>/dev/null || break
  if grep -q 'local side ready' "$D/log" && [ "$(ssh -n H cat /sys/class/net/tun$N/carrier)" = 1 ]; then
    cat "$D/log"; echo "tunnel up"; exit 0
  fi
done
cat "$D/log"; echo "tunnel failed" >&2; exit 1
EOF
```

It must print `tunnel up`. pasta may also print `Couldn't get any nameserver address`;
that is harmless.

## Step 5. Route the remote host through the tunnel (root)

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
[ "$(cat /sys/class/net/$T/carrier 2>/dev/null)" = 1 ] || { echo "$T is not connected, run step 4" >&2; exit 1; }
mkdir -m 700 "$D"
echo "ip link del $T 2>/dev/null" > "$D/restore.sh"

# Keep the user's SSH connection on its current route.
if [ -z "$(ip -4 route show exact "$CLIENT/32")" ]; then
  VIA=$(ip -4 route get "$CLIENT" | awk 'NR == 1 { for (i = 2; i <= NF && $i != "src"; i++) printf "%s ", $i }')
  ip route add "$CLIENT/32" $VIA
  echo "ip route del $CLIENT/32 $VIA 2>/dev/null" >> "$D/restore.sh"
fi

# Keep private ranges on the current default gateway.
read -r _ VIA GW _ DEV _ <<ROUTE
$(ip -4 route show default | head -n 1)
ROUTE
if [ "$VIA" = via ]; then
  for NET in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16; do
    [ -z "$(ip -4 route show exact $NET)" ] || continue
    ip route add $NET via "$GW" dev "$DEV"
    echo "ip route del $NET via $GW dev $DEV 2>/dev/null" >> "$D/restore.sh"
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

## Step 6. Verify, then do the user's task

```sh
ssh H 'getent hosts example.com; curl -sSI -m 10 https://example.com | head -n 1'
```

Then run what the user asked for. If curl works but a package manager does not, check
the remote proxy settings (`env | grep -i proxy`, `/etc/apt/apt.conf.d/`, `/etc/dnf/dnf.conf`).

## Step 7. Tear down

Ask the user once, then run all of it in this order, replacing 9 with N:

1. Stop the tunnel (user's machine). This ends ssh, both bridges and the namespace with
   its NAT and firewall:
   ```sh
   D=${XDG_RUNTIME_DIR:-/tmp}/ssh-inet-tunnel-9
   pkill -g "$(cat "$D/pid")"; rm -rf "$D"
   ```
2. Remote host: the watchdog restores routes and DNS and deletes `tun9` within a few
   seconds. Check:
   ```sh
   ssh H 'ls -d /run/ssh-inet-tunnel-9 /sys/class/net/tun9 2>&1; cat /etc/resolv.conf'
   ```
   Both paths must be gone and resolv.conf back to the original. If not, run
   `ssh H 'sudo -n sh /run/ssh-inet-tunnel-9/restore.sh'`. If step 5 never ran, run
   `ssh H 'sudo -n ip link del tun9'`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `pasta: blocked` | Unprivileged user namespaces are restricted (Ubuntu: `kernel.apparmor_restrict_unprivileged_userns=1`) and this pasta has no AppArmor profile. The distribution's `passt` package ships one: install it (as root, through the password dialog) instead of a self-built pasta. If it is still blocked, stop and tell the user. |
| `pasta cannot reach the internet through E` | E has no internet: pick another E in step 2. |
| `tunnel failed` | Read the log it prints. `Permission denied` or `Operation not permitted` from the remote bridge: `tunN` there is missing or owned by another user, check LOGIN (step 3). ssh errors: check that `ssh H true` works. Then run `rm -rf $XDG_RUNTIME_DIR/ssh-inet-tunnel-N` and retry step 4. |
| IPs work, names do not | DNS is blocked on the egress path: on the remote host, as root, write `nameserver 1.1.1.1` to `/etc/resolv.conf`, then `9.9.9.9`, and rerun step 6 after each. If neither works, ask the user for a public DNS server reachable through E. A private DNS server is rejected by the step 4 firewall. |
| remote internet stops while working | Tunnel dropped and the watchdog restored the network: run step 7, then steps 3 to 5 again. |
