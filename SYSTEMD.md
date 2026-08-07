# HBlink4 Systemd Service Installation

This directory contains systemd service files for running HBlink4 and its dashboard as system services.

## Service Files

- `hblink4.service` - Main HBlink4 DMR server
- `hblink4-dash.service` - Web dashboard (depends on hblink4.service)

The units run the programs straight from the checkout — there is no install
step, so after a `git pull` you only need to restart the services. If you are
upgrading from a version whose units pointed at `run.py`, re-copy the unit files
below before restarting.

## Quick install (recommended)

The shipped unit files contain the author's user and paths (`User=cort`,
`/home/cort/hblink4`), so they will not work as-is on your system. This script
asks for your service user and group, fills in your paths, installs both units
and reloads systemd:

```bash
sudo ./scripts/install_services.sh
```

It offers sensible defaults (the user who invoked `sudo`, and that user's
primary group), backs up any units you already have into the project root as
`<unit>.<timestamp>.bak`, and optionally enables and starts the services.

Before writing anything it checks the things that otherwise fail later, in the
journal, where they are hard to read:

- the checkout is complete, and its path contains no character systemd will
  mis-parse in `ExecStart=` (a space, `$` or `%`)
- `venv/` exists and its Python is 3.9 or newer
- the server's dependencies are installed, and the dashboard's — a missing
  `fastapi` is the usual reason `hblink4-dash` restarts in a loop
- `config/config.json` and `dashboard/config.json` exist, offering to create
  them from the samples if not
- the two halves of the dashboard event link agree; if they do not, the
  dashboard silently shows HBlink4 as disconnected
- the service user can write to the installation directory

To see what it would produce without touching the live system:

```bash
sudo DESTDIR=/tmp/preview ./scripts/install_services.sh
```

The manual steps below do the same thing by hand.

## Manual installation

> **⚠️ The shipped unit files contain the author's user and paths** —
> `User=cort`, `Group=cort`, and `/home/cort/hblink4` throughout. **They will not
> work as-is on your system.** You must change the user, the group, and every
> path to match your installation.
>
> Edit the *installed* copies in `/etc/systemd/system/`, not the ones in the
> repository — editing the repo copies makes them show up as local changes and
> conflict on the next `git pull`.

### 1. Install the service files

Copy the service files to systemd's system directory:

```bash
sudo cp hblink4.service /etc/systemd/system/
sudo cp hblink4-dash.service /etc/systemd/system/
```

### 2. Set your user and paths

Four settings in each file need to match your system: `User=`, `Group=`,
`WorkingDirectory=`, and `ExecStart=`. Edit them with your editor of choice:

```bash
sudo nano /etc/systemd/system/hblink4.service
sudo nano /etc/systemd/system/hblink4-dash.service
```

Or, run this from your HBlink4 directory to substitute them automatically:

```bash
sudo sed -i "s|/home/cort/hblink4|$PWD|g; s|^User=cort$|User=$USER|; s|^Group=cort$|Group=$(id -gn)|" \
    /etc/systemd/system/hblink4.service /etc/systemd/system/hblink4-dash.service
```

Check the result before continuing — no `cort` or `/home/cort` should remain:

```bash
grep -nE "^(User|Group|WorkingDirectory|ExecStart)=" /etc/systemd/system/hblink4*.service
```

### 3. Reload systemd

Tell systemd to reload its configuration. **This is required after any edit to a
unit file** — systemd will keep using the old version until you do:

```bash
sudo systemctl daemon-reload
```

### 4. Enable services (optional)

To start the services automatically at boot:

```bash
sudo systemctl enable hblink4
sudo systemctl enable hblink4-dash
```

### 5. Start the services

```bash
sudo systemctl start hblink4
sudo systemctl start hblink4-dash
```

## Service Management

### Check service status

```bash
sudo systemctl status hblink4
sudo systemctl status hblink4-dash
```

### View logs

```bash
# View logs for HBlink4
sudo journalctl -u hblink4 -f

# View logs for dashboard
sudo journalctl -u hblink4-dash -f

# View last 100 lines
sudo journalctl -u hblink4 -n 100
```

### Stop services

```bash
sudo systemctl stop hblink4
sudo systemctl stop hblink4-dash
```

### Restart services

```bash
sudo systemctl restart hblink4
sudo systemctl restart hblink4-dash
```

### Disable autostart

```bash
sudo systemctl disable hblink4
sudo systemctl disable hblink4-dash
```

## Configuration

As shipped, the service files:
- Run as user `cort` in group `cort` — **change this to your own user and group**
- Use the Python virtual environment at `/home/cort/hblink4/venv` — **change to your path**
- Automatically restart on failure (after 10 seconds)
- Log to systemd journal (view with `journalctl`)
- Start after network is available
- Dashboard starts after and depends on HBlink4

### Changing a unit file later

Always edit the copy in `/etc/systemd/system/`, then reload and restart:

```bash
sudo nano /etc/systemd/system/hblink4.service
sudo systemctl daemon-reload      # required, or systemd keeps the old version
sudo systemctl restart hblink4
```

Editing the copy in the repository has no effect on a running service, and
leaves you with local changes that conflict on the next `git pull`.

## Security Features

Both services include security hardening:
- `NoNewPrivileges=true` - Prevents privilege escalation

**Do not add `PrivateTmp=true`.** It gives each service its own private `/tmp`
namespace, so with the `unix` event transport HBlink4 and the dashboard would
each create a separate `/tmp/hblink4.sock` and never see each other. The
dashboard would simply report HBlink4 as disconnected, with no error on either
side. If you want `PrivateTmp`, move `unix_socket` out of `/tmp` on both sides
first (or use the `tcp` transport).

## Troubleshooting

### Service won't start

Check the status and logs:
```bash
sudo systemctl status hblink4
sudo journalctl -u hblink4 -n 50
```

Common issues:
- Virtual environment not found: Check path in `ExecStart=`
- Permission errors: Ensure user/group are correct
- Config file errors: Check HBlink4 configuration files
- Port conflicts: Another service using the same ports

### Dashboard can't connect to HBlink4

1. Ensure HBlink4 is running: `sudo systemctl status hblink4`
2. Check dashboard config points to correct socket/host
3. If using the `unix` transport, confirm neither unit sets `PrivateTmp=true`
   (see Security Features above) and that both sides name the same socket path
4. Check logs: `sudo journalctl -u hblink4-dash -n 50`

## Notes

- The dashboard service has `Wants=hblink4.service`, so it will start after HBlink4
- Both services have `Restart=always` for automatic recovery
- Logs are sent to systemd journal, not file-based logging
- Services run with the same privileges as the `cort` user
