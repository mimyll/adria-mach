"""Native HOME master surfaces share one selected scalar route and stable identities."""

from .client.master import MasterControl
from .entity import MachEntity


def setup_master(entry, async_add_entities, factory):
    coordinator = entry.runtime_data
    added = False

    def discover():
        nonlocal added
        if not added and any(c.value in coordinator.data.control_snapshots for c in MasterControl):
            async_add_entities([factory(coordinator)])
            added = True

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class MachMasterEntity(MachEntity):
    @property
    def control(self):
        matches = [c for c in MasterControl if c.value in self.coordinator.data.control_snapshots]
        return matches[0] if len(matches) == 1 else None

    @property
    def reading(self):
        control = self.control
        return (
            self.coordinator.data.control_snapshots[control.value].observed[control.key]
            if control
            else None
        )

    @property
    def available(self):
        return self.coordinator.last_update_success and self.control is not None

    @property
    def extra_state_attributes(self):
        return {
            **super().extra_state_attributes,
            **self.coordinator.commands.attributes_for(self.control),
            "confirmation_scope": "reported_master_setting_only",
            "all_physical_lamps_observed": False,
        }

    async def request_master(self, target):
        control = self.control
        if control is None:
            raise self.coordinator.commands.error("control_preflight_failed")
        await self.coordinator.commands.set_manual(control, target)
