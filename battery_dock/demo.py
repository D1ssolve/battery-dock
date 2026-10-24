from .core import DeviceReading

class DemoProvider:
    def poll(self):
        return [DeviceReading('demo-g733', 'Logitech G733 · ДЕМО', 76),
                DeviceReading('demo-aerox9', 'SteelSeries Aerox 9 · ДЕМО', 18)]

    def close(self):
        pass
