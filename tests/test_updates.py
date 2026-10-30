import hashlib
import io
import json

import pytest

from lume.core import updates

PAYLOAD = b"x" * 1000


def release_json(tag="v0.2.0", payload=PAYLOAD, digest=True, **extra):
    asset = {
        "name": f"Lume-Setup-{tag.lstrip('v')}.exe",
        "browser_download_url": "https://example.invalid/setup.exe",
        "size": len(payload),
    }
    if digest:
        asset["digest"] = "sha256:" + hashlib.sha256(payload).hexdigest()
    data = {"tag_name": tag, "body": "Novidades", "html_url": "https://example.invalid/r",
            "assets": [{"name": "outro.zip"}, asset]}
    data.update(extra)
    return data


class FakeResponse(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def opener_for(body: bytes):
    return lambda req, timeout=None: FakeResponse(body)


def test_version_comparison():
    assert updates.is_newer("0.2.0", "0.1.0")
    assert updates.is_newer("v0.10.0", "0.9.9")
    assert not updates.is_newer("0.1.0", "0.1.0")
    assert not updates.is_newer("lixo", "0.1.0")
    assert updates.parse_version("v1.2") == (1, 2, 0)


def test_parse_release_picks_installer_and_digest():
    rel = updates.parse_release(release_json())
    assert rel.version == "0.2.0" and rel.asset_name == "Lume-Setup-0.2.0.exe"
    assert rel.sha256 == hashlib.sha256(PAYLOAD).hexdigest()


def test_prerelease_and_bad_payload_are_rejected():
    with pytest.raises(updates.UpdateError):
        updates.parse_release(release_json(prerelease=True))
    with pytest.raises(updates.UpdateError):
        updates.parse_release({"oi": 1})


def test_fetch_latest_uses_opener():
    rel = updates.fetch_latest(opener=opener_for(json.dumps(release_json()).encode()))
    assert rel.version == "0.2.0"


def test_fetch_latest_wraps_network_errors():
    def boom(req, timeout=None):
        raise OSError("sem rede")

    with pytest.raises(updates.UpdateError, match="sem rede"):
        updates.fetch_latest(opener=boom)


def test_download_verifies_hash(tmp_path):
    rel = updates.parse_release(release_json())
    seen = []
    path = updates.download(rel, tmp_path, lambda d, t: seen.append((d, t)), opener=opener_for(PAYLOAD))
    assert path.read_bytes() == PAYLOAD and seen[-1] == (1000, 1000)


def test_download_rejects_tampered_file(tmp_path):
    rel = updates.parse_release(release_json())
    with pytest.raises(updates.UpdateError, match="SHA"):
        updates.download(rel, tmp_path, opener=opener_for(b"y" * 1000))
    assert not list(tmp_path.iterdir())  # nada fica para trás


def test_download_rejects_truncated_file(tmp_path):
    rel = updates.parse_release(release_json(digest=False))
    with pytest.raises(updates.UpdateError, match="incompleto"):
        updates.download(rel, tmp_path, opener=opener_for(PAYLOAD[:10]))


def test_installer_command_is_silent_and_relaunches(tmp_path):
    cmd = " ".join(updates.installer_command(tmp_path / "Lume-Setup.exe"))
    assert "/SILENT" in cmd and "/RELAUNCH" in cmd
