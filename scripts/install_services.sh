#!/bin/bash
#
# Install the HBlink4 systemd units, with your user, group and paths filled in.
#
#   sudo ./scripts/install_services.sh
#
# Prompts for the service user and group (sensible defaults are offered),
# rewrites the shipped unit files accordingly, installs them to
# /etc/systemd/system/, and reloads systemd. Existing units are backed up first.
#
# Set DESTDIR to install somewhere else (useful for inspecting the result
# without touching the live system):
#
#   sudo DESTDIR=/tmp/preview ./scripts/install_services.sh
#

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'

die() { echo -e "${RED}✗ $*${NC}" >&2; exit 1; }
note() { echo -e "${BLUE}$*${NC}"; }
ok()   { echo -e "${GREEN}✓ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${DESTDIR:-/etc/systemd/system}"
UNITS=(hblink4.service hblink4-dash.service)
LIVE_INSTALL=0
[ -z "${DESTDIR:-}" ] && LIVE_INSTALL=1

if [ "$LIVE_INSTALL" = 1 ] && [ "$(id -u)" -ne 0 ]; then
    die "This script must be run with sudo:  sudo $0"
fi

# ---------------------------------------------------------------- sanity checks

for u in "${UNITS[@]}"; do
    [ -f "$REPO_ROOT/$u" ] || die "Missing $REPO_ROOT/$u -- run this from the HBlink4 checkout."
done

[ -x "$REPO_ROOT/venv/bin/python" ] || die \
    "No virtual environment at $REPO_ROOT/venv
  Create it first:
    python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"

[ -f "$REPO_ROOT/config/config.json" ] || warn \
    "No config/config.json yet -- copy config/config_sample.json and edit it before starting."

echo
note "HBlink4 service installer"
echo "  Install directory : $REPO_ROOT"
echo "  Unit directory    : $UNIT_DIR"
echo

# ------------------------------------------------------------------- user/group

# Default to whoever invoked sudo, falling back to the directory's owner --
# HBlink4 must run as a user that can write logs/ and dashboard/data/.
DEFAULT_USER="${SUDO_USER:-$(stat -c '%U' "$REPO_ROOT")}"
DEFAULT_GROUP="$(id -gn "$DEFAULT_USER" 2>/dev/null || echo "$DEFAULT_USER")"

read -r -p "Service user [$DEFAULT_USER]: " SVC_USER
SVC_USER="${SVC_USER:-$DEFAULT_USER}"
read -r -p "Service group [$DEFAULT_GROUP]: " SVC_GROUP
SVC_GROUP="${SVC_GROUP:-$DEFAULT_GROUP}"

id "$SVC_USER" >/dev/null 2>&1 || die "No such user: $SVC_USER"
getent group "$SVC_GROUP" >/dev/null 2>&1 || die "No such group: $SVC_GROUP"

# The service user must be able to write persistence and logs.
if [ "$(id -u)" -eq 0 ] && ! runuser -u "$SVC_USER" -- test -w "$REPO_ROOT" 2>/dev/null; then
    warn "$SVC_USER cannot write to $REPO_ROOT"
    warn "The dashboard needs write access for dashboard/data/ and logs/."
fi

echo
note "Will install as:"
echo "  User=$SVC_USER"
echo "  Group=$SVC_GROUP"
echo "  WorkingDirectory=$REPO_ROOT"
echo "  ExecStart=$REPO_ROOT/venv/bin/python $REPO_ROOT/hblink4/hblink.py $REPO_ROOT/config/config.json"
echo "  ExecStart=$REPO_ROOT/venv/bin/python $REPO_ROOT/dashboard/server.py"
echo
read -r -p "Proceed? [y/N]: " CONFIRM
case "$CONFIRM" in [yY]|[yY][eE][sS]) ;; *) echo "Aborted."; exit 0 ;; esac

# ---------------------------------------------------------------------- install

mkdir -p "$UNIT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"

for u in "${UNITS[@]}"; do
    if [ -f "$UNIT_DIR/$u" ]; then
        cp -p "$UNIT_DIR/$u" "$UNIT_DIR/$u.bak-$STAMP"
        echo "  backed up existing $u -> $u.bak-$STAMP"
    fi

    # Substitute only the shipped author values; anchored so nothing else matches.
    sed -e "s|/home/cort/hblink4|$REPO_ROOT|g" \
        -e "s|^User=cort$|User=$SVC_USER|" \
        -e "s|^Group=cort$|Group=$SVC_GROUP|" \
        "$REPO_ROOT/$u" > "$UNIT_DIR/$u"
    chmod 644 "$UNIT_DIR/$u"
    ok "installed $UNIT_DIR/$u"
done

# Confirm the substitution produced what we intended, rather than leaving a
# half-rewritten unit in place. (Checked against the chosen values, not against
# the author's literal strings -- those are legitimate if you happen to use the
# same username or path.)
for u in "${UNITS[@]}"; do
    grep -q "^User=$SVC_USER$"                 "$UNIT_DIR/$u" || die "$u: User= was not set correctly"
    grep -q "^Group=$SVC_GROUP$"               "$UNIT_DIR/$u" || die "$u: Group= was not set correctly"
    grep -q "^WorkingDirectory=$REPO_ROOT$"    "$UNIT_DIR/$u" || die "$u: WorkingDirectory= was not set correctly"
    grep -q "^ExecStart=$REPO_ROOT/venv/bin/python " "$UNIT_DIR/$u" || die "$u: ExecStart= was not set correctly"
done

if [ "$LIVE_INSTALL" = 0 ]; then
    echo
    ok "Wrote units to $UNIT_DIR (DESTDIR set -- systemd not touched)."
    exit 0
fi

systemctl daemon-reload
ok "systemctl daemon-reload"

# ------------------------------------------------------------- enable and start

echo
read -r -p "Enable services at boot? [y/N]: " DO_ENABLE
case "$DO_ENABLE" in
    [yY]|[yY][eE][sS]) systemctl enable "${UNITS[@]}" >/dev/null && ok "enabled at boot" ;;
esac

read -r -p "Start (or restart) the services now? [y/N]: " DO_START
case "$DO_START" in
    [yY]|[yY][eE][sS])
        systemctl restart "${UNITS[@]}"
        sleep 2
        echo
        for u in "${UNITS[@]}"; do
            if systemctl is-active --quiet "$u"; then
                ok "$u is running"
            else
                warn "$u did not start -- journalctl -u ${u%.service} -n 30"
            fi
        done
        ;;
esac

echo
note "Done. Useful commands:"
echo "  systemctl status hblink4 hblink4-dash"
echo "  journalctl -u hblink4 -f"
echo
note "If you edit a unit later, edit $UNIT_DIR/<unit> and run 'systemctl daemon-reload'."
