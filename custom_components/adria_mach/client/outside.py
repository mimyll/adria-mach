"""Finite outside routes from the raw configuration; no driver data is exported."""

from enum import Enum

OUTSIDE_SCOPE_HASH = "d69f7b9b3f63df872106b5ea13e8cef13087d8bc12a8261fef2d38b949441395"


class OutsideControl(Enum):
    BINARY = "outside-binary"
    LIS112 = "outside-lis112-brightness"
    LIS104 = "outside-lis104-brightness"

    @property
    def key(self):
        return {
            self.BINARY: "EXTERNAL_LIGHT_VALUE",
            self.LIS112: "LIGHT_GROUP_10_BRIGHTNESS",
            self.LIS104: "LIGHT_GROUP_EXTERNAL_LIGHTS_BRIGHTNESS",
        }[self]

    @property
    def individual_light(self):
        return self is not self.BINARY

    @property
    def seconds(self):
        return 30


LIS112 = frozenset(
    (
        "SCHAUDT_LIGHT_SYSTEM_LIS_112",
        "SCHAUDT_LIGHT_SYSTEM_LIS112_V1",
        "SCHAUDT_LIGHT_SYSTEM_LIS112_V2",
    )
)
LIS104 = frozenset(
    (
        "SCHAUDT_LIGHT_SYSTEM_LIS_104",
        "SCHAUDT_LIGHT_SYSTEM_LIS104_V1",
        "SCHAUDT_LIGHT_SYSTEM_LIS104_V2",
    )
)
BLOCKS = frozenset(
    (
        "SCHAUDT_ELECTROBLOCK_CSV416",
        "SCHAUDT_EBL_CSV416",
        "SCHAUDT_ELECTROBLOCK_EBL227",
        "SCHAUDT_EBL_EBL227",
        "NORDELETTRONICA_NE350_ELECTROBLOCK",
        "NORDELETTRONICA_EBL_NE350",
    )
)


def outside_route(configuration):
    """Mirror public _j on supported inputs; ambiguous metadata grants no route.

    Public app IW maps raw devices/driverConfigs to drivers/a keyed map. Unlike
    its parseInt/last-wins behavior, accept only unambiguous lin0/1/2 and rows.
    Outside selection has no unit-type predicate.
    """
    devices = configuration.get("devices")
    configs = configuration.get("driverConfigs")
    values = configuration.get("values")
    if (
        not isinstance(devices, list)
        or any(type(d) is not str for d in devices)
        or len(devices) != len(set(devices))
        or not isinstance(configs, list)
        or not isinstance(values, list)
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
    lights = tuple(sorted(set(devices) & (LIS112 | LIS104)))
    context = {"outside_blocks": blocks}
    combined = []
    for driver in lights:
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
        return None  # Multiple controllers are outside this reviewed routing contract.
    selected = OutsideControl.BINARY
    if combined:
        candidate = OutsideControl.LIS104 if combined[0] in LIS104 else OutsideControl.LIS112
        matches = [v for v in values if isinstance(v, dict) and v.get("id") == candidate.key]
        if matches:
            if len(matches) != 1 or not isinstance(matches[0].get("config"), dict):
                return None
            if matches[0]["config"].get("type") != "integer":
                return None  # A broken selected numeric route must not fall back to binary.
            selected = candidate
    context["outside_route"] = selected.value
    return selected, context
