#!/bin/sh
# Print a password typed into a desktop dialog. Used as SUDO_ASKPASS; $1 is the prompt.
# Exit 1: the user cancelled. Exit 2: no dialog can be shown.
P=${1:-Password:}
[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || { echo "askpass: no desktop session" >&2; exit 2; }
for a in "${SSH_ASKPASS:-}" ssh-askpass /usr/lib/ssh/ssh-askpass /usr/libexec/openssh/ssh-askpass \
         /usr/lib/openssh/gnome-ssh-askpass /usr/libexec/openssh/gnome-ssh-askpass; do
  [ -n "$a" ] && command -v "$a" >/dev/null 2>&1 && exec "$a" "$P"
done
command -v zenity >/dev/null 2>&1 && exec zenity --password --title="$P"
command -v kdialog >/dev/null 2>&1 && exec kdialog --password "$P"
echo "askpass: no ssh-askpass, zenity or kdialog" >&2
exit 2
