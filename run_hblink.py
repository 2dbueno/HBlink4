#!/usr/bin/env python3
"""
Convenience launcher for the HBlink4 server.

    python run_hblink.py [config/config.json]

Purely a shortcut for interactive use -- it contains no logic beyond locating
hblink4/hblink.py, which is equally runnable on its own:

    python hblink4/hblink.py [config/config.json]

The systemd unit uses that direct path rather than this script.
"""

from hblink4.hblink import main

if __name__ == '__main__':
    main()
