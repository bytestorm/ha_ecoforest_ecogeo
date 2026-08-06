"""Tests for derived delta-T values."""

import importlib.util
import pathlib
import sys

_base = (
    pathlib.Path(__file__).parent.parent / "custom_components" / "ecoforest_ecogeo"
)


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_load(_base / "overrides" / "device.py",
      "custom_components.ecoforest_ecogeo.overrides.device")
api_mod = _load(_base / "overrides" / "api.py",
                "custom_components.ecoforest_ecogeo.overrides.api")

apply_derived = api_mod.apply_derived
DERIVED_KEYS = api_mod.DERIVED_KEYS
MAPPING = api_mod.MAPPING
_efficiency = api_mod._efficiency


def test_all_derived_keys_are_mapped() -> None:
    for key in DERIVED_KEYS:
        assert MAPPING[key]["entity_type"] == "temperature_delta"
        assert MAPPING[key]["type"] == "derived"
        assert MAPPING[key].get("address") is None


def test_brine_delta_is_supply_minus_return() -> None:
    info = {"t_brine_supply": 24.2, "t_brine_return": 21.3}
    apply_derived(info)
    assert info["t_brine_delta"] == 2.9


def test_production_delta_is_supply_minus_return() -> None:
    """Cooling makes the load-side supply colder than the return."""
    info = {"t_production_supply": 7.7, "t_production_return": 10.6}
    apply_derived(info)
    assert info["t_production_delta"] == -2.9


def test_delta_is_none_when_a_reading_is_missing() -> None:
    info = {"t_brine_supply": 24.2, "t_brine_return": None}
    apply_derived(info)
    assert info["t_brine_delta"] is None


def test_buffer_error_uses_heating_setpoint_when_heating() -> None:
    info = {
        "switch_heating": True,
        "switch_cooling": False,
        "t_heating": 28.0,
        "t_heating_setpoint": 30.0,
        "t_cooling_setpoint": 7.2,
    }
    apply_derived(info)
    assert info["t_buffer_error"] == -2.0


def test_buffer_error_uses_cooling_setpoint_when_cooling() -> None:
    info = {
        "switch_heating": False,
        "switch_cooling": True,
        "t_heating": 9.5,
        "t_heating_setpoint": 30.0,
        "t_cooling_setpoint": 7.2,
    }
    apply_derived(info)
    assert info["t_buffer_error"] == 2.3


def test_buffer_error_is_none_when_idle() -> None:
    info = {
        "switch_heating": False,
        "switch_cooling": False,
        "t_heating": 9.5,
        "t_heating_setpoint": 30.0,
        "t_cooling_setpoint": 7.2,
    }
    apply_derived(info)
    assert info["t_buffer_error"] is None


def test_derived_keys_are_always_present() -> None:
    """Even with no source data at all, every key is set rather than absent."""
    info: dict[str, object] = {}
    apply_derived(info)
    for key in DERIVED_KEYS:
        assert key in info
        assert info[key] is None


def test_efficiency_is_none_when_that_mode_is_idle() -> None:
    """Cooling means no heating COP — not a COP of zero."""
    assert api_mod._efficiency(0, 1000) is None


def test_efficiency_is_none_when_the_compressor_is_off() -> None:
    assert api_mod._efficiency(None, None) is None
    assert api_mod._efficiency(6300, 0) is None


def test_efficiency_computes_the_ratio_when_running() -> None:
    assert api_mod._efficiency(6300, 1000) == 6.3


def test_efficiency_rounds_to_two_places() -> None:
    assert api_mod._efficiency(6350, 1017) == 6.24
