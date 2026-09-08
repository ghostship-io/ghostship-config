import unittest

from engineio.packet import MESSAGE, Packet
from engineio.payload import Payload
from test_config import load

load("monitoring_provision", "modules/self-hosted/monitoring-provision.py")


class MonitoringTests(unittest.TestCase):
    def test_populated_fleet_login_burst_can_be_decoded(self):
        # Login sends multiple heartbeat/stat events per monitor before its ACK.
        burst = Payload(
            packets=[Packet(MESSAGE, data="fleet-event") for _ in range(128)]
        )
        decoded = Payload(encoded_payload=burst.encode())
        self.assertEqual(len(decoded.packets), 128)
        self.assertTrue(all(packet.data == "fleet-event" for packet in decoded.packets))
