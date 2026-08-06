"""Tests for temperature-interval unit arithmetic."""

import importlib.util
import pathlib
import sys

_UNITS_PATH = (
    pathlib.Path(__file__).parent.parent
    / "custom_components"
    / "ecoforest_ecogeo"
    / "units.py"
)


def _load_units():
    spec = importlib.util.spec_from_file_location("ecogeo_units", _UNITS_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ecogeo_units"] = mod
    spec.loader.exec_module(mod)
    return mod


units = _load_units()


def test_fahrenheit_scales_by_one_point_eight() -> None:
    assert units.delta_unit_and_scale("°F") == ("°F", 1.8)


def test_celsius_is_unscaled() -> None:
    assert units.delta_unit_and_scale("°C") == ("°C", 1.0)


def test_unknown_unit_falls_back_to_celsius() -> None:
    assert units.delta_unit_and_scale("K") == ("°C", 1.0)


def test_scale_has_no_offset() -> None:
    """A 10 °C interval is an 18 °F interval, not 50."""
    _, scale = units.delta_unit_and_scale("°F")
    assert 10.0 * scale == 18.0
