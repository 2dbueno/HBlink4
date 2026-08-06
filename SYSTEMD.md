# HBlink4 Systemd Service Installation

This directory contains systemd service files for running HBlink4 and its dashboard as system services.

## Service Files

- `hblink4.service` - Main HBlink4 DMR server
- `hblink4-dash.service` - Web dashboard (depends on hblink4.service)

## Upgrading an existing install

**The launcher scripts `run.py` and `run_dashboard.py` have been removed.** Both
services now execute their program directly. If you have older unit files
installed, they still point at the deleted scripts and **will fail on the next
restart** — update them before restarting anything.

What changed in the units:

| | Old | New |
|---|---|---|
| `hblink4` `ExecStart` | `.../run.py` | `.../hblink4/hblink.py .../config/config.json` |
| `hblink4-dash` `ExecStart` | `.../run_dashboard.py` | `.../dashboard/server.py` (bind/port now come from `dashboard/config.json`) |
| `hblink4-dash` `WorkingDirectory` | `.../hblink4/dashboard` | `.../hblink4` |
| both | `PrivateTmp=true` | *removed* — see [Security Features](#security-features) |

```bash
cd /home/cort/hblink4
sudo cp hblink4.service hblink4-dash.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart hblink4 hblink4-dash
systemctl status hblink4 hblink4-dash --no-pager
```

Confirm the new command lines took effect:

```bash
systemctl show -p ExecStart hblink4 hblink4-dash | grep -o 'argv\[\]=[^;]*'
```

## Installation

### 1. Install the service files

Copy the service files to systemd's system directory:

```bash
sudo cp hblink4.service /etc/systemd/system/
sudo cp hblink4-dash.service /etc/systemd/system/
```

### 2. Reload systemd

Tell systemd to reload its configuration:

```bash
sudo systemctl daemon-reload
```

### 3. Enable services (optional)

To start the services automatically at boot:

```bash
sudo systemctl enable hblink4
sudo systemctl enable hblink4-dash
```

### 4. Start the services

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

The service files are configured to:
- Run as user `cort` in group `cort`
- Use the Python virtual environment at `/home/cort/hblink4/venv`
- Automatically restart on failure (after 10 seconds)
- Log to systemd journal (view with `journalctl`)
- Start after network is available
- Dashboard starts after and depends on HBlink4

### Customization

If you need to modify the services (different user, paths, etc.), edit the files before copying them:

1. Edit `hblink4.service` and/or `hblink4-dash.service`
2. Change `User=`, `Group=`, `WorkingDirectory=`, or `ExecStart=` as needed
3. Copy to `/etc/systemd/system/`
4. Run `sudo systemctl daemon-reload`

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
