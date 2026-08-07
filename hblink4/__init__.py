"""
HBlink4 - Next Generation DMR Server Protocol Handler

A complete architectural redesign of HBlink3, implementing a repeater-centric
approach to DMR server services. The HomeBrew DMR protocol is UDP-based, used for
communication between DMR repeaters and servers.

License: GNU GPLv3
"""

# Deliberately no re-exports here. Importing the package must not pull in
# hblink.py: when hblink.py is run directly it is already loaded as __main__,
# and re-importing it as hblink4.hblink yields a second, independent copy of
# every module in the package -- classes from the two copies are distinct
# objects and fail isinstance() against each other. Import submodules
# explicitly instead (from hblink4.hblink import HBProtocol).

__version__ = '4.8.0'
__author__ = 'Cort Buffington, N0MJS'
__license__ = 'GNU GPLv3'
