import json
import urllib.error
import urllib.request

import pytest

from omada_cli.client import OmadaClient, OmadaError


class FakeResp:
    def __init__(self, payload, cookie=None):
        self._b = json.dumps(payload).encode()
        self.headers = {"Set-Cookie": cookie} if cookie else {}

    def read(self):
        return self._b


def make_urlopen(routes, calls=None):
    """routes: list of (url_substring, method, response_payload, cookie)."""
    def fake(req, context=None, timeout=None):
        url = req.full_url
        method = req.get_method()
        if calls is not None:
            calls.append((method, url, req.data))
        for sub, m, payload, cookie in routes:
            if sub in url and (m is None or m == method):
                return FakeResp(payload, cookie)
        raise AssertionError(f"no route for {method} {url}")
    return fake


@pytest.fixture
def patch_urlopen(monkeypatch):
    def _apply(routes, calls=None):
        monkeypatch.setattr(urllib.request, "urlopen", make_urlopen(routes, calls))
    return _apply


def test_connect_with_explicit_cid_and_site_name(patch_urlopen):
    patch_urlopen([
        ("/login", "POST", {"errorCode": 0, "result": {"token": "T"}}, "id=abc; Path=/"),
        ("/sites?", "GET", {"errorCode": 0, "result": {"data": [
            {"name": "Default", "id": "f" * 24}]}}, None),
    ])
    c = OmadaClient("https://x", "u", "p", controller_id="CID", site="Default").connect()
    assert c.token == "T"
    assert c.site_id == "f" * 24
    assert c.cookie == "id=abc"


def test_site_id_passthrough_when_hex(patch_urlopen):
    patch_urlopen([
        ("/login", "POST", {"errorCode": 0, "result": {"token": "T"}}, None),
    ])
    c = OmadaClient("https://x", "u", "p", controller_id="CID", site="a" * 24).connect()
    assert c.site_id == "a" * 24  # no /sites lookup needed


def test_cid_autodiscovery(patch_urlopen):
    patch_urlopen([
        ("/api/info", "GET", {"errorCode": 0, "result": {"omadacId": "DISCOVERED"}}, None),
        ("/login", "POST", {"errorCode": 0, "result": {"token": "T"}}, None),
        ("/sites?", "GET", {"errorCode": 0, "result": {"data": [
            {"name": "Default", "id": "0" * 24}]}}, None),
    ])
    c = OmadaClient("https://x", "u", "p", controller_id=None, site="Default").connect()
    assert c.cid == "DISCOVERED"


def test_site_not_found(patch_urlopen):
    patch_urlopen([
        ("/login", "POST", {"errorCode": 0, "result": {"token": "T"}}, None),
        ("/sites?", "GET", {"errorCode": 0, "result": {"data": []}}, None),
    ])
    with pytest.raises(OmadaError):
        OmadaClient("https://x", "u", "p", controller_id="CID", site="Nope").connect()


def test_api_error_code_raises(patch_urlopen):
    patch_urlopen([
        ("/login", "POST", {"errorCode": 0, "result": {"token": "T"}}, None),
        ("/sites?", "GET", {"errorCode": 0, "result": {"data": [
            {"name": "Default", "id": "0" * 24}]}}, None),
        ("/devices", "GET", {"errorCode": -1, "msg": "boom"}, None),
    ])
    c = OmadaClient("https://x", "u", "p", controller_id="CID", site="Default").connect()
    with pytest.raises(OmadaError, match="boom"):
        c.devices()


def test_http_error_raises(monkeypatch):
    def boom(req, context=None, timeout=None):
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(OmadaError, match="cannot reach"):
        OmadaClient("https://x", "u", "p", controller_id="CID").connect()


def test_dry_run_patch_skips_http(patch_urlopen, capsys):
    patch_urlopen([
        ("/login", "POST", {"errorCode": 0, "result": {"token": "T"}}, None),
        ("/sites?", "GET", {"errorCode": 0, "result": {"data": [
            {"name": "Default", "id": "0" * 24}]}}, None),
    ])
    c = OmadaClient("https://x", "u", "p", controller_id="CID", site="Default",
                    dry_run=True).connect()
    res = c.patch("/eaps/MAC", {"x": 1})
    assert res == {"_dry_run": True}
    assert "[dry-run]" in capsys.readouterr().out


def test_paginate_collects_all_pages(monkeypatch):
    def fake(req, context=None, timeout=None):
        url = req.full_url
        if "/login" in url:
            return FakeResp({"errorCode": 0, "result": {"token": "T"}})
        if "/sites?" in url:
            return FakeResp({"errorCode": 0, "result": {"data": [
                {"name": "Default", "id": "0" * 24}]}})
        if "currentPage=1" in url:
            return FakeResp({"errorCode": 0, "result": {"totalRows": 3, "data": [{"i": 1}, {"i": 2}]}})
        return FakeResp({"errorCode": 0, "result": {"totalRows": 3, "data": [{"i": 3}]}})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    c = OmadaClient("https://x", "u", "p", controller_id="CID", site="Default").connect()
    rows = c.paginate("/clients", page_size=2)
    assert [r["i"] for r in rows] == [1, 2, 3]


def test_convenience_methods_smoke(monkeypatch):
    def fake(req, context=None, timeout=None):
        url = req.full_url
        if "/login" in url:
            return FakeResp({"errorCode": 0, "result": {"token": "T"}})
        if "/sites?" in url:
            return FakeResp({"errorCode": 0, "result": {"data": [
                {"name": "Default", "id": "0" * 24}]}})
        if "/maintenance/controllerStatus" in url:
            return FakeResp({"errorCode": 0, "result": {"model": "OC200"}})
        if "/dashboard/overviewDiagram" in url:
            return FakeResp({"errorCode": 0, "result": {"totalApNum": 5}})
        return FakeResp({"errorCode": 0, "result": {"data": [], "totalRows": 0}})
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    c = OmadaClient("https://x", "u", "p", controller_id="CID", site="Default").connect()
    assert c.controller_status()["model"] == "OC200"
    assert c.overview()["totalApNum"] == 5
    assert c.devices() == {"data": [], "totalRows": 0}
    assert c.eap("MAC") == {"data": [], "totalRows": 0}
    assert c.clients() == [] and c.known_clients() == []
    assert c.setting() == {"data": [], "totalRows": 0}
    assert c.wlan_groups() == [] and c.ssids("g") == []
    assert c.lan_networks() == [] and c.alerts() == [] and c.events() == []
    # writes
    assert c.eap_patch("MAC", {"k": 1}) == {"data": [], "totalRows": 0}
    assert c.setting_patch({"k": 1}) == {"data": [], "totalRows": 0}
    assert c.ssid_patch("g", "s", {"k": 1}) == {"data": [], "totalRows": 0}
    assert c.post("/x", {"k": 1}) == {"data": [], "totalRows": 0}
