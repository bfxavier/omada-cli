from omada_cli import diagnostics


def _msgs(findings, area=None):
    return [m for s, a, m in findings if area is None or a == area]


def test_run_returns_findings(fake_client):
    findings = diagnostics.run(fake_client)
    assert findings
    assert all(len(f) == 3 for f in findings)


def test_firmware_mismatch_flagged(fake_client):
    findings = diagnostics.run(fake_client)
    fw = _msgs(findings, "firmware")
    # EAP655-Wall has 1.6.2 and 1.4.3; EAP620 HD has 1.0.3 and 1.6.1
    assert any("EAP655-Wall" in m and "mixed firmware" in m for m in fw)
    assert any("EAP620 HD" in m and "mixed firmware" in m for m in fw)


def test_needupgrade_info(fake_client):
    findings = diagnostics.run(fake_client)
    assert any("update available" in m for m in _msgs(findings, "firmware"))


def test_5g_cochannel_warns(fake_client):
    findings = diagnostics.run(fake_client)
    # Shed + Master both on 5G ch36
    warns = [m for s, a, m in findings if s == "warn" and a == "channels"]
    assert any("5G co-channel" in m and "ch36" in m for m in warns)


def test_2g_cochannel_is_info_not_warn(fake_client):
    findings = diagnostics.run(fake_client)
    twog = [(s, m) for s, a, m in findings if a == "channels" and "2.4" in m]
    assert twog and all(s == "info" for s, _ in twog)


def test_aggressive_roam_warns_from_eap_detail(fake_client):
    # Office has 5G kick -65 (> -72 floor) — read from per-EAP, not /devices
    findings = diagnostics.run(fake_client)
    roam = [m for s, a, m in findings if a == "roaming"]
    assert any("Office" in m and "-65" in m for m in roam)


def test_weak_client_info(fake_client):
    findings = diagnostics.run(fake_client)
    assert any("Sensor" in m for m in _msgs(findings, "clients"))


def test_mesh_off_no_warning(fake_client):
    findings = diagnostics.run(fake_client)
    assert not any("mesh" in a for s, a, m in findings)


def test_mesh_on_wired_warns(fake_client):
    fake_client._setting["mesh"]["meshEnable"] = True
    findings = diagnostics.run(fake_client)
    assert any(a == "mesh" and s == "warn" for s, a, m in findings)


def test_congestion_warns_on_high_rx(fake_client):
    fake_client._devices[0]["wp5g"]["rxUtil"] = 70
    findings = diagnostics.run(fake_client)
    assert any(a == "airtime" and "congested" in m for s, a, m in findings)
