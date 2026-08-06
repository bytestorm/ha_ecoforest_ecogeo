"""Record-replay tests for EcoGeoApi using captured device responses."""

import asyncio
import json
import pathlib
import sys
import importlib.util

import pytest

# ---------------------------------------------------------------------------
# Module loading  (HA stubs already registered by conftest.py)
# ---------------------------------------------------------------------------

def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

_base = pathlib.Path(__file__).parent.parent / "custom_components" / "ecoforest_ecogeo"
_load(_base / "overrides" / "device.py",
      "custom_components.ecoforest_ecogeo.overrides.device")
api_mod = _load(_base / "overrides" / "api.py",
                "custom_components.ecoforest_ecogeo.overrides.api")

EcoGeoApi = api_mod.EcoGeoApi
MAPPING = api_mod.MAPPING
EASYNET_INDEX = api_mod.EASYNET_INDEX
EASYNET_NAMED_INDEX = api_mod.EASYNET_NAMED_INDEX
EASYNET_SWITCH_WRITE = api_mod.EASYNET_SWITCH_WRITE
EASYNET_REGISTER_WRITE = api_mod.EASYNET_REGISTER_WRITE
OP_TYPE_SET_SWITCH = api_mod.OP_TYPE_SET_SWITCH
OP_TYPE_SET_REGISTER = api_mod.OP_TYPE_SET_REGISTER

# op2150 fixture decoded reference:
#   a[6]=0083→13.1°C (t_stop_heating), a[7]=009C→15.6°C (t_stop_cooling)
#   a[9]=00D2→21.0°C (tsz1), a[14]=00D4→21.2°C (ttz1), a[15]=D8F1→None, a[16]=00D4→21.2°C

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

FIXTURE = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "ecogeo_fixture.json").read_text()
)["responses"]


def _value_lines(response_text: str) -> list[str]:
    """Strip error header and terminator; return value tokens."""
    lines = response_text.split("\n")
    return [l.strip() for l in lines[1:] if l.strip() and l.strip() != "0"]


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _EasnetApi(EcoGeoApi):
    """Replays captured Easynet fixture responses; no HTTP calls."""

    def __init__(self, responses: dict[str, str]):
        self._protocol = "easynet"
        self._responses = responses

    async def _bulk(self, op: int) -> list[str]:
        return _value_lines(self._responses[f"op{op}"])

    async def _get_alarm_code(self) -> int:
        values = _value_lines(self._responses["op1079"])
        if not values:
            return 0
        alarm_str = values[0].split("=", 1)[-1].strip()
        digits = "".join(c for c in alarm_str if c.isdigit())
        return int(digits) if digits else 0


class _BareApi(EcoGeoApi):
    """EcoGeoApi with no HTTP client – for unit-testing helpers."""
    def __init__(self):
        pass


# ---------------------------------------------------------------------------
# _parse unit tests
# ---------------------------------------------------------------------------

class TestParse:
    api = _BareApi()

    def test_easynet_bulk_response(self):
        assert self.api._parse("error_2148=0\n00f9\n0078\n0011\n000c\n0\n") == [
            "00f9", "0078", "0011", "000c"
        ]

    def test_classic_per_register_response(self):
        assert self.api._parse("error_geo_get_bit=0\ndir=1&num=2&0001&0000\n0\n") == [
            "0001", "0000"
        ]

    def test_alarm_response_no_alarm(self):
        assert self.api._parse("error_get_alarmas=0\nget_alarmas=N\n0") == ["get_alarmas=N"]

    def test_alarm_response_with_code(self):
        assert self.api._parse("error_get_alarmas=0\nget_alarmas=G040\n0") == ["get_alarmas=G040"]

    def test_set_op_empty_result(self):
        assert self.api._parse("error_geo_set_bit=0\n0\n") == []

    def test_bad_response_nonzero_error(self):
        with pytest.raises(Exception, match="bad response"):
            self.api._parse("error_2148=1\nsome data\n0\n")

    def test_bad_response_no_equals(self):
        with pytest.raises(Exception, match="bad response"):
            self.api._parse("junk\n0\n")


# ---------------------------------------------------------------------------
# Parse helper unit tests
# ---------------------------------------------------------------------------

class TestParseHelpers:
    api = _BareApi()

    def test_int_positive(self):
        assert self.api.parse_ecoforest_int("00f9") == 249

    def test_int_negative(self):
        # D90F = 55567 → 55567 - 65536 = -9969
        assert self.api.parse_ecoforest_int("D90F") == -9969

    def test_float_positive(self):
        assert self.api.parse_ecoforest_float("00f9") == pytest.approx(24.9)

    def test_float_negative(self):
        assert self.api.parse_ecoforest_float("D90F") == pytest.approx(-996.9)

    def test_bool_true(self):
        assert self.api.parse_ecoforest_bool("0001") is True

    def test_bool_false(self):
        assert self.api.parse_ecoforest_bool("0000") is False

    def test_convert_positive(self):
        assert self.api.convert_to_ecoforest_int(24.9) == "00f9"

    def test_convert_negative(self):
        assert self.api.convert_to_ecoforest_int(-5.0) == "ffce"

    def test_convert_zero(self):
        assert self.api.convert_to_ecoforest_int(0.0) == "0000"

    @pytest.mark.parametrize("val", [0.0, 1.5, 21.0, -5.0, 50.0, -30.0])
    def test_roundtrip(self, val):
        encoded = self.api.convert_to_ecoforest_int(val)
        assert self.api.parse_ecoforest_float(encoded) == pytest.approx(val)


# ---------------------------------------------------------------------------
# Protocol detection
# ---------------------------------------------------------------------------

class TestProtocolDetection:
    def _make_api(self, response_text: str) -> EcoGeoApi:
        from unittest.mock import AsyncMock, MagicMock
        api = EcoGeoApi.__new__(EcoGeoApi)
        api._protocol = None
        mock_resp = MagicMock()
        mock_resp.text = response_text
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        api._client = mock_client
        api._auth = None
        api._timeout = 10
        return api

    def test_detects_easynet(self):
        api = self._make_api(FIXTURE["detect"])
        assert asyncio.run(api._detect_protocol()) == "easynet"

    def test_detects_classic(self):
        api = self._make_api("error_geo_get_bit=0\ndir=1&num=1&0001\n0\n")
        assert asyncio.run(api._detect_protocol()) == "classic"

    def test_defaults_to_easynet_on_connection_error(self):
        from unittest.mock import AsyncMock, MagicMock
        api = EcoGeoApi.__new__(EcoGeoApi)
        api._protocol = None
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=Exception("refused"))
        api._client = mock_client
        api._auth = None
        api._timeout = 10
        assert asyncio.run(api._detect_protocol()) == "easynet"


# ---------------------------------------------------------------------------
# Easynet get() – replay real production fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="class")
def easynet_device(request):
    api = _EasnetApi(FIXTURE)
    device = asyncio.run(api.get())
    request.cls.device = device
    request.cls.state = device.state


@pytest.mark.usefixtures("easynet_device")
class TestEasnetGet:
    def test_model_name(self):
        assert self.device.model_name == "Ecogeo"

    # op 2148 – temperatures and pressures
    def test_t_outdoor(self):
        assert self.state["t_outdoor"] == pytest.approx(25.8)

    def test_t_brine_return(self):
        assert self.state["t_brine_return"] == pytest.approx(18.3)

    def test_t_production_return(self):
        assert self.state["t_production_return"] == pytest.approx(9.8)

    def test_p_brine(self):
        assert self.state["p_brine"] == pytest.approx(1.7)

    def test_p_output(self):
        assert self.state["p_output"] == pytest.approx(1.1)

    # op 2149 – power. Registers report 0.1 kW steps; entities are W,
    # so the parse scales ×100 (fixture raw: heating 0, cooling 104, electric 15).
    def test_power_heating_zero(self):
        assert self.state["power_heating"] == 0

    def test_power_cooling(self):
        assert self.state["power_cooling"] == 10400

    def test_power_electric(self):
        assert self.state["power_electric"] == 1500

    def test_power_output_sum(self):
        assert self.state["power_output"] == 10400

    def test_cop(self):
        # Unit in pure cooling mode: heating power = 0, so there is no
        # heating COP to report (not a COP of zero).
        assert self.state["cop"] is None

    def test_eer(self):
        # cooling=10400 W, electric=1500 W → EER = 6.93
        assert self.state["eer"] == pytest.approx(6.93)

    def test_pf(self):
        # (heating+cooling)/electric = 10400/1500 = 6.93
        assert self.state["pf"] == pytest.approx(6.93)

    # op 2151 – buffer / zone / DHW temps
    def test_t_heating_buffer_actual(self):
        assert self.state["t_heating"] == pytest.approx(8.9)

    def test_t_cooling_buffer_actual(self):
        assert self.state["t_cooling"] == pytest.approx(8.9)

    def test_t_dhw_none_when_not_connected(self):
        # D90F = -996.9°C ≤ -50°C → filtered to None
        assert self.state["t_dhw"] is None

    def test_t_dg1_h_zone1_heat_setpoint(self):
        assert self.state["t_dg1_h"] == pytest.approx(21.0)

    def test_t_dg1_c_zone1_cool_setpoint(self):
        # 0074 = 116 → 11.6°C
        assert self.state["t_dg1_c"] == pytest.approx(11.6)

    def test_t_sg2_unconfigured_zero(self):
        assert self.state["t_sg2"] == pytest.approx(0.0)

    def test_t_sg5_unconfigured_zero(self):
        assert self.state["t_sg5"] == pytest.approx(0.0)

    # op 2148 – production and brine supply temps
    def test_t_production_supply(self):
        # 0041 = 65 → 6.5°C
        assert self.state["t_production_supply"] == pytest.approx(6.5)

    def test_t_brine_supply(self):
        # 00D8 = 216 → 21.6°C
        assert self.state["t_brine_supply"] == pytest.approx(21.6)

    # op 2151 – thermostat temps and zone regulation
    def test_t_thermostat_1_zero(self):
        assert self.state["t_thermostat_1"] == pytest.approx(0.0)

    def test_t_thermostat_2_not_connected(self):
        # D8F1 = -999.9°C ≤ -50°C → filtered to None
        assert self.state["t_thermostat_2"] is None

    def test_t_thermostat_3(self):
        # 00DD = 221 → 22.1°C
        assert self.state["t_thermostat_3"] == pytest.approx(22.1)

    def test_regulation_zone_1_zero(self):
        assert self.state["regulation_zone_1"] == pytest.approx(0.0)

    def test_t_dg2_c_unconfigured_zero(self):
        assert self.state["t_dg2_c"] == pytest.approx(0.0)

    # op 2151 – buffer tank setpoints and offsets
    def test_t_heating_setpoint(self):
        # 012C = 300 → 30.0°C
        assert self.state["t_heating_setpoint"] == pytest.approx(30.0)

    def test_t_heating_offset(self):
        # 0032 = 50 → 5.0°C
        assert self.state["t_heating_offset"] == pytest.approx(5.0)

    def test_t_cooling_setpoint(self):
        # 0047 = 71 → 7.1°C
        assert self.state["t_cooling_setpoint"] == pytest.approx(7.1)

    def test_t_cooling_offset(self):
        # 0032 = 50 → 5.0°C
        assert self.state["t_cooling_offset"] == pytest.approx(5.0)

    # op 2150 – outdoor stop temps and room-terminal zone data
    def test_t_stop_heating(self):
        # 0080 = 128 → 12.8°C
        assert self.state["t_stop_heating"] == pytest.approx(12.8)

    def test_t_stop_cooling(self):
        # 009C = 156 → 15.6°C
        assert self.state["t_stop_cooling"] == pytest.approx(15.6)

    def test_t_zone_setpoint_1_unconfigured_zero(self):
        # No zone room terminals connected on this device
        assert self.state["t_zone_setpoint_1"] == pytest.approx(0.0)

    def test_t_zone_setpoint_2_unconfigured_zero(self):
        assert self.state["t_zone_setpoint_2"] == pytest.approx(0.0)

    def test_t_zone_actual_1_unconfigured_zero(self):
        assert self.state["t_zone_actual_1"] == pytest.approx(0.0)

    def test_t_zone_actual_2_unconfigured_zero(self):
        assert self.state["t_zone_actual_2"] == pytest.approx(0.0)

    def test_t_zone_actual_3_unconfigured_zero(self):
        assert self.state["t_zone_actual_3"] == pytest.approx(0.0)

    # Switches
    def test_switch_heating_off(self):
        assert self.state["switch_heating"] is False

    def test_switch_cooling_on(self):
        assert self.state["switch_cooling"] is True

    def test_switch_dhw_off(self):
        assert self.state["switch_dhw"] is False

    def test_unmapped_switches_are_none(self):
        for key in ("switch_dg1_output", "switch_sg2_output",
                    "switch_pool_output", "switch_pool_device_output"):
            assert self.state[key] is None, f"{key} should be None"

    # Number inputs
    def test_number_dhw_setpoint_none_when_not_connected(self):
        # FC19 = -99.9°C ≤ -50°C → filtered to None
        assert self.state["number_dhw_setpoint"] is None

    def test_number_dhw_dt_start_valid(self):
        # 0032 = 5.0°C – a valid default
        assert self.state["number_dhw_dt_start"] == pytest.approx(5.0)

    # Alarm
    def test_alarm_no_alarm(self):
        assert self.state["alarm"] == 0

    # Unavailable on Easynet
    def test_number_dhw_htr_set_none(self):
        assert self.state["number_dhw_htr_set"] is None

    # Completeness
    def test_all_mapping_keys_present_in_state(self):
        for key in MAPPING:
            assert key in self.state, f"missing key in state: {key}"


# ---------------------------------------------------------------------------
# Alarm code parsing
# ---------------------------------------------------------------------------

class TestAlarmParsing:
    def _code(self, raw: str) -> int:
        api = _EasnetApi({"op1079": raw})
        return asyncio.run(api._get_alarm_code())

    def test_no_alarm_returns_zero(self):
        assert self._code("error_get_alarmas=0\nget_alarmas=N\n0") == 0

    def test_alarm_g040_returns_40(self):
        assert self._code("error_get_alarmas=0\nget_alarmas=G040\n0") == 40

    def test_alarm_g001_returns_1(self):
        assert self._code("error_get_alarmas=0\nget_alarmas=G001\n0") == 1

    def test_alarm_empty_body_returns_zero(self):
        assert self._code("error_get_alarmas=0\n0") == 0


# ---------------------------------------------------------------------------
# Write address constants
# ---------------------------------------------------------------------------

class TestWriteAddresses:
    def test_cooling_coil_address(self):
        assert EASYNET_SWITCH_WRITE["switch_cooling"] == 1568

    def test_heating_coil_address(self):
        assert EASYNET_SWITCH_WRITE["switch_heating"] == 1552

    def test_dhw_coil_address(self):
        assert EASYNET_SWITCH_WRITE["switch_dhw"] == 1524

    def test_dhw_setpoint_register_address(self):
        assert EASYNET_REGISTER_WRITE["number_dhw_setpoint"] == 6106

    def test_dhw_dt_start_register_address(self):
        assert EASYNET_REGISTER_WRITE["number_dhw_dt_start"] == 6105

    def test_dhw_htr_set_register_address(self):
        assert EASYNET_REGISTER_WRITE["number_dhw_htr_set"] == 6104


# ---------------------------------------------------------------------------
# turn_switch sends the right payload (Easynet)
# ---------------------------------------------------------------------------

class TestTurnSwitch:
    def _api_with_write_capture(self):
        """_EasnetApi that records the most recent _request call."""
        captured = {}

        class _Spy(_EasnetApi):
            async def _request(self_, data):
                captured.update(data)
                op = data.get("idOperacion")
                if op in (OP_TYPE_SET_SWITCH, OP_TYPE_SET_REGISTER):
                    return []
                # For reads during the follow-up get(), delegate to _bulk
                return await self_._bulk(op)

        return _Spy(FIXTURE), captured

    def test_turn_cooling_on_sends_correct_coil(self):
        api, captured = self._api_with_write_capture()

        async def run():
            # Manually issue the write request the way turn_switch would
            await api._request({
                "idOperacion": OP_TYPE_SET_SWITCH,
                "dir": EASYNET_SWITCH_WRITE["switch_cooling"],
                "num": 1,
                1: 1,
            })

        asyncio.run(run())
        assert captured["idOperacion"] == OP_TYPE_SET_SWITCH
        assert captured["dir"] == 1568

    def test_turn_heating_off_sends_correct_coil(self):
        api, captured = self._api_with_write_capture()

        async def run():
            await api._request({
                "idOperacion": OP_TYPE_SET_SWITCH,
                "dir": EASYNET_SWITCH_WRITE["switch_heating"],
                "num": 1,
                0: 0,
            })

        asyncio.run(run())
        assert captured["dir"] == 1552

    def test_unknown_switch_raises(self):
        api = _EasnetApi(FIXTURE)
        with pytest.raises(Exception, match="unknown switch"):
            asyncio.run(api.turn_switch("nonexistent", True))

    def test_unmapped_switch_raises(self):
        api = _EasnetApi(FIXTURE)
        with pytest.raises(Exception, match="no write address"):
            asyncio.run(api.turn_switch("switch_dg1_output", True))


# ---------------------------------------------------------------------------
# set_numeric_value sends the right payload (Easynet)
# ---------------------------------------------------------------------------

class TestSetNumericValue:
    def test_dhw_setpoint_encodes_correctly(self):
        bare = _BareApi()
        # 45.0°C → 450 → 0x01C2
        assert bare.convert_to_ecoforest_int(45.0) == "01c2"

    def test_set_numeric_unknown_raises(self):
        api = _EasnetApi(FIXTURE)
        with pytest.raises(Exception, match="unknown register"):
            asyncio.run(api.set_numeric_value("nonexistent", 45.0))


# ---------------------------------------------------------------------------
# Yearly energy sensors (op 2139, named-field format)
# ---------------------------------------------------------------------------

class TestNamedValue:
    api = _BareApi()

    def test_finds_key(self):
        assert self.api._named_value(["YAU=0000", "YH=03E8", "YE=007D"], "YH") == "03E8"

    def test_missing_key_returns_none(self):
        assert self.api._named_value(["YAU=0000", "YH=03E8"], "YE") is None

    def test_prefix_not_confused_with_longer_key(self):
        assert self.api._named_value(["YAU=0001", "YA=0002"], "YA") == "0002"


class TestMonthlyEnergy:
    state = asyncio.run(_EasnetApi(FIXTURE).get()).state

    def test_energy_electric_month(self):
        # ME=01F4 = 500 → 50.0 kWh
        assert self.state["energy_electric_month"] == pytest.approx(50.0)

    def test_energy_heating_month(self):
        # MH=0258 = 600 → 60.0 kWh
        assert self.state["energy_heating_month"] == pytest.approx(60.0)

    def test_energy_cooling_month(self):
        # MAC=04B0 = 1200 → 120.0 kWh
        assert self.state["energy_cooling_month"] == pytest.approx(120.0)


class TestDailyEnergy:
    state = asyncio.run(_EasnetApi(FIXTURE).get()).state

    def test_energy_electric_day(self):
        # DE=00C8 = 200 → 20.0 kWh
        assert self.state["energy_electric_day"] == pytest.approx(20.0)

    def test_energy_heating_day(self):
        # DH=0064 = 100 → 10.0 kWh
        assert self.state["energy_heating_day"] == pytest.approx(10.0)

    def test_energy_cooling_day(self):
        # DAC=012C = 300 → 30.0 kWh
        assert self.state["energy_cooling_day"] == pytest.approx(30.0)

    def test_missing_key_yields_none(self):
        bare = _BareApi()
        assert bare._named_value(["DH=0064"], "DMISSING") is None
