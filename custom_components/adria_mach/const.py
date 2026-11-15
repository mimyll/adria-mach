"""Verified integration identifiers and chosen polling policy."""

DOMAIN = "adria_mach"
CONF_MACH_ID = "mach_id"
VALUE_ID = "LIVING_MEASURED_TEMPERATURE"
UPDATE_SECONDS = 300
CONF_ONOFF_LIGHTS = "onoff_lights"
LIGHT_OPTIONS = tuple(f"light-group-{i}" for i in range(1, 9)) + ("outside-light",)
CONF_EQUIPMENT = "identified_equipment"
EQUIPMENT_OPTIONS = ("aux", "alde", "air_conditioning")
