import string, logging
from dataclasses import dataclass

import httpx
from pyecoforest.api import EcoforestApi
from pyecoforest.const import URL_CGI

from custom_components.ecoforest_ecogeo.overrides.device import EcoGeoDevice

_LOGGER = logging.getLogger(__name__)

MODEL_ADDRESS = 5323
MODEL_LENGTH = 6

OP_TYPE_GET_SWITCH = 2001
OP_TYPE_SET_SWITCH = 2011
OP_TYPE_GET_REGISTER = 2002
OP_TYPE_SET_REGISTER = 2012

class DataTypes:
    Register = 1
    Coil = 2

class Operations:
    Get = {DataTypes.Coil: 2001, DataTypes.Register: 2002}
    Set = {DataTypes.Coil: 2011, DataTypes.Register: 2012}

# REQUESTS is used by the classic protocol to fetch register/coil data.
REQUESTS = {
    DataTypes.Coil : [
        {"address": 1, "length": 41},
        {"address": 57, "length": 27},
        {"address": 105, "length": 3},
        {"address": 212, "length": 15},
    ],

    DataTypes.Register: [
        {"address": 1, "length": 31},
        {"address": 59, "length": 1},
        {"address": 194, "length": 8},
        {"address": 5066, "length": 18},
        {"address": 5185, "length": 1},
        {"address": MODEL_ADDRESS, "length": MODEL_LENGTH, "op": OP_TYPE_GET_REGISTER},
    ]
}

def _delta(supply: float | None, ret: float | None) -> float | None:
    """Return supply minus return, or None if either reading is unavailable."""
    if supply is None or ret is None:
        return None
    return round(supply - ret, 2)


def _buffer_error(data: dict[str, object]) -> float | None:
    """Return buffer temperature minus the setpoint for the active mode.

    Returns None when neither heating nor cooling is enabled, because there is
    no setpoint to be in error against.
    """
    if data.get("switch_heating"):
        setpoint = data.get("t_heating_setpoint")
    elif data.get("switch_cooling"):
        setpoint = data.get("t_cooling_setpoint")
    else:
        return None
    buffer = data.get("t_heating")
    if buffer is None or setpoint is None:
        return None
    return round(buffer - setpoint, 2)


def _efficiency(output: float | None, electric: float | None) -> float | None:
    """Ratio of thermal output to electrical input.

    Returns None rather than 0.0 when there is no output in this mode: a heat
    pump that is cooling has no heating COP, which is a different statement
    from having a COP of zero. Reporting 0.0 pollutes long-term statistics and
    flattens the scale of any graph the figure shares.
    """
    if not electric or not output:
        return None
    return round(output / electric, 2)


# MAPPING is the source of truth for entity discovery (keys, units, device class).
# The "data_type" and "address" fields are used by the classic protocol.
# Easynet G2 bulk-op reads are looked up in EASYNET_INDEX below.
MAPPING = {
    "t_heating": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 200,
        "entity_type": "temperature"
    },
    "t_cooling": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 201,
        "entity_type": "temperature"
    },
    "t_dhw": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 8,
        "entity_type": "temperature"
    },
    "t_dg1_h": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 3,
        "entity_type": "temperature"
    },
    "t_dg1_c": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 197,
        "entity_type": "temperature"
    },
    "t_sg2": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 194,
        "entity_type": "temperature"
    },
    "t_sg3": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 195,
        "entity_type": "temperature"
    },
    "t_sg4": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 196,
        "entity_type": "temperature"
    },
    "t_outdoor": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 11,
        "entity_type": "temperature"
    },
    "power_heating": {
        "data_type": DataTypes.Register,
        "type": "int",
        "address": 5083,
        "entity_type": "power"
    },
    "power_cooling": {
        "data_type": DataTypes.Register,
        "type": "int",
        "address": 5185,
        "entity_type": "power"
    },
    "power_electric": {
        "data_type": DataTypes.Register,
        "type": "int",
        "address": 5082,
        "entity_type": "power"
    },
    "power_output": {
        "data_type": DataTypes.Register,
        "type": "custom",
        "entity_type": "power",
        "value_fn": lambda data, raw: data["power_cooling"] + data["power_heating"]
    },
    "t_brine_delta": {
        "type": "derived",
        "entity_type": "temperature_delta",
        "value_fn": lambda data: _delta(
            data.get("t_brine_supply"), data.get("t_brine_return")
        ),
    },
    "t_production_delta": {
        "type": "derived",
        "entity_type": "temperature_delta",
        "value_fn": lambda data: _delta(
            data.get("t_production_supply"), data.get("t_production_return")
        ),
    },
    "t_buffer_error": {
        "type": "derived",
        "entity_type": "temperature_delta",
        "value_fn": _buffer_error,
    },
    "t_brine_return": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 2,
        "entity_type": "temperature"
    },
    "t_production_return": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 1,
        "entity_type": "temperature"
    },
    "p_brine": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 13,
        "entity_type": "pressure"
    },
    "p_output": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 14,
        "entity_type": "pressure"
    },
    "cop": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 30,
        "entity_type": "measurement"
    },
    "pf": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 31,
        "entity_type": "measurement"
    },
    "switch_heating": {
        "data_type": DataTypes.Coil,
        "type": "boolean",
        "address": 105,
        "entity_type": "switch"
    },
    "switch_cooling": {
        "data_type": DataTypes.Coil,
        "type": "boolean",
        "address": 107,
        "entity_type": "switch"
    },
    "switch_dhw": {
        "data_type": DataTypes.Coil,
        "type": "boolean",
        "address": 106,
        "entity_type": "switch"
    },
    "switch_dg1_output": {
        "data_type": DataTypes.Coil,
        "type": "boolean",
        "address": 60,
        "entity_type": "switch"
    },
    "switch_sg2_output": {
        "data_type": DataTypes.Coil,
        "type": "boolean",
        "address": 57,
        "entity_type": "switch"
    },
    "switch_pool_output": {
        "data_type": DataTypes.Coil,
        "type": "boolean",
        "address": 65,
        "entity_type": "switch"
    },
    "switch_pool_device_output": {
        "data_type": DataTypes.Coil,
        "type": "boolean",
        "address": 61,
        "entity_type": "switch"
    },
    "button_reset_alarms": {
        "data_type": DataTypes.Coil,
        "type": "boolean",
        "address": 83,
        "entity_type": "button"
    },
    "number_dhw_setpoint": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 17,
        "entity_type": "temperature",
        "is_number": True,
        "min": 0,
        "max": 65,
        "step": 0.1
    },
    "number_dhw_dt_start": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 15,
        "entity_type": "temperature",
        "is_number": True,
        "min": 2,
        "max": 25,
        "step": 0.1
    },
    "number_dhw_htr_set": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": 59,
        "entity_type": "temperature",
        "is_number": True,
        "min": 0,
        "max": 70,
        "step": 0.1
    },
    "t_cooling_setpoint": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_production_supply": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_brine_supply": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "energy_electric_month": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "energy"
    },
    "energy_heating_month": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "energy"
    },
    "energy_cooling_month": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "energy"
    },
    "energy_electric_day": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "energy"
    },
    "energy_heating_day": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "energy"
    },
    "energy_cooling_day": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "energy"
    },
    "t_sg5": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_thermostat_1": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_thermostat_2": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_thermostat_3": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_thermostat_4": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_thermostat_5": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "regulation_zone_1": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "measurement"
    },
    "regulation_zone_2": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "measurement"
    },
    "regulation_zone_3": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "measurement"
    },
    "regulation_zone_4": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "measurement"
    },
    "regulation_zone_5": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "measurement"
    },
    "t_dg2_c": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_dg3_c": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_dg4_c": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_dg5_c": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_heating_setpoint": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_heating_offset": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_cooling_offset": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_stop_heating": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_stop_cooling": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_zone_setpoint_1": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_zone_setpoint_2": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_zone_setpoint_3": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_zone_setpoint_4": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_zone_setpoint_5": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_zone_actual_1": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_zone_actual_2": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_zone_actual_3": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_zone_actual_4": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "t_zone_actual_5": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "temperature"
    },
    "eer": {
        "data_type": DataTypes.Register,
        "type": "float",
        "address": None,
        "entity_type": "measurement"
    },
    "alarm": {
        "data_type": DataTypes.Coil,
        "type": "custom",
        "entity_type": "enum",
        "value_fn": lambda data, raw: EcoGeoApi.get_alarm(raw)
    }
}

#: Keys computed from other values rather than read from a register.
DERIVED_KEYS: tuple[str, ...] = ("t_brine_delta", "t_production_delta", "t_buffer_error")


def apply_derived(device_info: dict[str, object]) -> None:
    """Populate the derived delta-T entries in place.

    Called at the end of both protocol paths, after every source value has
    been decoded and after temperature sentinels have been cleared to None.
    """
    for key in DERIVED_KEYS:
        device_info[key] = MAPPING[key]["value_fn"](device_info)


# ── Easynet G2 (Easynet gateway) specific data ────────────────────────────────
#
# The Easynet G2 exposes bulk read operations (2148, 2149, 2151) that return
# one hex value per line.  Each entry is (bulk_op, zero-based_index).
#
# Op 2148 – status/temperatures/pressures
# Op 2149 – power values
# Op 2151 – buffer/zone/DHW temperatures and setpoints
EASYNET_INDEX = {
    "t_outdoor":      (2148, 21),
    "t_brine_return":       (2148, 24),   # trp: brine returning from wells to HP
    "t_production_return":  (2148, 19),   # trc: production water returning from building
    "p_brine":        (2148, 20),   # brine circuit pressure
    "p_output":       (2148, 18),   # production circuit pressure
    "power_heating":  (2149,  1),
    "power_cooling":  (2149,  2),
    "power_electric": (2149,  3),
    "t_heating":      (2151, 20),   # heat buffer tank actual temperature
    "t_cooling":      (2151, 23),   # cool buffer tank actual temperature
    "t_dhw":          (2151, 28),   # DHW actual temperature
    "t_dg1_h":        (2151,  0),   # zone 1 heat setpoint
    "t_dg1_c":        (2151, 15),   # zone 1 cool setpoint
    "t_sg2":          (2151,  1),   # zone 2 heat setpoint
    "t_sg3":          (2151,  2),   # zone 3 heat setpoint
    "t_sg4":          (2151,  3),   # zone 4 heat setpoint
    "switch_heating": (2148, 26),   # heating-enabled status flag
    "switch_cooling": (2148, 27),   # cooling-enabled status flag
    "switch_dhw":     (2148, 25),   # DHW-enabled status flag
    "number_dhw_setpoint":  (2151, 26),
    "number_dhw_dt_start":  (2151, 27),
    "t_cooling_setpoint":   (2151, 24),   # cool buffer tank setpoint (cbtsp)
    # Op 2148 – production circuit temps
    "t_production_supply":  (2148, 22),   # tic: production water supplied to building
    "t_brine_supply":       (2148, 23),   # tip: brine supplied from HP to wells
    # Op 2151 – zone 5 setpoints, thermostat temps, valve regulation
    "t_sg5":                (2151,  4),   # hdtsg5: zone 5 heating setpoint
    "t_thermostat_1":       (2151,  5),   # ti1: zone 1 thermostat actual temp
    "t_thermostat_2":       (2151,  6),   # ti2
    "t_thermostat_3":       (2151,  7),   # ti3
    "t_thermostat_4":       (2151,  8),   # ti4
    "t_thermostat_5":       (2151,  9),   # ti5
    "regulation_zone_1":    (2151, 10),   # rvz1: zone 1 valve/regulation %
    "regulation_zone_2":    (2151, 11),   # rvz2
    "regulation_zone_3":    (2151, 12),   # rvz3
    "regulation_zone_4":    (2151, 13),   # rvz4
    "regulation_zone_5":    (2151, 14),   # rvz5
    "t_dg2_c":              (2151, 16),   # cdtsg2: zone 2 cooling setpoint
    "t_dg3_c":              (2151, 17),   # cdtsg3: zone 3 cooling setpoint
    "t_dg4_c":              (2151, 18),   # cdtsg4: zone 4 cooling setpoint
    "t_dg5_c":              (2151, 19),   # cdtsg5: zone 5 cooling setpoint
    "t_heating_setpoint":   (2151, 21),   # hbtsp: heating buffer tank setpoint
    "t_heating_offset":     (2151, 22),   # oic: heating buffer DT start
    "t_cooling_offset":     (2151, 25),   # oif: cooling buffer DT start
    # Op 2150 – outdoor stop temps and room-terminal zone data
    "t_stop_heating":       (2150,  6),   # tcc: outdoor heating stop temp
    "t_stop_cooling":       (2150,  7),   # tcfa: outdoor active-cooling start temp
    "t_zone_setpoint_1":    (2150,  9),   # tsz1: zone 1 room-terminal setpoint
    "t_zone_setpoint_2":    (2150, 10),   # tsz2
    "t_zone_setpoint_3":    (2150, 11),   # tsz3
    "t_zone_setpoint_4":    (2150, 12),   # tsz4
    "t_zone_setpoint_5":    (2150, 13),   # tsz5
    "t_zone_actual_1":      (2150, 14),   # ttz1: zone 1 room-terminal actual temp
    "t_zone_actual_2":      (2150, 15),   # ttz2
    "t_zone_actual_3":      (2150, 16),   # ttz3
    "t_zone_actual_4":      (2150, 17),   # ttz4
    "t_zone_actual_5":      (2150, 18),   # ttz5
}

# Coil write addresses (op 2011) for Easynet G2 switches
EASYNET_SWITCH_WRITE = {
    "switch_heating": 1552,
    "switch_cooling": 1568,
    "switch_dhw":     1524,
}

# Analog register write addresses (op 2012) for Easynet G2 number entities
EASYNET_REGISTER_WRITE = {
    "number_dhw_setpoint": 6106,
    "number_dhw_dt_start": 6105,
    "number_dhw_htr_set":  6104,
}

# Named-field ops: response lines are KEY=HEX rather than bare hex.
# Op 2140 – month-to-date energy totals (kWh, value/10)
# Op 2137 – today's energy totals (kWh, value/10)
EASYNET_NAMED_INDEX = {
    "energy_electric_month": (2140, "ME"),
    "energy_heating_month":  (2140, "MH"),
    "energy_cooling_month":  (2140, "MAC"),
    "energy_electric_day":   (2137, "DE"),
    "energy_heating_day":    (2137, "DH"),
    "energy_cooling_day":    (2137, "DAC"),
}


class EcoGeoApi(EcoforestApi):
    def __init__(
        self,
        host: str,
        user: str,
        password: str
    ) -> None:
        super().__init__(host, httpx.BasicAuth(user, password))
        self._protocol = None   # "classic" or "easynet"; detected on first get()

    async def get(self) -> EcoGeoDevice:
        if self._protocol is None:
            self._protocol = await self._detect_protocol()
            _LOGGER.info("Detected Ecoforest protocol: %s", self._protocol)

        if self._protocol == "easynet":
            return await self._get_easynet()
        return await self._get_classic()

    # ── Classic protocol ──────────────────────────────────────────────────────

    async def _get_classic(self) -> EcoGeoDevice:
        state = {DataTypes.Coil: {}, DataTypes.Register: {}}

        for dt in [DataTypes.Coil, DataTypes.Register]:
            for request in REQUESTS[dt]:
                state[dt].update(await self._load_data(request["address"], request["length"], Operations.Get[dt]))

        device_info = {}
        for name, definition in MAPPING.items():
            address = definition.get("address")
            if address is None:
                # Easynet-only entry; not available on classic devices
                device_info[name] = None
                continue
            raw = state[definition["data_type"]].get(address)
            if raw is None:
                device_info[name] = None
                continue
            match definition["type"]:
                case "int":
                    value = self.parse_ecoforest_int(raw)
                case "float":
                    value = self.parse_ecoforest_float(raw)
                case "boolean":
                    value = self.parse_ecoforest_bool(raw)
                case "custom":
                    continue
                case _:
                    _LOGGER.error("unknown entity type for %s", name)
                    continue

            device_info[name] = value

        for name, definition in MAPPING.items():
            if definition["entity_type"] == "temperature":
                if device_info.get(name) == -999.9:
                    device_info[name] = None

            if definition["type"] != "custom":
                continue
            device_info[name] = definition["value_fn"](device_info, state)

        apply_derived(device_info)

        _LOGGER.debug(device_info)
        _LOGGER.debug(state)
        return EcoGeoDevice.build(self.parse_model_name(state), device_info)

    async def _load_data(self, address, length, op_type) -> dict[int, str]:
        response = await self._request(
            data={
                "idOperacion": op_type,
                "dir": address,
                "num": length
            }
        )

        result = {}
        index = 0
        for i in range(address, address+length):
            result[i] = response[index]
            index += 1

        return result

    # ── Easynet G2 protocol ───────────────────────────────────────────────────

    async def _get_easynet(self) -> EcoGeoDevice:
        op2148 = await self._bulk(2148)
        op2149 = await self._bulk(2149)
        op2150 = await self._bulk(2150)
        op2151 = await self._bulk(2151)
        op2137 = await self._bulk(2137)
        op2140 = await self._bulk(2140)
        alarm_code = await self._get_alarm_code()

        raw = {2148: op2148, 2149: op2149, 2150: op2150, 2151: op2151}
        device_info = {}

        for name, (op, idx) in EASYNET_INDEX.items():
            vals = raw[op]
            if idx >= len(vals):
                device_info[name] = None
                continue
            val = vals[idx]
            defn = MAPPING[name]
            if defn["type"] == "float":
                device_info[name] = self.parse_ecoforest_float(val)
            elif defn["type"] == "int":
                device_info[name] = self.parse_ecoforest_int(val)
            elif defn["type"] == "boolean":
                device_info[name] = self.parse_ecoforest_bool(val)

        for name in EASYNET_INDEX:
            v = device_info.get(name)
            if MAPPING[name].get("entity_type") == "temperature" and v is not None and v <= -50.0:
                device_info[name] = None

        # Op 2149 power registers report 0.1 kW steps; power entities are W
        for name in ("power_heating", "power_cooling", "power_electric"):
            if device_info.get(name) is not None:
                device_info[name] = device_info[name] * 100

        named_raw = {2137: op2137, 2140: op2140}
        for name, (op, key) in EASYNET_NAMED_INDEX.items():
            val = self._named_value(named_raw[op], key)
            device_info[name] = self.parse_ecoforest_float(val) if val is not None else None

        # Computed / unavailable entries
        h = device_info.get("power_heating") or 0
        c = device_info.get("power_cooling") or 0
        e = device_info.get("power_electric")
        device_info["power_output"] = h + c
        device_info["cop"] = _efficiency(h, e)        # heating COP
        device_info["eer"] = _efficiency(c, e)        # cooling EER
        device_info["pf"]  = _efficiency(h + c, e)    # combined PF
        device_info["number_dhw_htr_set"] = None

        # Switches not yet mapped on Easynet
        for key in ("switch_dg1_output", "switch_sg2_output", "switch_pool_output",
                    "switch_pool_device_output", "button_reset_alarms"):
            device_info[key] = None

        apply_derived(device_info)
        device_info["alarm"] = alarm_code

        _LOGGER.debug(device_info)
        return EcoGeoDevice.build("Ecogeo", device_info)

    async def _bulk(self, op: int) -> list[str]:
        """Call a bulk read operation and return a list of hex value strings."""
        return await self._request(data={"idOperacion": op})

    async def _get_alarm_code(self) -> int:
        """Return numeric alarm code (0 = no alarm) from op 1079."""
        try:
            values = await self._request(data={"idOperacion": 1079})
            if not values:
                return 0
            # Response line is "get_alarmas=N" or "get_alarmas=G040"
            alarm_str = values[0].split("=", 1)[-1].strip()
            digits = "".join(c for c in alarm_str if c.isdigit())
            return int(digits) if digits else 0
        except Exception as e:
            _LOGGER.warning("Failed to get alarm status: %s", e)
            return 0

    # ── Protocol detection ────────────────────────────────────────────────────

    async def _detect_protocol(self) -> str:
        """Probe the device to determine which API protocol it speaks.

        Classic Ecoforest devices respond to op 2001 with an error key of the
        form "error_geo_get_bit".  The Easynet G2 gateway responds with a
        numeric key like "error_2001".
        """
        try:
            response = await self._client.post(
                URL_CGI,
                auth=self._auth,
                timeout=self._timeout,
                data={"idOperacion": 2001, "dir": 1, "num": 1},
            )
            response.raise_for_status()
            first_line = response.text.split('\n')[0]
            if first_line.startswith("error_geo_"):
                return "classic"
        except Exception as e:
            _LOGGER.warning("Protocol detection failed, defaulting to easynet: %s", e)
        return "easynet"

    # ── Switch / register writes ──────────────────────────────────────────────

    async def turn_switch(self, name, on: bool | None = False) -> EcoGeoDevice:
        if name not in MAPPING:
            raise Exception("unknown switch")

        if self._protocol == "easynet":
            write_addr = EASYNET_SWITCH_WRITE.get(name)
            if write_addr is None:
                raise Exception(f"switch {name!r} has no write address for Easynet protocol")
        else:
            write_addr = MAPPING[name]["address"]

        await self._request(
            data={"idOperacion": OP_TYPE_SET_SWITCH, "dir": write_addr, "num": 1, int(on): int(on)}
        )
        return await self.get()

    async def set_numeric_value(self, name, value: float) -> EcoGeoDevice:
        if name not in MAPPING:
            raise Exception("unknown register")

        if self._protocol == "easynet":
            write_addr = EASYNET_REGISTER_WRITE.get(name)
            if write_addr is None:
                raise Exception(f"register {name!r} has no write address for Easynet protocol")
        else:
            write_addr = MAPPING[name]["address"]

        converted_value = self.convert_to_ecoforest_int(value)
        await self._request(
            data={"idOperacion": OP_TYPE_SET_REGISTER, "dir": write_addr, "num": 1, converted_value: converted_value}
        )
        return await self.get()

    # ── Parsing helpers ───────────────────────────────────────────────────────

    def _parse(self, response: str) -> list[str]:
        """Parse a CGI response into a list of value strings.

        Both protocols return one value per logical token; the difference is
        whether they arrive on separate lines (Easynet bulk ops) or on a
        single ampersand-delimited line (classic per-register reads).

        The first line is always an error indicator of the form KEY=0; any
        non-zero value indicates a device error.
        """
        lines = response.split('\n')
        if not lines or '=' not in lines[0]:
            raise Exception(f"bad response: {response!r}")

        _, _, status = lines[0].partition('=')
        if status.strip() != "0":
            raise Exception(f"bad response: {response!r}")

        # Classic per-register: values are on line[1] separated by '&'
        # (format: "dir=ADDR&num=LEN&VAL1&VAL2&...")
        if len(lines) > 1 and '&' in lines[1]:
            return lines[1].split('&')[2:]

        # Easynet bulk / alarm: one value per line; last line is "0" (terminator)
        return [l.strip() for l in lines[1:] if l.strip() and l.strip() != '0']

    def parse_model_name(self, data):
        model_dictionary = ["--"] + [*string.digits] + [*string.ascii_uppercase]

        result = ''
        for address in range(MODEL_ADDRESS, MODEL_ADDRESS + MODEL_LENGTH):
            result += model_dictionary[self.parse_ecoforest_int(data[DataTypes.Register][address])]

        return result

    def convert_to_ecoforest_int(self, value):
        value = int(value * 10)

        if value < 0:
            value += 65536

        return ("0000" + hex(value)[2:])[-4:]

    def parse_ecoforest_int(self, value):
        result = int(value, 16)
        return result if result <= 32768 else result - 65536

    def parse_ecoforest_bool(self, value):
        return bool(int(value, 16))

    def parse_ecoforest_float(self, value):
        return self.parse_ecoforest_int(value) / 10

    def _named_value(self, values: list[str], key: str) -> str | None:
        """Return the hex string for KEY= from a named-field op response, or None."""
        prefix = f"{key}="
        for v in values:
            if v.startswith(prefix):
                return v[len(prefix):]
        return None

    def get_alarm(data):
        alarm_registers = [
            1,	#Clock Board fault or not connected
            2,	#Extended memory fault
            3,	#Low outdoor temp. & Low ground temp.
            7,	#AI3 Probe failure. Compressor discharge pressure
            8,	#AI4 Probe failure. Brine outlet temperature
            9,	#AI5 Probe failure. Brine return temperature
            10,	#AI6 Probe failure. Brine circuit pressure
            11,	#AI7 Probe failure. Heating outlet temperature
            12,	#AI8 Probe failure. Heating inlet temperature
            13,	#AI9 Probe failure. Heating circuit pressure
            14,	#AI10 Probe failure. Tank temperature 1 (DHW)
            15,	#AI11 Probe failure. Outdoor temperature probe
            16,	#AI12 Probe fault
            17,	#Low brine inlet temperature
            18,	#High discharge pressure
            19,	#High discharge temperature
            20,	#Inverter temperature
            21,	#Low brine outlet temperature
            24,	#Ecogeo internal probes fault
            25,	#Low pressure brine circuit
            26,	#Low pressure Heating circuit
            33,	#Evaporation temperature
            34,	#Low suction pressure
            36,	#AI2 Probe failure Compressor suction Pressure
            37,	#AI1 Probe failure. Compressor suction temperature
            38,	#Low superheat (lowSH)
            39,	#Low evaporation temperature (LOP)
            40,	#High evaporation temperature (MOP)
            41,	#Low suction temperature
            212,	#Inverter comms fault
            213,	#High brine temperature
            214,	#pCOe number:AI13 Analog input probe on channel 1 disconnected or broken
            215,	#pCOe number:AI14 Analog input probe on channel 2 disconnected or broken
            216,	#pCOe number:AI15 Analog input probe on channel 3 disconnected or broken
            217,	#pCOe number:AI16 Analog input probe on channel 4 disconnected or broken
            218,	#pCOe number: pCOe offline
            219,	#th-T 1 Error (thermostat for DG1) **
            220,	#th-T 1 offline (thermostat for DG1) **
            221,	#th-T 2 Error (thermostat for SG2) **
            222,	#th-T 2 offline (thermostat for SG2) **
            223,	#th-T 3 Error (thermostat for SG3) **
            224,	#th-T 3 offline (thermostat for SG3) **
            225,	#th-T 4 Error (thermostat for SG4) **
            226,	#th-T 4 offline (thermostat for SG4) **
        ]

        for address in alarm_registers:
            if data[DataTypes.Coil][address] == "0":
                continue
            return address

        return 0
