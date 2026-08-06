"""Base Entity for Ecoforest."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import SensorDeviceClass, SensorEntityDescription, SensorStateClass
from homeassistant.const import UnitOfTemperature, UnitOfPower, UnitOfPressure, UnitOfEnergy
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription, generate_entity_id
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.typing import StateType

from .const import DOMAIN, MANUFACTURER
from .units import delta_unit_and_scale
from .coordinator import EcoforestCoordinator
from .overrides.device import EcoGeoDevice


SENSOR_TYPES = {
    "temperature": {"class": SensorDeviceClass.TEMPERATURE, "unit": UnitOfTemperature.CELSIUS, "state_class": SensorStateClass.MEASUREMENT},
    "pressure": {"class": SensorDeviceClass.PRESSURE, "unit": UnitOfPressure.BAR, "state_class": SensorStateClass.MEASUREMENT},
    "power": {"class": SensorDeviceClass.POWER, "unit": UnitOfPower.WATT, "state_class": SensorStateClass.MEASUREMENT},
    "measurement": {"state_class": SensorStateClass.MEASUREMENT},
    "enum": {"class": SensorDeviceClass.ENUM},
    "energy": {"class": SensorDeviceClass.ENERGY, "unit": UnitOfEnergy.KILO_WATT_HOUR, "state_class": SensorStateClass.TOTAL_INCREASING},
    # Temperature intervals: no device_class, because Home Assistant would
    # apply the affine absolute-temperature conversion. Unit and scale are
    # resolved per entity in EcoforestEntity.__init__.
    "temperature_delta": {"state_class": SensorStateClass.MEASUREMENT},
}


@dataclass(frozen=True, kw_only=True)
class EcoforestSensorEntityDescription(SensorEntityDescription):
    """Describes Ecoforest sensor entity."""

    value_fn: Callable[[EcoGeoDevice], StateType] | None = None
    scale: float = 1.0

class EcoforestEntity(CoordinatorEntity[EcoforestCoordinator]):
    """Common Ecoforest entity using CoordinatorEntity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EcoforestCoordinator,
        key: str,
        definition: dict[str, str],
        device_alias: str
    ) -> None:
        """Initialize device information."""

        if definition["entity_type"] == "temperature_delta":
            unit, scale = delta_unit_and_scale(
                coordinator.hass.config.units.temperature_unit
            )
            self.entity_description = EcoforestSensorEntityDescription(
                key=key,
                translation_key=key,
                native_unit_of_measurement=unit,
                state_class=SENSOR_TYPES["temperature_delta"]["state_class"],
                scale=scale,
            )
        elif definition["entity_type"] in SENSOR_TYPES.keys():
            self.entity_description = EcoforestSensorEntityDescription(
                key=key,
                translation_key=key,
                native_unit_of_measurement = SENSOR_TYPES[definition["entity_type"]]["unit"] if "unit" in SENSOR_TYPES[definition["entity_type"]].keys() else None,
                device_class = SENSOR_TYPES[definition["entity_type"]]["class"] if "class" in SENSOR_TYPES[definition["entity_type"]].keys() else None,
                state_class=SENSOR_TYPES[definition["entity_type"]]["state_class"] if "state_class" in SENSOR_TYPES[definition["entity_type"]].keys() else None
            )
        else:
            self.entity_description = EcoforestSensorEntityDescription(
                key=key,
                translation_key=key
            )

        device_id = coordinator.data.model_name if device_alias is None else device_alias
        device_name = MANUFACTURER if device_alias is None else device_alias

        if definition.get("is_number"):
            domain = "number"
        elif definition["entity_type"] == "switch":
            domain = "switch"
        elif definition["entity_type"] == "button":
            domain = "button"
        else:
            domain = "sensor"

        id = f"{device_id}_{key}".lower()
        self._attr_unique_id = id
        self.entity_id = f"{domain}.{id}"

        super().__init__(coordinator)


        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=device_name,
            model=coordinator.data.model_name,
            manufacturer=MANUFACTURER,
        )

    @property
    def data(self) -> EcoGeoDevice:
        """Return ecoforest data."""
        assert self.coordinator.data
        return self.coordinator.data
