"""Opt-in API 1 example. All values are FAKE; no hardware is accessed."""
from battery_dock.core import DeviceReading


class DemoPluginProvider:
    def poll(self):
        return [DeviceReading(
            device_id="fake-battery",
            name="DEMO fake battery",
            percent=73,
            charging=False,
            connected=True,
            detail="DEMO: simulated 73%; not a hardware measurement",
            estimated=False,
        )]

    def close(self):
        """Real providers should release their owned hardware handles here."""


def create_provider():
    return DemoPluginProvider()
