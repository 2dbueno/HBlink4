"""
Protocol and system constants
"""

# HomeBrew Protocol Constants — full commands as they appear on the wire
DMRD    = b'DMRD'
MSTCL   = b'MSTCL'    # Server shutdown notice (sent bare, no repeater ID)
MSTNAK  = b'MSTNAK'
MSTPONG = b'MSTPONG'  # Server response to repeater's RPTPING/RPTP
RPTL    = b'RPTL'
RPTK    = b'RPTK'
RPTC    = b'RPTC'
RPTACK  = b'RPTACK'
RPTCL   = b'RPTCL'
RPTPING = b'RPTPING'  # Full command sent by repeater for keepalive
RPTO    = b'RPTO'     # Repeater sending Options
DMRA    = b'DMRA'     # DMR Talker Alias

# Four-byte command prefixes.
#
# Every HBP command can be identified from its first four bytes, so a receiver
# may slice a fixed 4-byte field and branch on that before comparing the full
# command. These are the prefixes of commands whose full form is longer than
# four bytes.
#
# HBlink4 uses RPTP this way (RPTPING is the only command starting 'RPTP', so
# the prefix alone identifies it). The rest are not needed here — this codebase
# compares the full command for those — but they are part of the shared
# constants vocabulary and other software using this module may match on them.
# They are kept here for legacy purposes.
#
# Prefix matching is not sufficient everywhere: 'RPTC' is shared by RPTC and
# RPTCL, so a receiver must check five bytes to tell configuration from close.
RPTP    = b'RPTP'     # RPTPING
RPTA    = b'RPTA'     # RPTACK
MSTN    = b'MSTN'     # MSTNAK
MSTC    = b'MSTC'     # MSTCL

# Protocol Configuration
DMR_DATA_PACKET_LENGTH = 55  # Minimum length of valid DMR data packet
DMR_PORT = 62031  # Default HomeBrew DMR port
DEFAULT_PING_TIME = 5.0  # Default ping interval in seconds
MAX_MISSED_PINGS = 3  # Maximum number of missed pings before disconnect
PENDING_LOGIN_TIMEOUT = 30.0  # Seconds a login challenging an already-registered ID may go unanswered

# DMR Sync Patterns (48 bits / 6 bytes)
# These patterns appear in the DMR payload at bytes 20-25 to identify frame types
# Used to distinguish between voice headers, terminators, and data frames

# Voice sync patterns (Base Station sourced)
DMR_SYNC_VOICE_HEADER = bytes.fromhex('755FD7DF75F7')    # Voice header with LC
DMR_SYNC_VOICE_TERM = bytes.fromhex('D5DD7DF75D55')      # Voice terminator with LC

# Data sync patterns (Base Station sourced)
DMR_SYNC_DATA_HEADER = bytes.fromhex('DFF57D75DF5D')     # Data header
DMR_SYNC_DATA_TERM = bytes.fromhex('7DFFD5F55D5F')       # Data terminator

# Mobile Station sourced patterns (less common in repeater systems)
DMR_SYNC_MS_VOICE_HEADER = bytes.fromhex('D5D7F77FD757')
DMR_SYNC_MS_VOICE_TERM = bytes.fromhex('77D57DD577F5')
DMR_SYNC_MS_DATA_HEADER = bytes.fromhex('7F7D5DD57DFD')
DMR_SYNC_MS_DATA_TERM = bytes.fromhex('55D5FDD755DF')
