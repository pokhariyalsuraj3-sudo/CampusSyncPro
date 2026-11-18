import os
import json
import uuid
import time
import logging
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger('campus_sync.iot')

class IoTAttendanceService:
    """
    Modular interface for ESP32 DevKit V1 integration (Green LED, Red LED, Buzzer).
    - 100% OPTIONAL: Does NOT require physical hardware to be connected or configured.
    - Zero blocking: Network requests to ESP32 run in background daemon threads.
    - Preserves simulation state and backwards-compatible API for existing modules and tests.
    """

    _lock = threading.Lock()
    _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='ESP32_IoT_Worker')

    # Simulation state dictionary (fully backward-compatible)
    _last_event = {
        'device_id': 'ESP32_DEVKIT_V1',
        'event': 'IDLE',
        'last_event': 'IDLE',
        'status': 'READY',
        'student_id': None,
        'student_name': None,
        'roll_number': None,
        'led': 'OFF',           # 'GREEN', 'RED', 'OFF'
        'led_green': 'OFF',
        'led_red': 'OFF',
        'buzzer': 'IDLE',
        'buzzer_beeps': 0,     # 1 for success, 2 for failed
        'error_detail': None,
        'timestamp': datetime.now().isoformat()
    }

    # Connection status cache
    _connection_cache = {
        'status': 'not_configured',  # 'connected', 'disconnected', 'not_configured'
        'configured': False,
        'host': '',
        'last_checked': 0.0,
        'message': 'ESP32 not configured'
    }

    # Queue of pending hardware events for ESP32 polling / heartbeat delivery
    _pending_events = []
    _last_heartbeat_time = 0.0
    _discovered_esp32_host = ''

    @classmethod
    def load_config(cls):
        """Loads configuration from iot_config.json and environment variable overrides."""
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'iot_config.json')
        config = {
            'esp32_enabled': False,
            'esp32_host': '',
            'esp32_secret': 'campus_sync_iot_secret_2026',
            'request_timeout_seconds': 1.0,
            'hardware': {
                'board': 'ESP32 DevKit V1 (30-pin USB-C)',
                'pin_green_led': 26,
                'pin_red_led': 27,
                'pin_buzzer': 25,
                'buzzer_is_active': True
            }
        }

        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    file_conf = json.load(f)
                    config.update(file_conf)
            except Exception as e:
                logger.warning(f"[ESP32 IoT] Error reading iot_config.json: {e}")

        # Environment variable overrides
        if 'CAMPUS_SYNC_ESP32_ENABLED' in os.environ:
            config['esp32_enabled'] = os.environ.get('CAMPUS_SYNC_ESP32_ENABLED', '').lower() in ('1', 'true', 'yes')
        if 'CAMPUS_SYNC_ESP32_HOST' in os.environ:
            config['esp32_host'] = os.environ.get('CAMPUS_SYNC_ESP32_HOST', '')
        if 'CAMPUS_SYNC_ESP32_SECRET' in os.environ:
            config['esp32_secret'] = os.environ.get('CAMPUS_SYNC_ESP32_SECRET', '')
        if 'CAMPUS_SYNC_ESP32_TIMEOUT' in os.environ:
            try:
                config['request_timeout_seconds'] = float(os.environ.get('CAMPUS_SYNC_ESP32_TIMEOUT', 1.0))
            except ValueError:
                pass

        return config

    @classmethod
    def get_connection_status(cls, force_refresh=False):
        """
        Returns connection state to ESP32: 'connected', 'disconnected', or 'not_configured'.
        Caches result for 5 seconds to avoid flooding the network or ESP32 node.
        """
        config = cls.load_config()
        enabled = config.get('esp32_enabled', False)
        host = (config.get('esp32_host') or cls._discovered_esp32_host or '').strip().rstrip('/')

        now = time.time()
        has_recent_heartbeat = (now - cls._last_heartbeat_time) < 15.0

        if not enabled and not has_recent_heartbeat:
            with cls._lock:
                cls._connection_cache = {
                    'status': 'not_configured',
                    'configured': False,
                    'host': host,
                    'last_checked': now,
                    'message': 'ESP32 is not enabled in iot_config.json.'
                }
            return dict(cls._connection_cache)

        # Check if we have received an active heartbeat within the last 15 seconds
        with cls._lock:
            if has_recent_heartbeat:
                cls._connection_cache = {
                    'status': 'connected',
                    'configured': True,
                    'host': host or cls._discovered_esp32_host,
                    'last_checked': now,
                    'message': 'ESP32 node online via active heartbeat',
                    'device_info': {
                        'heartbeat_age_seconds': round(now - cls._last_heartbeat_time, 1)
                    }
                }
                return dict(cls._connection_cache)

            if not force_refresh and (now - cls._connection_cache.get('last_checked', 0) < 5.0):
                return dict(cls._connection_cache)

        # If no host is specified and no heartbeat received
        if not host:
            with cls._lock:
                cls._connection_cache = {
                    'status': 'disconnected',
                    'configured': True,
                    'host': '',
                    'last_checked': now,
                    'message': 'ESP32 enabled but no host configured or heartbeat received.'
                }
                return dict(cls._connection_cache)

        # Lightweight check: GET <host>/api/status with short timeout
        import urllib.request
        import urllib.error

        url = f"{host}/api/status"
        timeout = float(config.get('request_timeout_seconds', 1.0))
        secret = config.get('esp32_secret', '')

        status_result = 'disconnected'
        msg = 'Connection timed out or host unreachable'
        device_info = {}

        try:
            req = urllib.request.Request(url, headers={'X-ESP32-Secret': secret, 'User-Agent': 'CampusSync-Flask'})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status == 200:
                    status_result = 'connected'
                    msg = 'ESP32 node online and responsive'
                    try:
                        device_info = json.loads(response.read().decode('utf-8'))
                    except Exception:
                        pass
                else:
                    msg = f"HTTP {response.status} from ESP32"
        except urllib.error.HTTPError as e:
            if e.code == 401:
                status_result = 'disconnected'
                msg = 'ESP32 Secret authentication rejected (401)'
            else:
                status_result = 'disconnected'
                msg = f"HTTP error {e.code}"
        except Exception as e:
            status_result = 'disconnected'
            msg = f"ESP32 offline or unreachable ({type(e).__name__})"

        with cls._lock:
            cls._connection_cache = {
                'status': status_result,
                'configured': True,
                'host': host,
                'last_checked': now,
                'message': msg,
                'device_info': device_info
            }
            return dict(cls._connection_cache)

    @classmethod
    def receive_heartbeat(cls, data=None, remote_addr='', auth_secret=''):
        """
        Processes an incoming heartbeat from physical ESP32 node.
        Validates secret, refreshes connection status, and returns any queued attendance events.
        """
        config = cls.load_config()
        expected_secret = config.get('esp32_secret', '')

        token = auth_secret or (data or {}).get('secret', '')
        if expected_secret and token != expected_secret:
            logger.warning("[ESP32 IoT] Rejected heartbeat: invalid secret")
            return False, {"error": "Unauthorized", "message": "Invalid ESP32 Secret"}, 401

        now = time.time()
        ip = (data or {}).get('ip') or remote_addr
        port = (data or {}).get('port', 8080)
        discovered_host = f"http://{ip}:{port}" if ip else ''

        with cls._lock:
            cls._last_heartbeat_time = now
            if discovered_host:
                cls._discovered_esp32_host = discovered_host

            # Pop any pending attendance event to deliver via heartbeat
            pending_event = None
            if cls._pending_events:
                pending_event = cls._pending_events.pop(0)

            cls._connection_cache = {
                'status': 'connected',
                'configured': True,
                'host': config.get('esp32_host') or cls._discovered_esp32_host,
                'last_checked': now,
                'message': 'ESP32 node online via active heartbeat',
                'device_info': {
                    'device': (data or {}).get('device', 'ESP32_DEVKIT_V1'),
                    'ip': ip,
                    'port': port,
                    'heartbeat_timestamp': datetime.now().isoformat()
                }
            }

        resp = {
            "status": "ok",
            "message": "Heartbeat acknowledged",
            "timestamp": datetime.now().isoformat()
        }
        if pending_event:
            resp.update(pending_event)

        return True, resp, 200

    @classmethod
    def _dispatch_hardware_event(cls, hardware_event_type, student_name=None, roll_number=None, student_id=None):
        """Internal worker running in background thread to deliver event to ESP32."""
        config = cls.load_config()
        enabled = config.get('esp32_enabled', False) or ((time.time() - cls._last_heartbeat_time) < 15.0)
        if not enabled:
            return

        event_id = str(uuid.uuid4())
        payload = {
            'event_id': event_id,
            'type': hardware_event_type,  # 'PRESENT' or 'ABSENT'
            'student_name': student_name or '',
            'roll_number': roll_number or '',
            'student_id': student_id,
            'timestamp': datetime.now().isoformat()
        }

        # Enqueue for heartbeat poll delivery (with bounded buffer)
        with cls._lock:
            cls._pending_events.append(payload)
            if len(cls._pending_events) > 10:
                cls._pending_events = cls._pending_events[-10:]

        host = (config.get('esp32_host') or cls._discovered_esp32_host or '').strip().rstrip('/')
        if not host:
            return

        secret = config.get('esp32_secret', '')
        timeout = float(config.get('request_timeout_seconds', 1.0))

        import urllib.request
        import urllib.error

        try:
            url = f"{host}/api/event"
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    'Content-Type': 'application/json',
                    'X-ESP32-Secret': secret,
                    'User-Agent': 'CampusSync-Flask'
                },
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status == 200:
                    logger.info(f"[ESP32 IoT] Successfully sent {hardware_event_type} event ({event_id}) to {host}")
                else:
                    logger.warning(f"[ESP32 IoT] ESP32 returned status {response.status}")
        except Exception as e:
            logger.warning(f"[ESP32 IoT] Optional ESP32 direct notification skipped ({type(e).__name__}): {e}")

    @classmethod
    def record_event(cls, event_type, student_id=None, student_name=None, roll_number=None, error_detail=None):
        """
        Records an attendance verification event for simulation and dispatches to ESP32 if configured.
        event_type: 'VERIFIED', 'ABSENT', 'UNRECOGNIZED', 'DUPLICATE', 'SESSION_START', 'SESSION_END'
        """
        # Determine simulation indicator states per specification:
        # PRESENT: Green LED ON, Red LED OFF, Buzzer SILENT
        # ABSENT: Red LED ON, Green LED OFF, Buzzer 1 short beep
        # IDLE / UNKNOWN / ERROR / DUPLICATE: Green LED OFF, Red LED OFF, Buzzer OFF
        if event_type == 'VERIFIED' or event_type == 'PRESENT':
            led = 'GREEN'
            beeps = 0
        elif event_type == 'ABSENT':
            led = 'RED'
            beeps = 1
        elif event_type in ['UNRECOGNIZED', 'UNAUTHORIZED']:
            led = 'RED'
            beeps = 0
        elif event_type == 'DUPLICATE':
            led = 'OFF'
            beeps = 0
        else:
            led = 'OFF'
            beeps = 0

        with cls._lock:
            cls._last_event = {
                'device_id': 'ESP32_DEVKIT_V1',
                'event': event_type,
                'last_event': event_type,
                'status': 'ACTIVE',
                'student_id': student_id,
                'student_name': student_name,
                'roll_number': roll_number,
                'led': led,
                'led_green': 'ON' if led == 'GREEN' else 'OFF',
                'led_red': 'ON' if led == 'RED' else 'OFF',
                'buzzer': 'BEEP' if beeps > 0 else 'IDLE',
                'buzzer_beeps': beeps,
                'error_detail': error_detail,
                'timestamp': datetime.now().isoformat()
            }

        # Dispatch to physical hardware asynchronously (non-blocking)
        # ONLY 'VERIFIED' triggers Green LED + Buzzer (PRESENT).
        # ONLY 'ABSENT' triggers Red LED + Buzzer (ABSENT).
        # Unrecognized / Duplicate do NOT trigger hardware Green LED or Buzzer.
        if event_type == 'VERIFIED':
            cls._executor.submit(
                cls._dispatch_hardware_event,
                'PRESENT',
                student_name=student_name,
                roll_number=roll_number,
                student_id=student_id
            )
        elif event_type == 'ABSENT':
            cls._executor.submit(
                cls._dispatch_hardware_event,
                'ABSENT',
                student_name=student_name,
                roll_number=roll_number,
                student_id=student_id
            )

        return cls._last_event

    @classmethod
    def get_status(cls):
        """Returns the current IoT hardware status and last event payload for ESP32 and UI."""
        with cls._lock:
            status_copy = dict(cls._last_event)
        
        # Include connection metadata
        conn = cls.get_connection_status(force_refresh=False)
        status_copy['esp32_connection'] = conn
        return status_copy
