# ssh-internet-tunnel

An agent skill that gives a remote Linux host without internet temporary access through
your machine. When you ask an agent (Claude Code, Codex, Gemini CLI, Cursor, GitHub
Copilot, OpenCode) to do something on a host over SSH, the host has no internet, and you
explicitly ask to give it some, the agent follows `skills/ssh-internet-tunnel/SKILL.md`.

```
remote host --- ssh -w (tunN) ---> your machine --- NAT ---> VPN or default interface ---> internet
```

The skill is plain text: every command is in `SKILL.md`. The agent shows each block with
the values filled in, asks before running it, and shows the output. Blocks that need root
on a host where `sudo` asks for a password are handed to you to paste instead.

What it does:

- Detects the egress interface on your machine with `ip route get`, so VPNs that work via
  policy routing (WireGuard, sing-box or clash TUN, OpenVPN) are found whatever their
  name. A VPN is preferred; you confirm or pick another interface.
- Pre-creates user-owned tun devices, so `ssh -w` runs without root and without root SSH
  login. Picks a free tunnel number and subnet (`10.254.N.0/30`).
- On your machine: NAT out of that interface only, no access to your machine or private
  ranges from the tunnel, `ip_forward` restored to its previous value afterwards.
- On the remote host: routes the internet through the tunnel with two `/1` routes (the
  default route stays untouched), keeps your SSH connection and private ranges on their
  current routes, switches DNS, and starts a watchdog that restores everything if the
  tunnel drops.
- Each side writes an undo script to `/run/ssh-inet-tunnel-N/restore.sh` at setup.

Requirements: Linux on both ends, `iptables` on your machine, root on both hosts,
key-based `ssh` to the remote host. IPv4 only.

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
filled in, checks that `remote` reaches `https://example.com`, drops the tunnel, and checks
that both sides are restored. Removes the containers and networks at the end.
