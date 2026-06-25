"""Reverse-engineered encoding for Omada radio settings.

Verified empirically against an OC200 (controller 5.14.x). The controller does
not use channel *numbers* in the API — it uses an *index* into the region's
channel list — and channel width is a small enum. ``channelRange`` (a list of
20 MHz center frequencies) must agree with the width or the AP widens the
operating block on its own.
"""

# 5 GHz channels in region order. The API "channel" value is the 1-based index
# into this list (index 1 == channel 36, 5 == 52, 9 == 100, 13 == 116, ...).
FIVE_G_CHANNELS = [36, 40, 44, 48, 52, 56, 60, 64,
                   100, 104, 108, 112, 116, 120, 124, 128,
                   132, 136, 140, 144]

# DFS channels (require radar detection; capability is per-AP-model).
NON_DFS_5G = {36, 40, 44, 48}
DFS_5G = set(FIVE_G_CHANNELS) - NON_DFS_5G

# channelWidth enum
WIDTH_CODE = {20: "2", 40: "3", 80: "5", 160: "6"}
CODE_WIDTH = {v: k for k, v in WIDTH_CODE.items()}

# 2.4 GHz channel is a literal number string ("1".."13", "0" == auto).
TWO_G_CHANNELS = list(range(1, 14))    # 1..13
TWO_G_WIDTHS = {20: "2", 40: "3"}      # no 80 MHz on 2.4


def band_of_channel(ch):
    """Infer band from a channel number: <=14 is 2.4 GHz, else 5 GHz."""
    return "2.4" if ch <= 14 else "5"


def validate_2g(ch, width):
    if ch not in TWO_G_CHANNELS:
        raise EncodingError(f"{ch} is not a valid 2.4GHz channel (1-13)")
    if width not in TWO_G_WIDTHS:
        raise EncodingError(f"2.4GHz supports 20 or 40 MHz, not {width}")

# Bonded blocks (lists of channels) used to build channelRange per width.
_BLOCKS = {
    40: [[36, 40], [44, 48], [52, 56], [60, 64], [100, 104], [108, 112],
         [116, 120], [124, 128], [132, 136], [140, 144]],
    80: [[36, 40, 44, 48], [52, 56, 60, 64], [100, 104, 108, 112],
         [116, 120, 124, 128], [132, 136, 140, 144]],
    160: [[36, 40, 44, 48, 52, 56, 60, 64],
          [100, 104, 108, 112, 116, 120, 124, 128]],
}


class EncodingError(ValueError):
    pass


def chan_to_freq(ch):
    """5 GHz channel number -> center frequency in MHz."""
    return 5000 + 5 * ch


def channel_index(ch):
    """5 GHz channel number -> API index string."""
    try:
        return str(FIVE_G_CHANNELS.index(ch) + 1)
    except ValueError:
        raise EncodingError(f"{ch} is not a known 5GHz channel")


def index_to_channel(idx):
    """API index -> 5 GHz channel number (best effort)."""
    try:
        return FIVE_G_CHANNELS[int(idx) - 1]
    except (ValueError, IndexError, TypeError):
        return None


def channel_range(ch, width):
    """Center-freq list the API expects for a 5 GHz channel at a given width."""
    if width == 20:
        return [chan_to_freq(ch)]
    if width not in _BLOCKS:
        raise EncodingError(f"unsupported width {width}")
    for block in _BLOCKS[width]:
        if ch in block:
            return [chan_to_freq(c) for c in block]
    raise EncodingError(f"channel {ch} has no valid {width}MHz block")


def width_code(width):
    if width not in WIDTH_CODE:
        raise EncodingError(f"unsupported width {width}")
    return WIDTH_CODE[width]


def describe_5g(radio):
    """Human label for a radioSetting5g dict, e.g. 'ch100/80MHz'."""
    ch = index_to_channel(radio.get("channel"))
    w = CODE_WIDTH.get(radio.get("channelWidth"), "?")
    return f"ch{ch}/{w}MHz"


def is_dfs(ch):
    return ch in DFS_5G
