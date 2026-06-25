"""omada-cli — a command-line tool for tuning TP-Link Omada SDN wireless.

Talks to the controller's internal web API (the one the GUI uses) because the
official Omada Open API does not expose per-AP radio configuration — channel,
width, transmit power, or roaming/RSSI thresholds. Those operations are the
reason this tool exists.
"""

__version__ = "0.3.0"
