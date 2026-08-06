"""Pytest configuration and shared fixtures for Ecoforest Ecogeo tests."""

import json
import pathlib
import types
import sys

import pytest

# ---------------------------------------------------------------------------
# Minimal Home Assistant stubs so the integration modules can be imported
# without a running HA instance.
# ---------------------------------------------------------------------------

HA_MODULES = [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.helpers",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.const",
    "homeassistant.exceptions",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.typing",
    "homeassistant.helpers.entity_platform",
    "homeassistant.components.switch",
    "homeassistant.components.number",
    "homeassistant.components.number.const",
    "homeassistant.components.button",
]

for _mod_name in HA_MODULES:
    if _mod_name not in sys.modules:
        _m = types.ModuleType(_mod_name)
        _m.__getattr__ = lambda _n: type(_n, (), {})()
        sys.modules[_mod_name] = _m


FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "ecogeo_fixture.json"


@pytest.fixture
def raw_responses():
    """Load the captured device responses from the JSON fixture file."""
    with FIXTURE_PATH.open() as f:
        data = json.load(f)
    return data["responses"]
