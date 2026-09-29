# DMR access checks and origin limits

## What HBlink4 checks

Inbound peers must pass the configured repeater allowlist and answer the
HomeBrew `RPTK` challenge with the configured passphrase. HBlink4 then requires
the protocol state sequence (`login` → `config` → `connected`) and binds later
packets to the source IP and UDP port of that authenticated session. DMR data
is accepted only for a connected session, and the configured timeslot and
talkgroup policy controls routing. A reconnect for an ID already in use from a
different address must prove the passphrase before it can take over.

`RPTK` uses the protocol's SHA-256 challenge construction, not a device
certificate or a per-device key. Because it is a fast hash of a transmitted
challenge and the shared passphrase, a captured exchange can be used for
offline guesses if that passphrase is weak. Use a randomly generated, high
entropy passphrase and distribute it privately. Do not publish or place the
credential in Git, browser UI, or audit records. The protocol does not encrypt
the session or attach a per-packet MAC to inbound DMRD frames.

HBlink4 now also requires the fixed 302-byte `RPTC` configuration packet before
it marks a session connected. A malformed configuration from the owning,
authenticated session is rejected and that session is removed. A malformed
packet from another address cannot remove the registered session.

These are access and protocol-framing checks. They do not attest that a packet
was created by a physical radio or modem.

An authenticated login for an already-registered repeater ID can replace the
incumbent session after a correct `RPTK`, before the replacement sends a valid
`RPTC`. A malformed `RPTC` is rejected and removes the claimant session, but
the framing check does not restore an incumbent already displaced after valid
credentials. This remains an operational denial-of-service risk for anyone
who knows that ID's passphrase; the check is not hardware attestation or a
credential-holder DoS guarantee.

## What the protocol reveals

The upstream MMDVM client implementation sends `RPTL` with a 4-byte repeater
ID, then computes `RPTK` as SHA-256 of the server challenge followed by its
configured passphrase. It sends `RPTC` configuration and optional `RPTO`
talkgroup options, and sends `RPTPING` keepalives. The HBP `DMRD` packet carries
source and destination IDs, repeater ID, slot and stream data. DMRGateway's
network code forwards the configured RPTC payload length and parses DMRD routing
fields; the 302-byte requirement enforced here follows this project's HBP wire
layout. See the [MMDVM-Host DMR network implementation](https://github.com/g4klx/MMDVM-Host/blob/master/DMRNetwork.cpp)
and the [DMRGateway DMR network implementation](https://github.com/g4klx/DMRGateway/blob/master/DMRNetwork.cpp).

WPSD uses MMDVMHost as its core modem/RF layer and configures an MMDVM modem
through that host. Its documentation describes the host and modem as separate
parts of a hotspot and documents MMDVMHost/DMRGateway configuration. Neither
that software path nor HBP provides a cryptographic modem identity. See the
[WPSD overview](https://manual.wpsd.radio/get_started/), [WPSD DMR guide](https://manual.wpsd.radio/modes/dmr/),
and [WPSD DMRGateway guide](https://manual.wpsd.radio/advanced/dmrgateway/).

## Signal classification

The shared passphrase and its captured challenge/response are sensitive
authentication material. Repeater IDs, packet addresses, DMRD IDs and RPTC
metadata are operational data: the server needs them for routing, session
binding or diagnostics, but they are not hardware credentials. Callsigns and
public aggregate status are suitable for the public dashboard only after the
server projects them into its fixed, sanitized DTO. Raw event payloads,
configuration, source addresses, ESSIDs, IDs, locations and credentials stay
server-side.

| Signal | What it can establish | Limitation |
| --- | --- | --- |
| Allowlisted repeater ID / ESSID | The claimed ID is in an administrator-managed range | The ID is present in packet fields and can be copied |
| `RPTK` response | The sender knew the shared passphrase for the challenge | It authenticates credentials, not the physical device; the current passphrase is shared |
| Handshake state | The peer followed the required protocol order | Any compatible implementation can follow that order |
| Source IP and UDP port | Later packets match the address tuple that completed login | It is session binding, not device identity; NAT and network access matter, and UDP packets are not individually authenticated |
| `RPTC` callsign, location, software and package fields | Client-provided descriptive metadata for display/diagnostics | All fields are self-reported and can be forged |
| `RPTO` and `RPTPING` | Requested talkgroups and session liveness | They do not identify hardware |
| `DMRD` IDs, slot, talkgroup and stream fields | Routing information used by HBlink4 policy | The fields are not signed by a device-specific key |

There is no reliable HBP fingerprint for a physical hotspot. A software client
that knows an allowed ID and passphrase can implement the same handshake,
declare WPSD/MMDVM metadata, bind its own UDP session and send DMRD frames. A
source-IP allowlist could narrow access only when operators have stable,
known addresses; it would break roaming/NAT clients and still would not prove a
physical modem. No software-name or packet-timing rule is used as an attestation
check.

## Public status

The Admin page labels the existing DMR checks `Ativos` to describe the actual
allowlist, challenge, session/address/state and talkgroup enforcement. It does
not claim that apps or software can be blocked absolutely. The current operator
allowlist, shared passphrase, TS1/TS2 and TG100/TG4100 policy remain authoritative.
