"""Regression tests for the HomeBrew RPTC wire framing and session checks."""

import pytest

from hblink4 import hblink as hblink_mod
from hblink4.constants import MSTNAK
from hblink4.hblink import HBProtocol
from hblink4.models import RepeaterState


RADIO_ID = b"\x00\x04\xc2\xc0"
OWNER = ("198.51.100.10", 62031)
OTHER_ADDRESS = ("203.0.113.55", 54001)
PASSPHRASE = "rptc-framing-test-key"

CONFIG = {
    "global": {"user_cache": {"timeout": 600}},
    "dashboard": {"enabled": False},
    "repeater_configurations": {
        "patterns": [{
            "name": "RPTC test network",
            "match": {"id_ranges": [[312000, 312999]]},
            "config": {
                "passphrase": PASSPHRASE,
                "trust": False,
                "slot1_talkgroups": [],
                "slot2_talkgroups": [100],
            },
        }]
    },
}


class FakeTransport:
    def __init__(self):
        self.sent = []

    def sendto(self, data, addr=None):
        self.sent.append((data, addr))


@pytest.fixture
def hb_protocol(monkeypatch):
    monkeypatch.setattr(hblink_mod, "CONFIG", CONFIG)
    protocol = HBProtocol()
    protocol.transport = FakeTransport()
    return protocol


def make_rptc(length=302):
    """Return the fixed RPTC fields padded to the requested wire length."""
    fixed = b"RPTC" + RADIO_ID + b"W1AW    "
    return fixed + (b" " * (length - len(fixed)))


def install_config_session(protocol, address=OWNER, *, authenticated=True,
                           connection_state="config", connected=False):
    state = RepeaterState(repeater_id=RADIO_ID, ip=address[0], port=address[1])
    state.authenticated = authenticated
    state.connection_state = connection_state
    state.connected = connected
    protocol._repeaters[RADIO_ID] = state
    return state


@pytest.mark.parametrize("length", [301, 303])
def test_authenticated_rptc_with_wrong_length_is_nak_and_removed(hb_protocol, length):
    state = install_config_session(hb_protocol)

    hb_protocol._handle_config(make_rptc(length), OWNER)

    assert RADIO_ID not in hb_protocol._repeaters
    assert state.connection_state == "config"
    assert hb_protocol.transport.sent[-1] == (MSTNAK + RADIO_ID, OWNER)


def test_authenticated_rptc_of_exactly_302_bytes_connects(hb_protocol):
    state = install_config_session(hb_protocol)
    packet = make_rptc(302)

    hb_protocol._handle_config(packet, OWNER)

    assert len(packet) == 302
    assert hb_protocol._repeaters[RADIO_ID] is state
    assert state.connection_state == "connected"
    assert state.connected is True
    assert state.callsign == b"W1AW    "
    assert state.package_id == packet[262:302]
    assert hb_protocol.transport.sent[-1] == (b"RPTACK" + RADIO_ID, OWNER)


def test_malformed_rptc_from_non_owner_preserves_incumbent(hb_protocol):
    incumbent = install_config_session(
        hb_protocol, authenticated=True, connection_state="connected", connected=True
    )
    incumbent.callsign = b"W1AW    "

    hb_protocol._handle_config(make_rptc(301), OTHER_ADDRESS)

    assert hb_protocol._repeaters[RADIO_ID] is incumbent
    assert incumbent.connection_state == "connected"
    assert incumbent.connected is True
    assert incumbent.callsign == b"W1AW    "
    assert hb_protocol.transport.sent[-1] == (MSTNAK + RADIO_ID, OTHER_ADDRESS)


def test_unauthenticated_rptc_cannot_connect_or_remove_session(hb_protocol):
    state = install_config_session(
        hb_protocol, authenticated=False, connection_state="login", connected=False
    )

    hb_protocol._handle_config(make_rptc(302), OWNER)

    assert hb_protocol._repeaters[RADIO_ID] is state
    assert state.connection_state == "login"
    assert state.connected is False
    assert state.callsign == b""
    assert hb_protocol.transport.sent[-1] == (MSTNAK + RADIO_ID, OWNER)


def test_authenticated_rptc_in_wrong_state_cannot_connect_or_remove_session(hb_protocol):
    state = install_config_session(
        hb_protocol, authenticated=True, connection_state="login", connected=False
    )

    hb_protocol._handle_config(make_rptc(302), OWNER)

    assert hb_protocol._repeaters[RADIO_ID] is state
    assert state.connection_state == "login"
    assert state.connected is False
    assert state.callsign == b""
    assert hb_protocol.transport.sent[-1] == (MSTNAK + RADIO_ID, OWNER)
