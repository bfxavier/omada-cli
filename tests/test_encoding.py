import pytest

from omada_cli import encoding as e


@pytest.mark.parametrize("ch,idx", [(36, "1"), (44, "3"), (52, "5"),
                                    (100, "9"), (116, "13"), (132, "17"), (144, "20")])
def test_channel_index_roundtrip(ch, idx):
    assert e.channel_index(ch) == idx
    assert e.index_to_channel(idx) == ch


def test_channel_index_invalid():
    with pytest.raises(e.EncodingError):
        e.channel_index(37)


def test_index_to_channel_bad():
    assert e.index_to_channel("99") is None
    assert e.index_to_channel(None) is None


def test_chan_to_freq():
    assert e.chan_to_freq(36) == 5180
    assert e.chan_to_freq(100) == 5500


@pytest.mark.parametrize("ch,width,expected", [
    (36, 20, [5180]),
    (36, 40, [5180, 5200]),
    (44, 40, [5220, 5240]),
    (52, 80, [5260, 5280, 5300, 5320]),
    (100, 80, [5500, 5520, 5540, 5560]),
    (36, 160, [5180, 5200, 5220, 5240, 5260, 5280, 5300, 5320]),
])
def test_channel_range(ch, width, expected):
    assert e.channel_range(ch, width) == expected


def test_channel_range_bad_block():
    with pytest.raises(e.EncodingError):
        e.channel_range(149, 80)


def test_channel_range_bad_width():
    with pytest.raises(e.EncodingError):
        e.channel_range(36, 30)


@pytest.mark.parametrize("w,code", [(20, "2"), (40, "3"), (80, "5"), (160, "6")])
def test_width_code(w, code):
    assert e.width_code(w) == code
    assert e.CODE_WIDTH[code] == w


def test_width_code_bad():
    with pytest.raises(e.EncodingError):
        e.width_code(25)


def test_describe_5g():
    assert e.describe_5g({"channel": "9", "channelWidth": "5"}) == "ch100/80MHz"
    assert e.describe_5g({"channel": "99", "channelWidth": "x"}) == "chNone/?MHz"


def test_is_dfs():
    assert e.is_dfs(100) is True
    assert e.is_dfs(36) is False
