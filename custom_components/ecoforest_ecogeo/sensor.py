"""Support for Ecoforest sensors."""

from __future__ import annotations

import logging
from functools import cached_property

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ALIAS
from homeassistant.helpers.typing import StateType

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EcoforestCoordinator
from .entity import EcoforestEntity, EcoforestSensorEntityDescription
from .overrides.device import EcoGeoDevice
from .overrides.api import MAPPING
from .entity import SENSOR_TYPES

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Ecoforest sensor platform."""
    coordinator: EcoforestCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    device_alias = config_entry.data[CONF_ALIAS] if CONF_ALIAS in config_entry.data else None
    entities = [
        EcoforestSensor(coordinator, key, definition, device_alias)
        for key, definition in MAPPING.items()
        if definition["entity_type"] in SENSOR_TYPES.keys()
        and not definition.get("is_number")
    ]

    async_add_entities(entities)


class EcoforestSensor(SensorEntity, EcoforestEntity):
    """Representation of an Ecoforest sensor."""
    entity_description: EcoforestSensorEntityDescription

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        if self.entity_description.value_fn is not None:
            value = self.entity_description.value_fn(self.data)
        else:
            value = self.data.state[self.entity_description.key]

        if value is not None and self.entity_description.scale != 1.0:
            return round(value * self.entity_description.scale, 2)

        return value
