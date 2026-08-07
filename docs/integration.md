# HBlink4 Integration Guide

This document describes how to use HBlink4 as a module in your own applications for advanced DMR routing and control.

For basic installation and setup, see the main [README](../readme.md).

## Overview

HBlink4 is modular, allowing you to access repeater metadata, connection states, and control the routing of DMR traffic. The main interface is the `HBProtocol` class, an `asyncio.DatagramProtocol`. HBlink4 runs on Python's `asyncio` event loop and has no external framework dependency.

## Core Classes

### HBProtocol

The protocol handler that manages repeater connections and DMR traffic. One instance is bound per listening socket.

```python
from hblink4.hblink import HBProtocol

protocol = HBProtocol()
```

### RepeaterState

Each inbound connection is represented by a `RepeaterState`. Despite the name it represents any inbound HomeBrew connection — repeater, hotspot, or another network's server.

#### Selected properties

| Property | Type | Description |
|----------|------|-------------|
| `repeater_id` | bytes | DMR ID (4 bytes) |
| `ip` | str | Peer IP address |
| `port` | int | Peer UDP port |
| `connected` | bool | Connection completed |
| `authenticated` | bool | Authentication completed |
| `connection_state` | str | `'login'`, `'config'`, or `'connected'` |
| `connection_type` | str | `'repeater'`, `'hotspot'`, `'network'`, or `'unknown'` |
| `last_ping` | float | Timestamp of last ping received |
| `ping_count` | int | Number of pings received |
| `missed_pings` | int | Consecutive missed pings |
| `callsign` | bytes | Callsign from config |
| `description` | bytes | Description from config |
| `slots` | bytes | Supported timeslots |
| `url` | bytes | URL from config |
| `software_id` | bytes | Software identifier |
| `package_id` | bytes | Package identifier |
| `slot1_talkgroups` | set \| None | Allowed 3-byte TGIDs on TS1; `None` = no restriction, empty set = deny all |
| `slot2_talkgroups` | set \| None | Same for TS2 |

Metadata fields are raw protocol `bytes`, not `str`. See `hblink4/models.py` for the complete definition.

#### Accessing repeater states

```python
# Access repeater by ID (keys are bytes)
repeater = protocol._repeaters[repeater_id]

# Iterate all connections
for repeater_id, repeater in protocol._repeaters.items():
    print(f"Repeater {int.from_bytes(repeater_id, 'big')}:")
    print(f"  State: {repeater.connection_state}")
    print(f"  Address: {repeater.ip}:{repeater.port}")
```

## Integrating with Your Application

### Complete application example

```python
#!/usr/bin/env python3
import asyncio
import json
import sys

from hblink4.hblink import HBProtocol, CONFIG


class MyDMRApplication:
    def __init__(self, config_file: str):
        self.load_config(config_file)
        self.transports = []
        self.protocols = []

    def load_config(self, config_file: str):
        """Load the HBlink configuration file"""
        try:
            with open(config_file, 'r') as f:
                CONFIG.update(json.load(f))
        except Exception as e:
            print(f"Error loading config: {e}")
            sys.exit(1)

    async def start(self):
        loop = asyncio.get_running_loop()
        g = CONFIG['global']

        # Dual-stack UDP listeners. Each endpoint gets its own protocol instance.
        if g.get('bind_ipv4'):
            protocol = HBProtocol()
            transport, _ = await loop.create_datagram_endpoint(
                lambda: protocol,
                local_addr=(g['bind_ipv4'], g.get('port_ipv4', 62031))
            )
            self.transports.append(transport)
            self.protocols.append(protocol)

        if g.get('bind_ipv6') and not g.get('disable_ipv6', False):
            protocol = HBProtocol()
            transport, _ = await loop.create_datagram_endpoint(
                lambda: protocol,
                local_addr=(g['bind_ipv6'], g.get('port_ipv6', 62031))
            )
            self.transports.append(transport)
            self.protocols.append(protocol)

        # Periodic status check alongside the protocol's own tasks
        asyncio.create_task(self.status_loop())

        # Run until cancelled (Ctrl-C raises KeyboardInterrupt in asyncio.run)
        await asyncio.Event().wait()

    async def status_loop(self):
        while True:
            await asyncio.sleep(60)
            for protocol in self.protocols:
                for repeater_id, repeater in protocol._repeaters.items():
                    if repeater.connection_state == 'connected':
                        self.handle_active_repeater(repeater_id, repeater)

    def handle_active_repeater(self, repeater_id: bytes, repeater):
        print(f"Active repeater {int.from_bytes(repeater_id, 'big')}:")
        print(f"  Last ping: {repeater.last_ping}")
        print(f"  Description: {repeater.description.decode('utf-8', errors='ignore')}")

    def shutdown(self):
        """Send disconnect messages and close sockets"""
        for protocol in self.protocols:
            protocol.cleanup()
        for transport in self.transports:
            transport.close()


def main():
    if len(sys.argv) != 2:
        print("Usage: mydmr.py /path/to/config.json")
        sys.exit(1)

    app = MyDMRApplication(sys.argv[1])
    try:
        asyncio.run(app.start())
    except KeyboardInterrupt:
        app.shutdown()


if __name__ == '__main__':
    main()
```

### Event hooks

To be notified of protocol events, subclass `HBProtocol` and override the handler you need, calling `super()` so normal processing still happens. The handlers are internal (underscore-prefixed) — check the signatures in `hblink4/hblink.py` against the version you are building on, as they are not a stable public API.

```python
class MyHBProtocol(HBProtocol):
    def datagram_received(self, data: bytes, addr: tuple):
        """Every inbound packet, before dispatch"""
        super().datagram_received(data, addr)

    def _handle_config(self, data: bytes, addr):
        """Repeater finished sending its configuration"""
        super()._handle_config(data, addr)
        # Custom post-connection handling here
```

Useful override points include `datagram_received`, `_handle_repeater_login`, `_handle_config`, `_handle_options`, `_handle_ping`, and `_handle_disconnect`.

## Common Integration Tasks

### Getting connected repeater count
```python
connected_count = sum(1 for r in protocol._repeaters.values()
                      if r.connection_state == 'connected')
```

### Finding a repeater by IP
```python
def find_repeater_by_ip(protocol, ip_address: str):
    for repeater in protocol._repeaters.values():
        if repeater.ip == ip_address:
            return repeater
    return None
```

### Monitoring connection states
```python
def get_repeater_states(protocol):
    states = {'connected': [], 'config': [], 'login': []}
    for repeater_id, repeater in protocol._repeaters.items():
        states[repeater.connection_state].append(int.from_bytes(repeater_id, 'big'))
    return states
```

## Best Practices

1. **Read-Only Access**: Avoid directly modifying the `_repeaters` dictionary or repeater states. Use protocol methods to interact with repeaters.

2. **State Handling**: Always check `connection_state == 'connected'` before acting on a repeater.

3. **Error Handling**: Wrap repeater access in try/except — repeaters may disconnect at any time.

4. **Event-Driven**: Prefer the override points above to polling.

5. **Single-Threaded**: HBlink4 runs on one asyncio event loop and its state is not protected by locks. From another thread, use `loop.call_soon_threadsafe()`; never touch protocol state directly.

6. **Don't Block**: Handlers run on the event loop. Anything slow must be dispatched with `asyncio.create_task()` or run in an executor, or it will stall packet processing for every repeater.

## Limitations

1. Routing rules are set by configuration before startup unless you subclass the handlers
2. Some repeater metadata may contain non-UTF8 characters
3. Radio IDs are handled as raw bytes — convert to int for display/logging

## Graceful Shutdown

1. Call `protocol.cleanup()` on each protocol to send disconnect messages
2. Close each transport
3. Allow the loop a moment to flush before exiting
