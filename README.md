# ssh-internet-tunnel

An agent skill that gives a remote Linux host without internet temporary access through
your machine. When you ask an agent (Claude Code, Codex, Gemini CLI, Cursor, GitHub
Copilot, OpenCode) to do something on a host over SSH, the host has no internet, and you
explicitly ask to give it some, the agent follows `skills/ssh-internet-tunnel/SKILL.md`.

```
remote host                                  your machine, private network namespace (no root)
tunN 10.254.N.2 <-> tunbridge.py == ssh H == tunbridge.py <-> tunN 10.254.N.1 -- NAT -- pasta -- VPN or default interface -- internet
```

The skill is plain text plus two small helpers: every command is in `SKILL.md`. The agent
inspects both hosts on its own, asks you once to approve the plan, then sets everything up
and shows the output. Where `sudo` on the remote host asks for a password, the agent opens
a password dialog on your desktop (`askpass.sh`: ssh-askpass, zenity or kdialog) and pipes
what you type straight into sudo, so the password never reaches the agent. Without a
desktop session it hands you the block to paste instead.

What it does:

- Needs no root on your machine. `pasta` (from the `passt` package) gives a private
  network namespace to your normal user; the tun device, NAT and firewall live in it and
  disappear when the tunnel stops. pasta sends the traffic out through ordinary sockets.
- Carries the tunnel over a plain `ssh H` session: `tunbridge.py` on each end moves
  packets between the tun device and ssh's stdin/stdout. No `ssh -w`, no sshd change on
  the remote host.
- Detects the egress interface on your machine with `ip route get`, so VPNs that work via
  policy routing (WireGuard, sing-box or clash TUN, OpenVPN) are found whatever their
  name. A VPN is preferred; you confirm or pick another interface. pasta binds its sockets
  to that interface, so traffic never leaks out of another one.
- Rejects tunnel traffic to your machine's own addresses and to private ranges.
- On the remote host: routes the internet through the tunnel with two `/1` routes (the
  default route stays untouched), keeps your SSH connection and private ranges on their
  current routes, switches DNS, and starts a watchdog that restores everything if the
  tunnel drops. The undo script is `/run/ssh-inet-tunnel-N/restore.sh`.

Requirements: Linux on both ends; `pasta` and `python3` on your machine; `python3` and
root on the remote host; key-based `ssh` to it. IPv4 only.

## Install

```sh
git clone <this repo> && cd tunnel-skill
./install.sh               # copy to ~/.agents/skills, symlink into ~/.claude/skills
./install.sh --uninstall   # remove
```

`~/.agents/skills` is read by Codex, Gemini CLI, Cursor, GitHub Copilot and OpenCode;
Claude Code reads `~/.claude/skills`. With the [skills CLI](https://github.com/vercel-labs/skills)
you can instead run `npx skills add <owner>/<repo>`.

## Use

Ask, for example: "install docker on build-01 over ssh; it has no internet, give it mine".
In Claude Code you can also call it directly: `/ssh-internet-tunnel`.

## Test

```sh
python3 test/e2e.py
```

Needs Docker. Starts two privileged Debian containers, `local` (internet) and `remote`
(internal network only), runs the `SKILL.md` blocks as written with only the top values
filled in, checks that `remote` reaches `https://example.com` but not `local` itself, that
nothing changed on `local`, drops the tunnel, and checks that both sides are restored.
Removes the containers and networks at the end.
