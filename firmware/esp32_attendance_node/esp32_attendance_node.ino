/*
 * ==============================================================================
 * CAMPUSSYNC — ESP32 IOT ATTENDANCE NOTIFICATION NODE
 * ==============================================================================
 * Target Hardware : ESP32 DevKit V1 (30-pin, USB-C)
 * Framework       : Arduino IDE (ESP32 by Espressif Systems board package)
 *
 * Hardware Components:
 *   - ESP32 DevKit V1 (30-pin USB-C)
 *   - Green LED (Present Indicator)
 *   - Red LED (Absent Indicator)
 *   - Buzzer (Active or Passive, configurable below)
 *   - 220 Ohm Current-Limiting Resistors (x3)
 *   - Breadboard & Jumper Wires
 *
 * Wiring Pinout:
 *   - GPIO 26 ----[ 220 Ohm ]----> Green LED Anode (+) | Cathode (-) -> GND
 *   - GPIO 27 ----[ 220 Ohm ]----> Red LED Anode (+)   | Cathode (-) -> GND
 *   - GPIO 25 -------------------> Buzzer I/O / Signal | VCC -> 3V3, GND -> GND
 *   - GND     -------------------> Breadboard Ground Rail
 *
 * Behavior:
 *   - PRESENT event: Green LED ON (2.5s) + Buzzer short beep (~200ms), Red LED OFF
 *   - ABSENT event : Red LED ON (2.5s)   + Buzzer short beep (~200ms), Green LED OFF
 *   - Self-test on boot: Green LED -> Red LED -> Short Chirp
 *   - Hardware is 100% OPTIONAL: CampusSync operates normally if node is offline.
 * ==============================================================================
 */

#include <WiFi.h>
#include <WebServer.h>
#include <HTTPClient.h>

// ==========================================
// 1. NETWORK & AUTHENTICATION CONFIGURATION
// ==========================================
// Replace with your local Wi-Fi credentials
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// CampusSync Flask Server IP & Port (e.g. http://192.168.1.100:5000)
// Leave empty ("") if you prefer CampusSync to push events to ESP32 only
const char* SERVER_URL    = "http://192.168.1.100:5000";

// Pre-shared secret matching CampusSync backend (X-ESP32-Secret header)
const char* ESP32_SECRET  = "campus_sync_iot_secret_2026";

// Web server listening port (default: 8080)
const int HTTP_PORT       = 8080;

// ==========================================
// 2. HARDWARE GPIO PIN CONFIGURATION
// ==========================================
#define PIN_LED_GREEN 26  // Green LED — Present (GPIO 26)
#define PIN_LED_RED   27  // Red LED — Absent (GPIO 27)
#define PIN_BUZZER    25  // Buzzer Signal / IO (GPIO 25)

// ==========================================
// 3. BUZZER CONFIGURATION (ACTIVE VS PASSIVE)
// ==========================================
// Set to true if using an Active Buzzer (internal oscillator, steady DC triggers buzz).
// Set to false if using a Passive Buzzer (requires PWM square wave tone).
#define BUZZER_IS_ACTIVE true

// Frequency in Hertz for Passive Buzzer (ignored for Active Buzzer)
#define BUZZER_FREQUENCY_HZ 2000

// Durations in milliseconds
#define DURATION_PRESENT_LED_MS  2500
#define DURATION_PRESENT_BEEP_MS 200
#define DURATION_ABSENT_LED_MS   2500
#define DURATION_ABSENT_BEEP_MS  200

// ==========================================
// GLOBAL STATE & OBJECTS
// ==========================================
WebServer server(HTTP_PORT);

// Non-blocking timer state variables
bool greenLedActive  = false;
bool redLedActive    = false;
bool buzzerActive    = false;

unsigned long greenLedOffTime = 0;
unsigned long redLedOffTime   = 0;
unsigned long buzzerOffTime   = 0;

// Deduplication Ring Buffer (last 16 event UUIDs)
const int DEDUP_HISTORY_SIZE = 16;
String recentEventIds[DEDUP_HISTORY_SIZE];
int dedupHead = 0;

// Track last event for status reporting
String lastEventType   = "IDLE";
String lastStudentName = "";
String lastRollNumber  = "";
unsigned long lastEventTime = 0;

// ==========================================
// HARDWARE CONTROL PRIMITIVES
// ==========================================
void buzzerOn() {
#if BUZZER_IS_ACTIVE
  digitalWrite(PIN_BUZZER, HIGH);
#else
  // Passive buzzer square wave tone
  tone(PIN_BUZZER, BUZZER_FREQUENCY_HZ);
#endif
  buzzerActive = true;
}

void buzzerOff() {
#if BUZZER_IS_ACTIVE
  digitalWrite(PIN_BUZZER, LOW);
#else
  noTone(PIN_BUZZER);
#endif
  buzzerActive = false;
}

void triggerPresentFeedback(const String& studentName, const String& rollNumber) {
  // Clear any active absent indicators
  digitalWrite(PIN_LED_RED, LOW);
  redLedActive = false;

  // Turn on Green LED
  digitalWrite(PIN_LED_GREEN, HIGH);
  greenLedActive = true;
  greenLedOffTime = millis() + DURATION_PRESENT_LED_MS;

  // Turn on Buzzer
  buzzerOn();
  buzzerOffTime = millis() + DURATION_PRESENT_BEEP_MS;

  lastEventType   = "PRESENT";
  lastStudentName = studentName;
  lastRollNumber  = rollNumber;
  lastEventTime   = millis();

  Serial.printf("[FEEDBACK] Present: %s (%s) -> Green LED ON, Buzzer Beep\n",
                studentName.c_str(), rollNumber.c_str());
}

void triggerAbsentFeedback(const String& studentName, const String& rollNumber) {
  // Clear any active present indicators
  digitalWrite(PIN_LED_GREEN, LOW);
  greenLedActive = false;

  // Turn on Red LED
  digitalWrite(PIN_LED_RED, HIGH);
  redLedActive = true;
  redLedOffTime = millis() + DURATION_ABSENT_LED_MS;

  // Turn on Buzzer for short beep (as specified in Section 3.B)
  buzzerOn();
  buzzerOffTime = millis() + DURATION_ABSENT_BEEP_MS;

  lastEventType   = "ABSENT";
  lastStudentName = studentName;
  lastRollNumber  = rollNumber;
  lastEventTime   = millis();

  Serial.printf("[FEEDBACK] Absent: %s (%s) -> Red LED ON, Buzzer Beep\n",
                studentName.c_str(), rollNumber.c_str());
}

void runBootSelfTest() {
  Serial.println("[SELF-TEST] Running hardware diagnostic...");

  // Green LED test
  digitalWrite(PIN_LED_GREEN, HIGH);
  delay(200);
  digitalWrite(PIN_LED_GREEN, LOW);
  delay(100);

  // Red LED test
  digitalWrite(PIN_LED_RED, HIGH);
  delay(200);
  digitalWrite(PIN_LED_RED, LOW);
  delay(100);

  // Buzzer short chirp (50ms)
  buzzerOn();
  delay(60);
  buzzerOff();

  Serial.println("[SELF-TEST] Diagnostic complete. LEDs and Buzzer operational.");
}

// ==========================================
// DEDUPLICATION CHECK
// ==========================================
bool isDuplicate(const String& eventId) {
  if (eventId.length() == 0) return false;

  for (int i = 0; i < DEDUP_HISTORY_SIZE; i++) {
    if (recentEventIds[i].length() > 0 && recentEventIds[i] == eventId) {
      return true;
    }
  }

  // Store in circular buffer
  recentEventIds[dedupHead] = eventId;
  dedupHead = (dedupHead + 1) % DEDUP_HISTORY_SIZE;
  return false;
}

// ==========================================
// HELPER: EXTRACT FIELD FROM JSON STRING
// (Zero-dependency JSON parser)
// ==========================================
String extractJsonField(const String& body, const String& field) {
  String searchKey = "\"" + field + "\"";
  int keyPos = body.indexOf(searchKey);
  if (keyPos < 0) return "";

  int colonPos = body.indexOf(":", keyPos + searchKey.length());
  if (colonPos < 0) return "";

  int valStart = colonPos + 1;
  while (valStart < body.length() && (body[valStart] == ' ' || body[valStart] == '\t')) {
    valStart++;
  }

  if (valStart < body.length() && body[valStart] == '\"') {
    valStart++;
    int valEnd = body.indexOf("\"", valStart);
    if (valEnd < 0) return "";
    return body.substring(valStart, valEnd);
  } else {
    int valEnd = valStart;
    while (valEnd < body.length() && body[valEnd] != ',' && body[valEnd] != '}' && body[valEnd] != '\n' && body[valEnd] != '\r') {
      valEnd++;
    }
    String val = body.substring(valStart, valEnd);
    val.trim();
    return val;
  }
}

// ==========================================
// HTTP REQUEST HANDLERS
// ==========================================
bool validateAuth() {
  if (strlen(ESP32_SECRET) == 0) return true; // Auth disabled if secret is empty

  if (server.hasHeader("X-ESP32-Secret")) {
    String headerSecret = server.header("X-ESP32-Secret");
    if (headerSecret == ESP32_SECRET) return true;
  }

  // Also accept query parameter ?secret=... for quick manual testing
  if (server.hasArg("secret")) {
    if (server.arg("secret") == ESP32_SECRET) return true;
  }

  return false;
}

void handleStatus() {
  if (!validateAuth()) {
    server.send(401, "application/json", "{\"error\":\"Unauthorized: invalid or missing X-ESP32-Secret\"}");
    return;
  }

  String json = "{";
  json += "\"device\":\"ESP32_DEVKIT_V1\",";
  json += "\"system\":\"CampusSync IoT Attendance Node\",";
  json += "\"status\":\"online\",";
  json += "\"ip\":\"" + WiFi.localIP().toString() + "\",";
  json += "\"wifi_rssi\":" + String(WiFi.RSSI()) + ",";
  json += "\"uptime_seconds\":" + String(millis() / 1000) + ",";
  json += "\"buzzer_type\":\"" + String(BUZZER_IS_ACTIVE ? "active" : "passive") + "\",";
  json += "\"pins\":{\"green_led\":" + String(PIN_LED_GREEN) + ",\"red_led\":" + String(PIN_LED_RED) + ",\"buzzer\":" + String(PIN_BUZZER) + "},";
  json += "\"led_green\":\"" + String(greenLedActive ? "ON" : "OFF") + "\",";
  json += "\"led_red\":\"" + String(redLedActive ? "ON" : "OFF") + "\",";
  json += "\"buzzer\":\"" + String(buzzerActive ? "BEEP" : "IDLE") + "\",";
  json += "\"last_event\":\"" + lastEventType + "\",";
  json += "\"last_student_name\":\"" + lastStudentName + "\",";
  json += "\"last_roll_number\":\"" + lastRollNumber + "\"";
  json += "}";

  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", json);
}

void handleEvent() {
  if (!validateAuth()) {
    server.send(401, "application/json", "{\"error\":\"Unauthorized: invalid or missing X-ESP32-Secret\"}");
    return;
  }

  String body = server.arg("plain");
  if (body.length() == 0) {
    server.send(400, "application/json", "{\"error\":\"Empty request body\"}");
    return;
  }

  String eventId     = extractJsonField(body, "event_id");
  String eventType   = extractJsonField(body, "type");
  String studentName = extractJsonField(body, "student_name");
  String rollNumber  = extractJsonField(body, "roll_number");

  if (eventType.length() == 0) {
    eventType = extractJsonField(body, "event_type");
  }

  eventType.toUpperCase();

  // Check deduplication
  if (eventId.length() > 0 && isDuplicate(eventId)) {
    Serial.printf("[DEDUP] Ignored duplicate event ID: %s\n", eventId.c_str());
    server.send(200, "application/json", "{\"success\":true,\"status\":\"duplicate_ignored\",\"event_id\":\"" + eventId + "\"}");
    return;
  }

  if (eventType == "PRESENT" || eventType == "VERIFIED") {
    triggerPresentFeedback(studentName, rollNumber);
    server.send(200, "application/json", "{\"success\":true,\"action\":\"PRESENT_FEEDBACK_TRIGGERED\",\"event_id\":\"" + eventId + "\"}");
  } else if (eventType == "ABSENT") {
    triggerAbsentFeedback(studentName, rollNumber);
    server.send(200, "application/json", "{\"success\":true,\"action\":\"ABSENT_FEEDBACK_TRIGGERED\",\"event_id\":\"" + eventId + "\"}");
  } else {
    // Other events (e.g., UNRECOGNIZED, DUPLICATE, PING) - do not trigger Green LED or buzzer
    Serial.printf("[INFO] Non-trigger event received: %s (LED/Buzzer kept idle)\n", eventType.c_str());
    server.send(200, "application/json", "{\"success\":true,\"action\":\"IGNORED_SAFE\",\"event_type\":\"" + eventType + "\"}");
  }
}

// Quick testing endpoints for web browser testing
void handleTestPresent() {
  triggerPresentFeedback("Test Student", "CS-TEST");
  server.send(200, "text/plain", "OK: Present test feedback triggered (Green LED + Buzzer Beep)");
}

void handleTestAbsent() {
  triggerAbsentFeedback("Test Student", "CS-TEST");
  server.send(200, "text/plain", "OK: Absent test feedback triggered (Red LED, no buzzer)");
}

void handleNotFound() {
  server.send(404, "application/json", "{\"error\":\"Endpoint not found. Valid endpoints: GET /api/status, POST /api/event\"}");
}

// ==========================================
// ARDUINO SETUP
// ==========================================
void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("\n==========================================");
  Serial.println("  CAMPUSSYNC ESP32 ATTENDANCE NODE BOOT  ");
  Serial.println("==========================================");

  // Configure GPIO pins as outputs
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_RED,   OUTPUT);
  pinMode(PIN_BUZZER,    OUTPUT);

  digitalWrite(PIN_LED_GREEN, LOW);
  digitalWrite(PIN_LED_RED,   LOW);
  buzzerOff();

  // Run hardware self-test
  runBootSelfTest();

  // Connect to Wi-Fi
  Serial.printf("[WIFI] Connecting to SSID: %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 25) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("[WIFI] Connected successfully!");
    Serial.print("[WIFI] ESP32 IP Address: ");
    Serial.println(WiFi.localIP());
    Serial.print("[WIFI] Signal Strength (RSSI): ");
    Serial.printf("%d dBm\n", WiFi.RSSI());
  } else {
    Serial.println("[WIFI] Failed to connect. Running in offline/standalone mode.");
    Serial.println("[WIFI] Check SSID and password in firmware configuration.");
  }

  // Register header for secret validation
  const char* headerKeys[] = {"X-ESP32-Secret", "Content-Type"};
  server.collectHeaders(headerKeys, 2);

  // Register endpoints
  server.on("/", HTTP_GET, handleStatus);
  server.on("/api/status", HTTP_GET, handleStatus);
  server.on("/api/event", HTTP_POST, handleEvent);
  server.on("/test/present", HTTP_GET, handleTestPresent);
  server.on("/test/absent", HTTP_GET, handleTestAbsent);
  server.onNotFound(handleNotFound);

  server.begin();
  Serial.printf("[HTTP] Server started on port %d\n", HTTP_PORT);
  Serial.printf("[INFO] Base URL: http://%s:%d/api/status\n", WiFi.localIP().toString().c_str(), HTTP_PORT);
  Serial.println("==========================================\n");
}

// ==========================================
// BIDIRECTIONAL HEARTBEAT TO CAMPUSSYNC
// ==========================================
void sendHeartbeatToCampusSync() {
  if (WiFi.status() != WL_CONNECTED || strlen(SERVER_URL) == 0) return;

  HTTPClient http;
  String url = String(SERVER_URL) + "/api/iot/heartbeat";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-ESP32-Secret", ESP32_SECRET);
  http.setTimeout(1200);

  String payload = "{";
  payload += "\"device\":\"ESP32_DEVKIT_V1\",";
  payload += "\"ip\":\"" + WiFi.localIP().toString() + "\",";
  payload += "\"port\":" + String(HTTP_PORT) + ",";
  payload += "\"status\":\"online\"";
  payload += "}";

  int httpCode = http.POST(payload);
  if (httpCode == 200) {
    String response = http.getString();
    // Check if there are any pending attendance events dispatched while disconnected
    if (response.indexOf("\"type\":") >= 0) {
      String eventType   = extractJsonField(response, "type");
      String eventId     = extractJsonField(response, "event_id");
      String studentName = extractJsonField(response, "student_name");
      String rollNumber  = extractJsonField(response, "roll_number");
      if (eventId.length() > 0 && !isDuplicate(eventId)) {
        eventType.toUpperCase();
        if (eventType == "PRESENT" || eventType == "VERIFIED") {
          triggerPresentFeedback(studentName, rollNumber);
        } else if (eventType == "ABSENT") {
          triggerAbsentFeedback(studentName, rollNumber);
        }
      }
    }
  }
  http.end();
}

// ==========================================
// ARDUINO MAIN LOOP (Non-blocking)
// ==========================================
void loop() {
  server.handleClient();

  unsigned long currentMillis = millis();

  // Non-blocking timer: Turn off Buzzer after beep duration
  if (buzzerActive && currentMillis >= buzzerOffTime) {
    buzzerOff();
  }

  // Non-blocking timer: Turn off Green LED after duration
  if (greenLedActive && currentMillis >= greenLedOffTime) {
    digitalWrite(PIN_LED_GREEN, LOW);
    greenLedActive = false;
  }

  // Non-blocking timer: Turn off Red LED after duration
  if (redLedActive && currentMillis >= redLedOffTime) {
    digitalWrite(PIN_LED_RED, LOW);
    redLedActive = false;
  }

  // Auto-reconnect Wi-Fi if connection is dropped (every 10s)
  static unsigned long lastWifiCheck = 0;
  if (currentMillis - lastWifiCheck >= 10000) {
    lastWifiCheck = currentMillis;
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("[WIFI] Connection lost. Attempting non-blocking reconnect...");
      WiFi.reconnect();
    }
  }

  // Periodic heartbeat to CampusSync server (every 8s)
  static unsigned long lastHeartbeat = 0;
  if (currentMillis - lastHeartbeat >= 8000) {
    lastHeartbeat = currentMillis;
    sendHeartbeatToCampusSync();
  }
}
