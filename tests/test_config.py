from pathlib import Path
import pytest
from pymail_client.config import AppConfig, load_config, save_config


def test_defaults_match_spec(tmp_path: Path) -> None:
    cfg = AppConfig()
    assert cfg.undo_send_delay_s == 10  # RF-SET-02
    assert cfg.poll_interval_s == 60  # RF-MSG-05
    assert cfg.body_cache_limit_bytes == 500 * 1024 * 1024  # RF-MSG-06
    assert cfg.mark_read_delay_ms == 1500  # RF-RD-09
    assert cfg.search_debounce_ms == 250  # RF-SRCH-02
    assert cfg.use_idle is True  # RF-SET-02
    assert cfg.theme == "system"  # RF-UI-06


@pytest.mark.parametrize("value", [4, 31, 0, -5])
def test_undo_delay_out_of_range_rejected(value: int) -> None:
    """RF-SND-03: a janela é configurável entre 5 e 30 segundos."""
    with pytest.raises(ValueError):
        AppConfig(undo_send_delay_s=value)


def test_roundtrip_preserves_values(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    save_config(AppConfig(undo_send_delay_s=20), path)
    assert load_config(path).undo_send_delay_s == 20


def test_missing_file_yields_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path / "nao-existe.toml") == AppConfig()
