#!/usr/bin/env python3
"""End-to-end test of SKILL.md in Docker.

Runs the skill's shell blocks, as written, between two privileged containers:
`local` (has internet) and `remote` (internal network only). Only the values at
the top of each block are substituted, like an agent would do.

Usage: python3 test/e2e.py        (needs docker; leaves nothing behind)
"""
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = (ROOT / "skills/ssh-internet-tunnel/SKILL.md").read_text()
IMAGE = "ssh-internet-tunnel-test"
NETS = ("sit-inet", "sit-air")
DOCKERFILE = """
FROM debian:13
RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-client openssh-server iproute2 iptables curl ca-certificates sudo procps \
      python3 passt \
    && rm -rf /var/lib/apt/lists/* && mkdir -p /run/sshd
RUN for u in alice bob; do useradd -m -s /bin/bash $u \
      && echo "$u ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/$u; done
"""


def sh(cmd, check=True, **kw):
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True, **kw)
    if check and r.returncode:
        sys.exit(f"FAILED: {cmd}\n{r.stdout}{r.stderr}")
    return r.stdout


def steps():
    """Map step number -> list of shell blocks under that heading."""
    out = {}
    for m in re.finditer(r"^## Step (\d+)\..*?(?=^## |\Z)", SKILL, re.M | re.S):
        blocks = re.findall(r"^( *)```sh\n(.*?)^\1```", m.group(0), re.M | re.S)
        out[int(m.group(1))] = [re.sub(rf"(?m)^{ind}", "", b) for ind, b in blocks]
    return out


def run_local(block, subs=()):
    """Run a block in `local` as alice, like an agent's shell tool would."""
    block = re.sub(r"(?<=\s)H(?=\s|$)", "remote", block)
    for old, new in subs:
        assert re.search(old, block, re.M), f"{old!r} not in block"
        block = re.sub(old, new, block, flags=re.M)
    sh("docker exec -i local sh -c 'cat > /tmp/block.sh'", input=block)
    r = subprocess.run("docker exec -u alice -w /home/alice local sh /tmp/block.sh",
                       shell=True, text=True, capture_output=True)
    print(f"$ ---\n{block}--> rc={r.returncode}\n{r.stdout}{r.stderr}")
    if r.returncode:
        sys.exit("block failed")
    return r.stdout


def remote(cmd):
    return sh(f"docker exec remote sh -c '{cmd}'", check=False)


def setup():
    sh(f"docker build -q -t {IMAGE} -", input=DOCKERFILE)
    sh(f"docker network create {NETS[0]}")
    sh(f"docker network create --internal {NETS[1]}")
    for name, net in (("remote", NETS[1]), ("local", NETS[0])):
        sh(f"docker run -d --init --privileged --name {name} --hostname {name} --network {net} {IMAGE} sleep infinity")
    sh(f"docker network connect {NETS[1]} local")
    # remote: sshd with alice's key for bob
    sh("docker exec -u alice local sh -c 'ssh-keygen -q -t ed25519 -N \"\" -f ~/.ssh/id_ed25519'")
    key = sh("docker exec local cat /home/alice/.ssh/id_ed25519.pub")
    sh("docker exec -i remote sh -c 'mkdir -p ~bob/.ssh && cat > ~bob/.ssh/authorized_keys"
       " && chown -R bob ~bob/.ssh && /usr/sbin/sshd'", input=key)
    sh("docker exec -i -u alice local sh -c 'cat > ~/.ssh/config'",
       input="Host remote\n  User bob\n  StrictHostKeyChecking accept-new\n")
    sh("docker cp skills/ssh-internet-tunnel/tunbridge.py local:/home/alice/tunbridge.py", cwd=ROOT)
    # an air-gapped LAN usually still has a default gateway that goes nowhere
    gw = sh("docker network inspect -f '{{(index .IPAM.Config 0).Gateway}}' " + NETS[1]).strip()
    remote(f"ip route replace default via {gw}")


def cleanup():
    sh("docker rm -f local remote", check=False)
    sh(f"docker network rm {' '.join(NETS)}", check=False)


def main():
    # Claude Code replaces $0, $1, ... in SKILL.md with the skill's arguments.
    assert not re.search(r"\$\d", SKILL), "SKILL.md must not use positional parameters"
    cleanup()
    setup()
    s = steps()
    resolv_before = remote("cat /etc/resolv.conf")
    default_before = remote("ip -4 route show default")

    out = run_local(s[1][0]) + run_local(s[1][1])
    assert "internet: no" in out and "internet: http 200" in out
    assert "pasta: ok" in out and "python: /usr/bin/python3" in out
    egress = re.search(r"dev (\S+)", out).group(1)
    client = re.search(r"client: (\S+)", out).group(1)
    iptables_before = sh("docker exec local sh -c 'iptables -S; iptables -t nat -S'")

    run_local(s[3][0])
    out = run_local(s[4][0], [(r"^E=\S+", f"E={egress}"),
                              (r"^BRIDGE=\S+", "BRIDGE=/home/alice/tunbridge.py")])
    assert "tunnel up" in out
    run_local(s[5][0], [(r"^CLIENT=\S+", f"CLIENT={client}")])
    out = run_local(s[6][0])
    assert "HTTP/2 200" in out or "HTTP/1.1 200" in out

    # The tunnel must not reach the user's machine: neither the namespace end nor the
    # host's own addresses. --interface forces the request into the tunnel.
    sh("docker exec -d -u alice local python3 -m http.server 8000")
    local_ip = sh("docker exec local hostname -I").split()[0]
    for target in ("10.254.9.1", local_ip):
        rc = remote(f"curl -s -m 3 --interface tun9 http://{target}:8000 >/dev/null; echo $?")
        assert rc.strip() != "0", f"remote reached {target} through the tunnel"
    # Nothing changed on the user's machine itself.
    assert sh("docker exec local sh -c 'iptables -S; iptables -t nat -S'") == iptables_before
    assert "tun9" not in sh("docker exec local ls /sys/class/net")

    # Drop the tunnel: the watchdog must restore the remote host on its own.
    run_local(s[7][0])
    time.sleep(5)
    out = run_local(s[7][1])
    assert out.count("No such file") == 2
    assert remote("cat /etc/resolv.conf") == resolv_before
    assert remote("ip -4 route show default") == default_before
    assert "10.0.0.0/8" not in remote("ip route")
    assert "pasta" not in sh("docker exec local ps -eo stat=,comm= | grep -v ^Z")
    assert "permittunnel no" in remote("sshd -T | grep -i ^permittunnel")
    print("\nOK: tunnel up, remote got internet, everything restored")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
