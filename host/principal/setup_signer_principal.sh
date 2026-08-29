#!/usr/bin/env bash
# Creates the gate-signer principal (docs/decisions.md D4 option A). Run ONCE with sudo.
# Owner-run; nothing here touches the board. Idempotent where possible.
#
#   signer user  : p3signer  (no login shell; reached only via `sudo -u p3signer`)
#   pod group    : p3jtag    (udev gives the JTAG pod to it; the runner user is NOT a member)
#   key store    : /var/lib/p3signer/keys  (0700 p3signer; K.bin 0400)
#   sudoers      : the runner user may run exactly host/sign_arm.py as p3signer, nothing else
set -euo pipefail
RUNNER_USER="${RUNNER_USER:-test}"
REPO="${REPO:-/home/test/zynq_psoracle}"
STORE=/var/lib/p3signer/keys
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 2; }
getent group p3jtag >/dev/null || groupadd --system p3jtag
getent passwd p3signer >/dev/null || useradd --system --home-dir /var/lib/p3signer --create-home \
    --shell /usr/sbin/nologin --gid p3jtag p3signer
usermod -aG p3jtag p3signer
# the runner must NOT be in the pod group (the whole point)
if id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -qx p3jtag; then gpasswd -d "$RUNNER_USER" p3jtag; fi
install -d -m 0700 -o p3signer -g p3jtag "$STORE"
if [ -f "$REPO/keys/K.bin" ] && [ ! -f "$STORE/K.bin" ]; then
    install -m 0400 -o p3signer -g p3jtag "$REPO/keys/K.bin" "$STORE/K.bin"
    shred -u "$REPO/keys/K.bin"          # the runner's copy must not remain
    echo "moved K.bin -> $STORE/K.bin (runner copy shredded)"
fi
# a second key for the wrong_key negative control, signer-owned
if [ ! -f "$STORE/K_control.bin" ]; then
    head -c 16 /dev/urandom > "$STORE/K_control.bin"; chown p3signer:p3jtag "$STORE/K_control.bin"; chmod 0400 "$STORE/K_control.bin"
fi
install -m 0644 "$REPO/host/principal/99-p3-signer-jtag.rules" /etc/udev/rules.d/99-p3-signer-jtag.rules
udevadm control --reload && udevadm trigger --subsystem-match=usb
# the runner may ask the signer for exactly one program, no shell, no other args prefix
# fixed key paths only (re-review 2026-08-29: no trailing wildcard on the signer's input)
cat > /etc/sudoers.d/p3signer <<SUDO
$RUNNER_USER ALL=(p3signer) NOPASSWD: $(command -v python3) $REPO/host/sign_arm.py $STORE/K.bin
$RUNNER_USER ALL=(p3signer) NOPASSWD: $(command -v python3) $REPO/host/sign_arm.py $STORE/K_control.bin
SUDO
chmod 0440 /etc/sudoers.d/p3signer
visudo -cf /etc/sudoers.d/p3signer
# the signer must be able to read the repo (host/, validators/, scripts/) but not write it
chmod -R o+rX "$REPO/host" "$REPO/validators" "$REPO/scripts" "$REPO/imported"
# ...and must be able to TRAVERSE to it (a 0750 home directory blocks the signer: found on first run)
chmod o+x "$(dirname "$REPO")" "$REPO"
echo "done. verify as the runner:  python3 $REPO/host/verify_principal_boundary.py --out <record.json>"
