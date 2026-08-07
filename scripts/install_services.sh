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
# The install location is taken from where this script lives, so the checkout
# can be named anything and live anywhere -- HBlink4, hblink4, /opt/dmr/hb4.
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
VENV_PY="$REPO_ROOT/venv/bin/python"
UNIT_DIR="${DESTDIR:-/etc/systemd/system}"
UNITS=(hblink4.service hblink4-dash.service)
LIVE_INSTALL=0
[ -z "${DESTDIR:-}" ] && LIVE_INSTALL=1

if [ "$LIVE_INSTALL" = 1 ] && [ "$(id -u)" -ne 0 ]; then
    die "This script must be run with sudo:  sudo $0"
fi

# ---------------------------------------------------------------- sanity checks

# The installation path ends up in ExecStart=, where systemd splits on
# whitespace, expands $ as a variable and % as a specifier. A path containing
# any of those produces a unit that fails at start with a misleading error, so
# refuse up front rather than install something broken.
case "$REPO_ROOT" in
    *[[:space:]]*) die "The installation path contains a space:
    $REPO_ROOT
  systemd splits ExecStart= on whitespace, so this cannot work.
  Move the checkout to a path with no spaces and re-run." ;;
    *['$%']*) die "The installation path contains a '\$' or '%':
    $REPO_ROOT
  systemd treats those as variable/specifier escapes in a unit file.
  Move the checkout to a path without them and re-run." ;;
esac

# A wrong or partial clone (downloaded zip of the wrong branch, cloned one
# directory too deep) shows up here rather than as a mystery failure later.
for f in hblink4/hblink.py dashboard/server.py "${UNITS[@]}"; do
    [ -f "$REPO_ROOT/$f" ] || die "Missing $REPO_ROOT/$f
  This does not look like a complete HBlink4 checkout.
  Run the script from the checkout:  sudo ./scripts/install_services.sh"
done

[ -x "$VENV_PY" ] || die \
    "No virtual environment at $REPO_ROOT/venv
  Create it first, from $REPO_ROOT:
    python3 -m venv venv
    ./venv/bin/pip install -r requirements.txt -r requirements-dashboard.txt"

"$VENV_PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null || die \
    "The virtual environment's Python is older than 3.9 (HBlink4 needs 3.9+).
  Check with: $VENV_PY --version"

# Missing dependencies are the most common reason a service starts and then
# restarts forever, and the traceback only shows up in the journal. Name the
# exact command that fixes it.
"$VENV_PY" -c 'import dmr_utils3' 2>/dev/null || die \
    "HBlink4's dependencies are not installed in $REPO_ROOT/venv
  Install them:
    ./venv/bin/pip install -r requirements.txt"

DASH_READY=1
"$VENV_PY" -c 'import fastapi, uvicorn' 2>/dev/null || DASH_READY=0
if [ "$DASH_READY" = 0 ]; then
    warn "The dashboard's dependencies are not installed in $REPO_ROOT/venv"
    warn "hblink4-dash will restart in a loop until you run:"
    warn "    ./venv/bin/pip install -r requirements-dashboard.txt"
fi

echo
note "HBlink4 service installer"
echo "  Install directory : $REPO_ROOT"
echo "  Unit directory    : $UNIT_DIR"
echo

# ----------------------------------------------------------------- config files

# Both programs need their config in place before the services will start.
# Offer to create them from the samples rather than just reporting the problem.
offer_config() {
    local live="$1" sample="$2" label="$3"
    [ -f "$REPO_ROOT/$live" ] && return 0
    if [ ! -f "$REPO_ROOT/$sample" ]; then
        warn "No $live and no $sample to copy from."
        return 0
    fi
    warn "No $live yet."
    read -r -p "  Create it from $sample? [Y/n]: " REPLY_CFG
    case "${REPLY_CFG:-y}" in
        [nN]|[nN][oO]) warn "  $label will not start until $live exists." ;;
        *)
            cp "$REPO_ROOT/$sample" "$REPO_ROOT/$live"
            # Created under sudo, but owned by the person who has to edit it.
            [ -n "${SUDO_USER:-}" ] && chown "$SUDO_USER" "$REPO_ROOT/$live" 2>/dev/null || true
            ok "  created $live -- edit it before going live"
            ;;
    esac
}

offer_config "config/config.json"    "config/config_sample.json"    "hblink4"
offer_config "dashboard/config.json" "dashboard/config_sample.json" "hblink4-dash"

# A mismatch between the two halves of the event link is invisible at runtime:
# the dashboard simply shows HBlink4 as disconnected, with no error either side.
if [ -f "$REPO_ROOT/config/config.json" ] && [ -f "$REPO_ROOT/dashboard/config.json" ]; then
    LINK_PROBLEM="$("$VENV_PY" - "$REPO_ROOT" <<'PY' 2>/dev/null || true
import json, sys, pathlib
root = pathlib.Path(sys.argv[1])
try:
    server = json.loads((root / "config" / "config.json").read_text()).get("dashboard", {})
    dash = json.loads((root / "dashboard" / "config.json").read_text()).get("event_receiver", {})
except Exception as e:
    print(f"could not read both config files ({e})")
    raise SystemExit(0)
st, dt = server.get("transport", "unix"), dash.get("transport", "unix")
if st != dt:
    print(f"transport differs: config/config.json says '{st}', dashboard/config.json says '{dt}'")
elif st == "unix":
    ss, ds = server.get("unix_socket"), dash.get("unix_socket")
    if ss != ds:
        print(f"unix_socket differs: '{ss}' vs '{ds}'")
elif server.get("port") != dash.get("port"):
    print(f"port differs: {server.get('port')} vs {dash.get('port')}")
PY
)"
    if [ -n "$LINK_PROBLEM" ]; then
        warn "Dashboard event link mismatch -- $LINK_PROBLEM"
        warn "The dashboard will show HBlink4 as disconnected until these agree."
        echo
    fi
fi

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
if [ "$(id -u)" -eq 0 ] && command -v runuser >/dev/null 2>&1; then
    if ! runuser -u "$SVC_USER" -- test -w "$REPO_ROOT" 2>/dev/null; then
        warn "$SVC_USER cannot write to $REPO_ROOT"
        warn "The dashboard needs write access for dashboard/data/ and logs/."
    fi
fi

echo
note "Will install as:"
echo "  User=$SVC_USER"
echo "  Group=$SVC_GROUP"
echo "  WorkingDirectory=$REPO_ROOT"
echo "  ExecStart=$VENV_PY $REPO_ROOT/hblink4/hblink.py $REPO_ROOT/config/config.json"
echo "  ExecStart=$VENV_PY $REPO_ROOT/dashboard/server.py"
echo
read -r -p "Proceed? [y/N]: " CONFIRM
case "$CONFIRM" in [yY]|[yY][eE][sS]) ;; *) echo "Aborted."; exit 0 ;; esac

# ---------------------------------------------------------------------- install

mkdir -p "$UNIT_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"

# '&' and '\' are substitution metacharacters on the right-hand side of s|||,
# and would otherwise be pasted in as the matched text.
REPO_ROOT_SED="$(printf '%s' "$REPO_ROOT" | sed -e 's/[&\\|]/\\&/g')"

# Render and verify each unit in full before anything reaches the unit
# directory, so a failed substitution can never leave a half-rewritten unit
# behind for systemd to pick up.
TMPDIR_UNITS="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_UNITS"' EXIT

for u in "${UNITS[@]}"; do
    # Substitute only the shipped author values; anchored so nothing else matches.
    sed -e "s|/home/cort/hblink4|$REPO_ROOT_SED|g" \
        -e "s|^User=cort$|User=$SVC_USER|" \
        -e "s|^Group=cort$|Group=$SVC_GROUP|" \
        "$REPO_ROOT/$u" > "$TMPDIR_UNITS/$u"

    # Confirm the substitution produced what we intended. Checked against the
    # chosen values with fixed-string matching -- the path is data, not a
    # regex, and may legitimately contain '.', '[' or '+'.
    grep -Fqx "User=$SVC_USER"              "$TMPDIR_UNITS/$u" || die "$u: User= was not set correctly"
    grep -Fqx "Group=$SVC_GROUP"            "$TMPDIR_UNITS/$u" || die "$u: Group= was not set correctly"
    grep -Fqx "WorkingDirectory=$REPO_ROOT" "$TMPDIR_UNITS/$u" || die "$u: WorkingDirectory= was not set correctly"
    grep -Fq  "ExecStart=$VENV_PY "         "$TMPDIR_UNITS/$u" || die "$u: ExecStart= was not set correctly"
done

for u in "${UNITS[@]}"; do
    # Back up any existing unit into the project root rather than leaving stray
    # files in /etc/systemd/system -- systemd reads every *.service there, and
    # clutter in a system directory is easy to forget about. The ".bak" suffix
    # is git-ignored.
    if [ -f "$UNIT_DIR/$u" ]; then
        BACKUP="$REPO_ROOT/$u.$STAMP.bak"
        cp -p "$UNIT_DIR/$u" "$BACKUP"
        [ -n "${SUDO_USER:-}" ] && chown "$SUDO_USER" "$BACKUP" 2>/dev/null || true
        echo "  backed up existing $u -> $BACKUP"
    fi

    cp "$TMPDIR_UNITS/$u" "$UNIT_DIR/$u"
    chmod 644 "$UNIT_DIR/$u"
    ok "installed $UNIT_DIR/$u"
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
