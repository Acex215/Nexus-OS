import unittest

from satnogsclient.observer.observer import rx_device_for_frequency


class RXDeviceForFrequency(unittest.TestCase):

    def test_invalid_value(self):
        self.assertRaises(ValueError, rx_device_for_frequency, 'missing colon', 1)
        self.assertRaises(
            ValueError,
            rx_device_for_frequency,
            'invalid_range:device1 100-200:device2',
            1,
        )

    def test_several_specs(self):
        # IN (spec, frequency) / OUT (device_expected)
        fixtures = [
            # No device for freq (--> LookupError)
            (('100-200:device1 200-300:device2', 1000), None),
            # Single device
            (('device1', 100 * 10**6), 'device1'),
            # First device is selected
            (('100-200:device1 100-200:device2', 100 * 10**6), 'device1'),
            # Second device is selected
            (('100-200:device1 200-300:device2 300-400:d3', 250.0 * 10**6), 'device2'),
            # Second device is selected, with colon in the device string
            (
                (
                    '100-120:device1 120-170:driver=remote,remote:driver=lime',
                    130 * 10**6,
                ),
                'driver=remote,remote:driver=lime',
            ),
        ]

        for idx, ((rx_device_spec, freq), device_expected) in enumerate(fixtures):
            if device_expected:
                device_actual = rx_device_for_frequency(rx_device_spec, freq)
                self.assertEqual(device_actual, device_expected, f'Fixture {idx} failed.')
            else:
                self.assertRaises(LookupError, rx_device_for_frequency, rx_device_spec, freq)
