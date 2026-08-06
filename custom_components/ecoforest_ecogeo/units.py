"""Unit arithmetic for temperature intervals.

Deliberately free of imports — including Home Assistant ones — so it can be
tested directly without stubs.
"""

from __future__ import annotations

CELSIUS = "°C"
FAHRENHEIT = "°F"

#: A temperature *interval* in Celsius scales to Fahrenheit by this factor.
#: There is no +32 offset: 10 °C of difference is 18 °F of difference, not 50.
CELSIUS_TO_FAHRENHEIT_INTERVAL = 1.8


def delta_unit_and_scale(temperature_unit: str) -> tuple[str, float]:
    """Return the reporting unit and scale factor for a Celsius interval.

    The Ecoforest API reports absolute temperatures in Celsius, so any
    difference between two of its readings is a Celsius interval. Home
    Assistant must not be asked to convert it: giving such a sensor
    ``device_class: temperature`` would apply the full affine transform
    (x1.8 +32), which is correct for a temperature and wrong for a
    difference between two temperatures.

    :param temperature_unit: the unit Home Assistant is configured to display,
        i.e. ``hass.config.units.temperature_unit``.
    :return: the unit string to report, and the factor to multiply by.

    This is called once from ``EcoforestEntity.__init__``, so the result is
    resolved at entity construction time and fixed for the entity's
    lifetime. If Home Assistant's unit system changes afterward, the
    delta-T sensors keep reporting the old unit until the integration is
    reloaded.
    """
    if str(temperature_unit) == FAHRENHEIT:
        return FAHRENHEIT, CELSIUS_TO_FAHRENHEIT_INTERVAL
    return CELSIUS, 1.0
