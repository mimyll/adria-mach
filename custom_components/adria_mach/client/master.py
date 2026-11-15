"""HOME Lights internal master: finite scalar dj routes, never a child-light fanout."""

from enum import Enum

from .outside import BLOCKS, LIS104, LIS112

MASTER_SCOPE_HASH = "051af2615d6f96e38e6c577df2f87e483b417495ab36b900809e03d00fe04af3"


class MasterControl(Enum):
    INTERNAL = "light-master-internal"
    GROUP = "light-master-group"

    @property
    def key(self):
        return (
            "INTERNAL_LIGHT_VALUE"
            if self is MasterControl.INTERNAL
            else "LIGHT_GROUP_INTERNAL_LIGHTS"
        )

    @property
    def individual_light(self):
        return False

    @property
    def seconds(self):
        return 30


def master_route(configuration):
    """Reject composite/ambiguous routes; never fall back from a broken selected alias."""
    devices = configuration.get("devices")
    configs = configuration.get("driverConfigs")
    definitions = configuration.get("values")
    if (
        not isinstance(devices, list)
        or any(type(d) is not str for d in devices)
        or len(set(devices)) != len(devices)
        or not isinstance(configs, list)
        or not isinstance(definitions, list)
    ):
        return None
    parameters = {}
    for row in configs:
        if (
            not isinstance(row, dict)
            or type(row.get("driver")) is not str
            or not isinstance(row.get("config"), dict)
            or row["driver"] in parameters
        ):
            return None
        parameters[row["driver"]] = row["config"]
    blocks = tuple(sorted(set(devices) & BLOCKS))
    context = {"master_blocks": blocks}
    combined = []
    for driver in sorted(set(devices) & (LIS104 | LIS112)):
        raw = parameters.get(driver, {}).get("lin")
        if type(raw) is int and raw in (0, 1, 2):
            lin = raw
        elif type(raw) is str and raw in ("0", "1", "2"):
            lin = int(raw)
        else:
            return None
        context[driver] = lin
        if blocks and lin == 2:
            combined.append(driver)
    if len(combined) > 1:
        return None
    ids = [d.get("id") for d in definitions if isinstance(d, dict)]
    internal = MasterControl.INTERNAL.key in ids
    group = MasterControl.GROUP.key in ids
    if combined and combined[0] in LIS104 and internal and group:
        return None  # Public ge/fX is an ordered two-write series, not this scalar contract.
    if combined and combined[0] in LIS112 and group:
        control = MasterControl.GROUP
    elif internal:
        control = MasterControl.INTERNAL
    else:
        return None
    context["master_route"] = control.value
    return control, context
