"""Native light feedback follows admitted requests; observations remain separate."""

from homeassistant.components.light import ColorMode, LightEntity, LightEntityDescription

from .client.control_model import (
    OFF_LEVEL,
    Case,
    ControlError,
    ManualControl,
    brightness_to_level,
    level_to_brightness,
)
from .client.outside import OutsideControl
from .entity import MachEntity
from .master_entity import MachMasterEntity, setup_master

DESCRIPTION = LightEntityDescription(key="EXTERNAL_LIGHT_VALUE", translation_key="outside_light")
DESCRIPTIONS = ((Case.LIGHT, DESCRIPTION),) + tuple(
    (case, LightEntityDescription(key=case.key, translation_key=case.value.replace("-", "_")))
    for case in Case
    if case.individual_light
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        [
            MachLight(coordinator, description, case)
            for case, description in DESCRIPTIONS
            if case.value in coordinator.data.control_snapshots
            or (
                case is Case.LIGHT
                and any(c.value in coordinator.data.control_snapshots for c in OutsideControl)
            )
        ]
    )
    setup_master(entry, async_add_entities, MachLightMaster)


class PendingLightDisplay:
    """Transient native display only; never mutate observations or dispatch commands."""

    @property
    def pending_request(self):
        return self.coordinator.commands.pending_for(self.request_control)

    @property
    def is_on(self):
        pending = self.pending_request
        if pending is None:
            return self.reported_is_on
        target = pending.target[0]
        if target is None:  # Bare ON does not supply a brightness level.
            return True
        return (
            target != OFF_LEVEL
            if getattr(self.request_control, "individual_light", False)
            else target == "on"
        )

    @property
    def extra_state_attributes(self):
        attributes = super().extra_state_attributes
        if self.request_control is None:
            return attributes
        return {
            **attributes,
            "reported_state": None
            if self.reported_is_on is None
            else "on"
            if self.reported_is_on
            else "off",
            "display_state_source": "requested" if self.pending_request is not None else "reported",
        }


class MachLight(PendingLightDisplay, MachEntity, LightEntity):
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    def __init__(self, coordinator, description, case):
        super().__init__(coordinator, description)
        self.case = case
        if case.individual_light:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS

    @property
    def outside_control(self):
        if self.case is Case.LIGHT:
            return next(
                (c for c in OutsideControl if c.value in self.coordinator.data.control_snapshots),
                None,
            )
        return None

    @property
    def dimmable(self):
        return self.case.value not in self.coordinator.onoff_lights and (
            self.case.individual_light
            or (self.outside_control is not None and self.outside_control.individual_light)
        )

    @property
    def supported_color_modes(self):
        return {ColorMode.BRIGHTNESS} if self.dimmable else {ColorMode.ONOFF}

    @property
    def color_mode(self):
        return ColorMode.BRIGHTNESS if self.dimmable else ColorMode.ONOFF

    @property
    def available(self):
        if self.case is Case.LIGHT:
            return self.coordinator.last_update_success and self.outside_control is not None
        return super().available and self.case.value in self.coordinator.data.control_snapshots

    @property
    def request_control(self):
        return self.outside_control if self.case is Case.LIGHT else self.case

    @property
    def reported_is_on(self):
        if self.case is Case.LIGHT:
            control = self.outside_control
            if control is None:
                return None
            value = self.coordinator.data.control_snapshots[control.value].observed[control.key]
            return value != OFF_LEVEL if control.individual_light else value == "on"
        return self.reading

    @property
    def reported_brightness(self):
        if not self.dimmable or not self.available:
            return None
        if self.case is Case.LIGHT:
            control = self.outside_control
            return level_to_brightness(
                self.coordinator.data.control_snapshots[control.value].observed[control.key]
            )
        return level_to_brightness(
            self.coordinator.data.control_snapshots[self.case.value].observed[self.case.key]
        )

    @property
    def brightness(self):
        if not self.dimmable or not self.available:
            return None
        pending = self.pending_request
        if pending is not None and pending.target[0] is not None:
            return level_to_brightness(pending.target[0])
        return self.reported_brightness

    @property
    def extra_state_attributes(self):
        return {
            **super().extra_state_attributes,
            **self.coordinator.commands.attributes_for(self.outside_control or self.case),
            "reported_brightness": self.reported_brightness,
        }

    async def async_turn_on(self, **kwargs):
        if self.case is Case.LIGHT:
            await self._outside(True, kwargs)
            return
        if self.case.individual_light:
            if set(kwargs) - ({"brightness"} if self.dimmable else set()):
                raise self.coordinator.commands.error("invalid_control_value")
            try:
                target = (
                    brightness_to_level(kwargs["brightness"]) if "brightness" in kwargs else None
                )
            except ControlError:
                raise self.coordinator.commands.error("invalid_control_value") from None
            await self.coordinator.commands.set_manual(
                ManualControl("manual-" + self.case.value), target, coalesce="brightness" in kwargs
            )
            return
        if kwargs:
            raise self.coordinator.commands.error("invalid_control_value")
        await self.coordinator.commands.set(self.case, self.case.target)

    async def async_turn_off(self, **kwargs):
        if kwargs:
            raise self.coordinator.commands.error("invalid_control_value")
        if self.case is Case.LIGHT:
            if self.coordinator.commands.restoration_required and (
                self.coordinator.commands.journal.state["pending"]["case"] == Case.LIGHT.value
            ):
                await self.coordinator.commands.set(Case.LIGHT, Case.LIGHT.baseline)
            else:
                await self._outside(False, {})
            return
        if self.case.individual_light:
            await self.coordinator.commands.set_manual(
                ManualControl("manual-" + self.case.value), self.case.baseline
            )
        else:
            await self.coordinator.commands.set(self.case, self.case.baseline)

    async def _outside(self, on, kwargs):
        control = self.outside_control
        if control is None:
            raise self.coordinator.commands.error("control_preflight_failed")
        if set(kwargs) - {"brightness"} or (kwargs and not self.dimmable):
            raise self.coordinator.commands.error("invalid_control_value")
        try:
            target = (
                (
                    brightness_to_level(kwargs["brightness"])
                    if "brightness" in kwargs
                    else None
                    if on
                    else OFF_LEVEL
                )
                if control.individual_light
                else "on"
                if on
                else "off"
            )
        except ControlError:
            raise self.coordinator.commands.error("invalid_control_value") from None
        await self.coordinator.commands.set_manual(control, target, coalesce="brightness" in kwargs)


class MachLightMaster(PendingLightDisplay, MachMasterEntity, LightEntity):
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    def __init__(self, coordinator):
        super().__init__(
            coordinator, LightEntityDescription(key="light_master", translation_key="light_master")
        )

    @property
    def request_control(self):
        return self.control

    @property
    def reported_is_on(self):
        return self.reading == "on" if self.reading is not None else None

    async def async_turn_on(self, **kwargs):
        if kwargs:
            raise self.coordinator.commands.error("invalid_control_value")
        await self.request_master("on")

    async def async_turn_off(self, **kwargs):
        if kwargs:
            raise self.coordinator.commands.error("invalid_control_value")
        await self.request_master("off")
