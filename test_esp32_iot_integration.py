import os
import json
import time
import socket
import unittest
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from iot_service import IoTAttendanceService
import database

# Mock ESP32 Server to simulate physical ESP32 DevKit V1 behavior in test environment
class MockESP32Handler(BaseHTTPRequestHandler):
    events_received = []
    auth_header_checked = []
    status_checks = 0
    secret = "campus_sync_iot_secret_2026"

    def do_GET(self):
        auth_header = self.headers.get('X-ESP32-Secret', '')
        MockESP32Handler.auth_header_checked.append(auth_header)

        if auth_header != MockESP32Handler.secret and not self.path.endswith(f"?secret={MockESP32Handler.secret}"):
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error": "Unauthorized"}')
            return

        if self.path.startswith('/api/status') or self.path == '/':
            MockESP32Handler.status_checks += 1
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            resp = {
                "device": "ESP32_DEVKIT_V1",
                "system": "Mock ESP32 Node",
                "status": "online",
                "ip": "127.0.0.1",
                "uptime_seconds": 42,
                "led_green": "OFF",
                "led_red": "OFF",
                "buzzer": "IDLE"
            }
            self.wfile.write(json.dumps(resp).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        auth_header = self.headers.get('X-ESP32-Secret', '')
        MockESP32Handler.auth_header_checked.append(auth_header)

        if auth_header != MockESP32Handler.secret:
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error": "Unauthorized"}')
            return

        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        try:
            event = json.loads(post_data.decode('utf-8'))
            MockESP32Handler.events_received.append(event)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"success": true, "status": "processed"}')
        except Exception as e:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress noisy standard HTTP logs during tests
        pass

class TestESP32IoTIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Find a free local port for the mock ESP32 server
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('127.0.0.1', 0))
        cls.mock_port = sock.getsockname()[1]
        sock.close()

        cls.mock_host = f"http://127.0.0.1:{cls.mock_port}"
        cls.server = HTTPServer(('127.0.0.1', cls.mock_port), MockESP32Handler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        MockESP32Handler.events_received.clear()
        MockESP32Handler.auth_header_checked.clear()
        MockESP32Handler.status_checks = 0

        # Reset env vars
        for k in ['CAMPUS_SYNC_ESP32_ENABLED', 'CAMPUS_SYNC_ESP32_HOST', 'CAMPUS_SYNC_ESP32_SECRET', 'CAMPUS_SYNC_ESP32_TIMEOUT']:
            if k in os.environ:
                del os.environ[k]

    def test_01_optional_when_unconfigured(self):
        """Hardware must be completely optional when unconfigured; attendance and simulation still succeed."""
        os.environ['CAMPUS_SYNC_ESP32_ENABLED'] = 'false'
        status = IoTAttendanceService.get_connection_status(force_refresh=True)
        self.assertEqual(status['status'], 'not_configured')
        self.assertFalse(status['configured'])

        # Recording event should succeed instantly (Present: Green LED ON, Buzzer Silent)
        event = IoTAttendanceService.record_event('VERIFIED', student_id=8, student_name="Priyanka Saini", roll_number="CS-101")
        self.assertEqual(event['event'], 'VERIFIED')
        self.assertEqual(event['led'], 'GREEN')
        self.assertEqual(event['buzzer_beeps'], 0)
        self.assertEqual(event['buzzer'], 'IDLE')

        # No network calls to mock server should have occurred
        time.sleep(0.1)
        self.assertEqual(len(MockESP32Handler.events_received), 0)

    def test_02_connection_status_connected_when_online(self):
        """When ESP32 host is configured and reachable, status reports connected."""
        os.environ['CAMPUS_SYNC_ESP32_ENABLED'] = 'true'
        os.environ['CAMPUS_SYNC_ESP32_HOST'] = self.mock_host
        os.environ['CAMPUS_SYNC_ESP32_SECRET'] = 'campus_sync_iot_secret_2026'

        status = IoTAttendanceService.get_connection_status(force_refresh=True)
        self.assertEqual(status['status'], 'connected')
        self.assertTrue(status['configured'])
        self.assertIn('device_info', status)
        self.assertEqual(status['device_info'].get('device'), 'ESP32_DEVKIT_V1')

    def test_03_present_event_dispatched_with_auth_and_uuid(self):
        """Verified / Present attendance dispatches PRESENT event to ESP32 with auth header and UUID."""
        os.environ['CAMPUS_SYNC_ESP32_ENABLED'] = 'true'
        os.environ['CAMPUS_SYNC_ESP32_HOST'] = self.mock_host
        os.environ['CAMPUS_SYNC_ESP32_SECRET'] = 'campus_sync_iot_secret_2026'

        IoTAttendanceService.record_event('VERIFIED', student_id=1057, student_name="Priyanka Saini", roll_number="CS-202")

        # Allow daemon worker thread to deliver payload
        time.sleep(0.3)

        self.assertEqual(len(MockESP32Handler.events_received), 1)
        ev = MockESP32Handler.events_received[0]
        self.assertEqual(ev['type'], 'PRESENT')
        self.assertEqual(ev['student_name'], 'Priyanka Saini')
        self.assertEqual(ev['roll_number'], 'CS-202')
        self.assertTrue(len(ev['event_id']) > 10, "Unique event_id UUID must be present")
        self.assertIn('campus_sync_iot_secret_2026', MockESP32Handler.auth_header_checked)

    def test_04_absent_event_dispatched(self):
        """Explicitly marked Absent attendance dispatches ABSENT event to ESP32."""
        os.environ['CAMPUS_SYNC_ESP32_ENABLED'] = 'true'
        os.environ['CAMPUS_SYNC_ESP32_HOST'] = self.mock_host
        os.environ['CAMPUS_SYNC_ESP32_SECRET'] = 'campus_sync_iot_secret_2026'

        IoTAttendanceService.record_event('ABSENT', student_id=8, student_name="Test Student", roll_number="CS-08")

        time.sleep(0.3)

        self.assertEqual(len(MockESP32Handler.events_received), 1)
        ev = MockESP32Handler.events_received[0]
        self.assertEqual(ev['type'], 'ABSENT')
        self.assertEqual(ev['student_name'], 'Test Student')

    def test_05_unrecognized_duplicate_do_not_trigger_hardware_green_or_buzzer(self):
        """Unrecognized and Duplicate events do NOT dispatch PRESENT to ESP32 hardware."""
        os.environ['CAMPUS_SYNC_ESP32_ENABLED'] = 'true'
        os.environ['CAMPUS_SYNC_ESP32_HOST'] = self.mock_host

        IoTAttendanceService.record_event('UNRECOGNIZED', error_detail="Cosine similarity below threshold")
        IoTAttendanceService.record_event('DUPLICATE', student_id=8, student_name="Priyanka Saini")

        time.sleep(0.3)

        # Neither UNRECOGNIZED nor DUPLICATE dispatches hardware event
        self.assertEqual(len(MockESP32Handler.events_received), 0)

    def test_06_offline_resilience_and_timeout_isolation(self):
        """When ESP32 host is offline or unreachable, system fails gracefully without blocking or throwing."""
        # Point to an unreachable port on localhost
        os.environ['CAMPUS_SYNC_ESP32_ENABLED'] = 'true'
        os.environ['CAMPUS_SYNC_ESP32_HOST'] = 'http://127.0.0.1:59998'
        os.environ['CAMPUS_SYNC_ESP32_TIMEOUT'] = '0.3'

        start_time = time.time()
        # record_event must return immediately (non-blocking async dispatch)
        event = IoTAttendanceService.record_event('VERIFIED', student_id=8, student_name="Priyanka Saini")
        elapsed = time.time() - start_time

        self.assertLess(elapsed, 0.1, "record_event must be non-blocking and return in under 100ms")
        self.assertEqual(event['led'], 'GREEN')

        # Connection status should indicate disconnected
        status = IoTAttendanceService.get_connection_status(force_refresh=True)
        self.assertEqual(status['status'], 'disconnected')

    def test_07_heartbeat_unauthorized_rejection(self):
        """Heartbeat requests with invalid or missing secret must return 401 Unauthorized."""
        os.environ['CAMPUS_SYNC_ESP32_SECRET'] = 'campus_sync_iot_secret_2026'

        # Wrong secret
        success, resp, code = IoTAttendanceService.receive_heartbeat(
            data={'ip': '192.168.1.55'},
            remote_addr='192.168.1.55',
            auth_secret='wrong_secret'
        )
        self.assertFalse(success)
        self.assertEqual(code, 401)
        self.assertIn('Unauthorized', resp.get('error', ''))

    def test_08_heartbeat_authorized_and_event_delivery(self):
        """Authorized heartbeat updates node connectivity and retrieves queued events."""
        os.environ['CAMPUS_SYNC_ESP32_ENABLED'] = 'true'
        os.environ['CAMPUS_SYNC_ESP32_SECRET'] = 'campus_sync_iot_secret_2026'

        # Dispatch an event while direct host is empty or unreachable
        IoTAttendanceService.record_event('VERIFIED', student_id=1057, student_name="Priyanka Saini", roll_number="CS-202")

        # ESP32 sends periodic heartbeat
        success, resp, code = IoTAttendanceService.receive_heartbeat(
            data={'device': 'ESP32_DEVKIT_V1', 'ip': '192.168.1.55', 'port': 8080},
            remote_addr='192.168.1.55',
            auth_secret='campus_sync_iot_secret_2026'
        )

        self.assertTrue(success)
        self.assertEqual(code, 200)
        self.assertEqual(resp.get('status'), 'ok')
        # Queued event should be delivered in response
        self.assertEqual(resp.get('type'), 'PRESENT')
        self.assertEqual(resp.get('student_name'), 'Priyanka Saini')

        # Status should report connected
        conn = IoTAttendanceService.get_connection_status()
        self.assertEqual(conn['status'], 'connected')

    def test_09_hardware_pins_configuration(self):
        """Verifies hardware configuration strictly matches specified physical wiring."""
        config = IoTAttendanceService.load_config()
        hw = config.get('hardware', {})
        self.assertEqual(hw.get('pin_green_led'), 26, "Green LED must be assigned to GPIO 26")
        self.assertEqual(hw.get('pin_red_led'), 27, "Red LED must be assigned to GPIO 27")
        self.assertEqual(hw.get('pin_buzzer'), 25, "Buzzer must be assigned to GPIO 25")
        self.assertIn('ESP32 DevKit V1', hw.get('board', ''))

    def test_10_absent_event_triggers_buzzer_beep(self):
        """Absent event triggers Red LED and Buzzer Beep per Section 3.B.2."""
        event = IoTAttendanceService.record_event('ABSENT', student_id=8, student_name="Rajni Mehra", roll_number="CS-108")
        self.assertEqual(event['led'], 'RED')
        self.assertEqual(event['led_red'], 'ON')
        self.assertEqual(event['led_green'], 'OFF')
        self.assertEqual(event['buzzer'], 'BEEP')
        self.assertEqual(event['buzzer_beeps'], 1)

    def test_11_unrecognized_never_triggers_hardware(self):
        """Unrecognized faces never dispatch hardware events (no PRESENT, no ABSENT) to ESP32 per Section 3.C."""
        MockESP32Handler.events_received.clear()
        event = IoTAttendanceService.record_event('UNRECOGNIZED', error_detail="Low cosine similarity")
        self.assertEqual(event['event'], 'UNRECOGNIZED')
        self.assertEqual(event['led'], 'RED')
        self.assertEqual(event['led_red'], 'ON')
        self.assertEqual(event['led_green'], 'OFF')
        self.assertEqual(event['buzzer'], 'IDLE')
        self.assertEqual(event['buzzer_beeps'], 0)
        time.sleep(0.1)
        self.assertEqual(len(MockESP32Handler.events_received), 0, "Hardware must NOT receive any event on unrecognized")

    def test_12_present_event_buzzer_is_silent(self):
        """Verified / Present attendance triggers Green LED ON and Buzzer strictly SILENT per Section 3."""
        event = IoTAttendanceService.record_event('VERIFIED', student_id=1057, student_name="Priyanka Saini", roll_number="19")
        self.assertEqual(event['led'], 'GREEN')
        self.assertEqual(event['led_green'], 'ON')
        self.assertEqual(event['led_red'], 'OFF')
        self.assertEqual(event['buzzer'], 'IDLE')
        self.assertEqual(event['buzzer_beeps'], 0)

    def test_13_teacher_iot_dashboard_route_and_template(self):
        """Teacher IoT dashboard renders with live telemetry, pinout, and testing controls."""
        import app
        with app.app.test_client() as client:
            with client.session_transaction() as sess:
                sess['teacher_id'] = 5
                sess['user_type'] = 'teacher'
                sess['teacher_name'] = 'Rajesh Lohani'
                sess['role'] = 'teacher'
            resp = client.get('/teacher/iot')
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn('ESP32 IoT Device Integration', html)
            self.assertIn('GPIO 26', html)
            self.assertIn('GPIO 27', html)
            self.assertIn('GPIO 25', html)
            self.assertIn('Hardware Self-Test Actions', html)

if __name__ == '__main__':
    unittest.main()
