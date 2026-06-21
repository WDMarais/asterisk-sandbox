import importlib.util
import sys
from pathlib import Path

import pytest

# gen_pjsip lives in scripts/ (not a package); load it by path. It must be in
# sys.modules before exec for dataclass + `from __future__ import annotations`.
_spec = importlib.util.spec_from_file_location(
    "gen_pjsip", Path(__file__).parent.parent / "scripts" / "gen_pjsip.py"
)
gen_pjsip = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gen_pjsip
_spec.loader.exec_module(gen_pjsip)

ENV = {"DOMAIN": "pbx.example.com", "SIP_PASS_01": "p1", "SIP_PASS_02": "p2", "SIP_PASS_03": "p3"}


def render():
    return gen_pjsip.render(gen_pjsip.ENDPOINTS, ENV)


class TestRender:
    def test_has_both_transports(self):
        out = render()
        assert "[transport-udp]" in out
        assert "[transport-ws]" in out
        assert "protocol=ws" in out

    def test_external_address_from_domain(self):
        assert "external_media_address=pbx.example.com" in render()

    def test_external_address_omitted_without_domain(self):
        out = gen_pjsip.render(gen_pjsip.ENDPOINTS, {**ENV, "DOMAIN": ""})
        assert "external_media_address" not in out

    def test_udp_endpoint(self):
        out = render()
        assert "[6001]\ntype=endpoint" in out
        assert "rtp_symmetric=yes" in out
        assert "password=p1" in out

    def test_webrtc_endpoint(self):
        out = render()
        assert "webrtc=yes" in out
        assert "dtls_auto_generate_cert=yes" in out
        assert "password=p3" in out

    def test_missing_password_raises(self):
        with pytest.raises(SystemExit):
            gen_pjsip.render(gen_pjsip.ENDPOINTS, {**ENV, "SIP_PASS_03": ""})

    def test_every_endpoint_has_auth_and_aor(self):
        out = render()
        for n in ("6001", "6002", "6003"):
            assert f"[auth{n}]" in out
            assert f"[{n}]\ntype=aor" in out
