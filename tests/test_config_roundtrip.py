"""
Config write/load roundtrip: typed values survive, None is omitted (never a
literal `null` token), hostile strings escape cleanly, invalid TOML rejected.
"""
import pytest
import tomllib

from core.config import load_config, write_config, write_config_bootstrap

pytestmark = pytest.mark.core_only  # fast/offline core data-layer tests


def test_roundtrip_preserves_types_and_nesting(tmp_path):
    cfg = {
        "installation": {
            "install_dir": str(tmp_path / "inst"),
            "venv_dir": str(tmp_path / "inst" / "venv"),
            "data_dir": str(tmp_path / "data"),
            "logs_dir": str(tmp_path / "logs"),
            "photos_root": str(tmp_path / "photos"),
            "create_desktop_entry": True,
            "autostart": False,
        },
        "behavior": {
            "camera_index": 5,
            "width": 640,
            "height": 480,
            "image_format": "jpg",
            "quality": 77,
            "audit_enabled": False,
            "one_photo_per_day": True,
            "allow_retake": True,
            "timer_duration": 300,
            "motion_enabled": False,
        },
        "theme": {"name": "material-theme", "mode": "light", "contrast": "high"},
    }
    path = tmp_path / "config.toml"
    write_config(path, cfg)
    loaded = load_config(path)

    b = loaded["behavior"]
    assert isinstance(b["camera_index"], int) and b["camera_index"] == 5
    assert isinstance(b["quality"], int) and b["quality"] == 77
    assert isinstance(b["timer_duration"], int) and b["timer_duration"] == 300
    assert loaded["installation"]["create_desktop_entry"] is True
    assert loaded["installation"]["autostart"] is False
    assert b["one_photo_per_day"] is True
    assert isinstance(b["allow_retake"], bool) and b["allow_retake"] is True
    assert isinstance(b["motion_enabled"], bool) and b["motion_enabled"] is False
    assert b["image_format"] == "jpg"
    assert loaded["theme"] == {"name": "material-theme", "mode": "light", "contrast": "high"}


def test_none_width_height_omitted_not_null(tmp_path):
    from core.config import DEFAULT_CONFIG

    cfg = {
        "installation": dict(DEFAULT_CONFIG["installation"]),
        "behavior": {
            "camera_index": 0,
            "width": None,
            "height": None,
            "quality": 90,
            "image_format": "jpg",
        },
        "theme": dict(DEFAULT_CONFIG["theme"]),
    }
    path = tmp_path / "config.toml"
    write_config(path, cfg)

    raw = path.read_text(encoding="utf-8")
    assert "null" not in raw.lower()
    assert "width" not in raw and "height" not in raw

    loaded = load_config(path)
    assert isinstance(loaded["behavior"]["width"], int)
    assert isinstance(loaded["behavior"]["height"], int)


def test_bootstrap_writer_also_omits_none(tmp_path):
    from core.config import DEFAULT_CONFIG

    cfg = {
        "installation": dict(DEFAULT_CONFIG["installation"]),
        "behavior": {"camera_index": 2, "width": None, "height": None},
        "theme": dict(DEFAULT_CONFIG["theme"]),
    }
    path = tmp_path / "bootstrap.toml"
    write_config_bootstrap(path, cfg)
    raw = path.read_text(encoding="utf-8")
    assert "null" not in raw.lower()
    assert "width" not in raw
    loaded = load_config(path)
    assert loaded["behavior"]["camera_index"] == 2


def test_hostile_strings_survive_tomli_w_roundtrip(tmp_path):
    hostile = 'quote " back\\slash\nnewline\ttab end'
    cfg = {
        "installation": {},
        "behavior": {},
        "theme": {"name": hostile, "mode": "dark", "contrast": "standard"},
    }
    path = tmp_path / "hostile.toml"
    write_config(path, cfg)
    loaded = load_config(path)
    assert loaded["theme"]["name"] == hostile


def test_hostile_strings_survive_bootstrap_writer(tmp_path):
    hostile = 'say "hi" \\ ok\nsecond line'
    cfg = {
        "installation": {},
        "behavior": {},
        "theme": {"name": hostile, "mode": "dark", "contrast": "standard"},
    }
    path = tmp_path / "hostile-bootstrap.toml"
    write_config_bootstrap(path, cfg)
    parsed_directly = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed_directly["theme"]["name"] == hostile
    loaded = load_config(path)
    assert loaded["theme"]["name"] == hostile


def test_invalid_toml_rejected_cleanly(tmp_path):
    path = tmp_path / "broken.toml"
    path.write_text("this is [ definitely = not toml\n[unclosed", encoding="utf-8")
    with pytest.raises(tomllib.TOMLDecodeError):
        load_config(path)


def test_missing_file_returns_defaults_without_writing(tmp_path):
    path = tmp_path / "absent.toml"
    loaded = load_config(path)
    assert path.exists() is False
    assert loaded["behavior"]["quality"] >= 1
