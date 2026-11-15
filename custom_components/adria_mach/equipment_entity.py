"""Shared native equipment eligibility and observed state, without command side effects."""

from .client.operational import CURRENT_CONTROLS
from .entity import MachEntity


def setup_equipment(entry, async_add_entities, domain, factory):
    coordinator = entry.runtime_data
    added = set()

    def discover():
        entities = []
        for control in CURRENT_CONTROLS:
            if control.domain != domain or control in added:
                continue
            if control.equipment and control.equipment not in coordinator.equipment:
                continue
            if control.value in coordinator.data.control_snapshots:
                entities.append(factory(coordinator, control))
                added.add(control)
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class MachEquipmentEntity(MachEntity):
    def __init__(self, coordinator, control, description):
        super().__init__(coordinator, description)
        self.control = control

    @property
    def snapshot(self):
        return self.coordinator.data.control_snapshots.get(self.control.value)

    @property
    def reading(self):
        return self.snapshot.observed[self.control.key] if self.snapshot else None

    @property
    def available(self):
        return self.coordinator.last_update_success and self.snapshot is not None

    @property
    def extra_state_attributes(self):
        return {
            **super().extra_state_attributes,
            **self.coordinator.commands.attributes_for(self.control),
        }

    async def request(self, value):
        await self.coordinator.commands.set_manual(self.control, value)
