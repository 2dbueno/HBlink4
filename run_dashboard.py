#!/usr/bin/env python3
"""
Convenience launcher for the HBlink4 dashboard.

    python run_dashboard.py [bind] [port]

Purely a shortcut for interactive use -- it contains no logic beyond locating
dashboard/server.py, which is equally runnable on its own:

    python dashboard/server.py [bind] [port]

The systemd unit uses that direct path rather than this script. With no
arguments the bind address and port come from the 'web' section of
dashboard/config.json.
"""

from dashboard.server import run

if __name__ == '__main__':
    run()
