"""Strict optional backend metadata; cloud receipt and device contact stay distinct."""

from datetime import UTC, datetime


class ConnectionMetadata:
    def __init__(self):
        self.connected = None
        self.initialized = None
        self.last_contact = None

    def observe(self, event):
        if not isinstance(event, dict) or event.get("type") != "bcknd-msg":
            return
        message = event.get("payload")
        if not isinstance(message, dict) or message.get("type") != "mach-conn":
            return
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return
        for key, attribute in (("connected", "connected"), ("initialized", "initialized")):
            if key in payload:
                setattr(self, attribute, payload[key] if type(payload[key]) is bool else None)
        if "lastContactUTC" in payload:
            value = payload["lastContactUTC"]
            now = datetime.now(UTC)
            self.last_contact = (
                datetime.fromtimestamp(value / 1000, UTC)
                if type(value) is int and 946684800000 <= value <= now.timestamp() * 1000
                else None
            )

    def facts(self):
        return {
            "reported_device_connected": self.connected,
            "reported_cache_initialized": self.initialized,
            "reported_device_contact_at": self.last_contact.isoformat()
            if self.last_contact
            else None,
            "device_sample_at": None,
            "source_contact_contract": "optional_portal_epoch_milliseconds",
        }
