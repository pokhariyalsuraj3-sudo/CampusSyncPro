# CampusSync — ESP32 IoT Attendance Node: Wiring & Setup Guide

This guide details how to build, flash, and connect the **ESP32 IoT Attendance Notification Node** to CampusSync.

---

## 1. Hardware Bill of Materials (BOM)

| Component | Quantity | Specification / Notes |
| :--- | :---: | :--- |
| **ESP32 DevKit V1** | 1 | 30-Pin USB-C version |
| **Green LED (5mm)** | 1 | Indicates Present / Verified attendance |
| **Red LED (5mm)** | 1 | Indicates Absent attendance |
| **Buzzer** | 1 | Active or Passive (see Section 3 for distinction) |
| **Resistors** | 3 | 220 Ω (Red-Red-Brown-Gold) current limiting |
| **Half-Size Breadboard** | 1 | Standard 400-point breadboard |
| **Jumper Wires** | 6–8 | Male-to-Male jumpers |
| **USB-C Cable** | 1 | Connects ESP32 to 5V power or laptop |

---

## 2. Wiring & Pinout Table

### Pin Connection Table

| ESP32 Pin (30-Pin) | Breadboard Connection | Target Component | Notes |
| :--- | :--- | :--- | :--- |
| **GPIO 18** | Jumper $\rightarrow$ 220 Ω Resistor | **Green LED Anode (+)** (Long leg) | Safe output pin (VSPI CLK) |
| **GPIO 19** | Jumper $\rightarrow$ 220 Ω Resistor | **Red LED Anode (+)** (Long leg) | Safe output pin (VSPI MISO) |
| **GPIO 21** | Jumper $\rightarrow$ 220 Ω Resistor | **Buzzer (+ / Positive Pin)** | Safe output / PWM pin |
| **GND** | Jumper $\rightarrow$ Blue Ground Rail ($-$) | **All Component Cathodes ($-$)** | Common Ground |

### Cathode / Ground Return:
- **Green LED Cathode ($-$)** (Flat notch / short leg) $\rightarrow$ Breadboard Common Ground Rail ($-$).
- **Red LED Cathode ($-$)** (Flat notch / short leg) $\rightarrow$ Breadboard Common Ground Rail ($-$).
- **Buzzer Negative ($-$)** (Marked with "$-$" or black wire) $\rightarrow$ Breadboard Common Ground Rail ($-$).
- **ESP32 GND pin** $\rightarrow$ Breadboard Common Ground Rail ($-$).

```
             ESP32 DevKit V1 (30-Pin)
             +-----------------------+
             | [USB-C]               |
             |                       |
   GPIO 18 --| [18]                  |
             |   |                   |
             |   +--[ 220 Ohm ]--> [Green LED +] ---> [GND Rail]
             |                       |
   GPIO 19 --| [19]                  |
             |   |                   |
             |   +--[ 220 Ohm ]--> [Red LED +] -----> [GND Rail]
             |                       |
   GPIO 21 --| [21]                  |
             |   |                   |
             |   +--[ 220 Ohm ]--> [Buzzer +] ------> [GND Rail]
             |                       |
       GND --| [GND] --------------------------------> [GND Rail]
             +-----------------------+
```

---

## 3. Active Buzzer vs. Passive Buzzer Configuration

The firmware supports **both** Active and Passive buzzers via a single configuration flag:

```cpp
#define BUZZER_IS_ACTIVE true   // Set to true for Active, false for Passive
```

### How to identify which buzzer you have:
1. **Physical Inspection**:
   - **Active Buzzer**: Usually has a protective sticker on top ("Remove seal after washing") and a smooth black resin/potting on the bottom covering the circuit.
   - **Passive Buzzer**: Usually has an exposed green PCB visible on the bottom side.
2. **Simple 3V Battery Test**:
   - Touch the buzzer leads momentarily to a 3V coin cell battery (CR2032) or 3.3V power pin:
   - If it makes a **continuous, steady buzz/beep**, it is an **Active Buzzer** $\rightarrow$ Keep `#define BUZZER_IS_ACTIVE true`.
   - If it only makes a **single faint click** when touching and releasing the wire, it is a **Passive Buzzer** $\rightarrow$ Change to `#define BUZZER_IS_ACTIVE false`.

---

## 4. Flashing Firmware via Arduino IDE

1. Open **Arduino IDE** (v1.8.x or v2.x).
2. Go to **File $\rightarrow$ Preferences**, add to *Additional Boards Manager URLs*:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
3. Go to **Tools $\rightarrow$ Board $\rightarrow$ Boards Manager**, search for `esp32` by Espressif Systems and install it.
4. Select board: **Tools $\rightarrow$ Board $\rightarrow$ ESP32 Arduino $\rightarrow$ ESP32 Dev Module** (or `DOIT ESP32 DEVKIT V1`).
5. Open `firmware/esp32_attendance_node/esp32_attendance_node.ino`.
6. Update Wi-Fi settings at the top:
   ```cpp
   const char* WIFI_SSID     = "Your_WiFi_Network_Name";
   const char* WIFI_PASSWORD = "Your_WiFi_Password";
   ```
7. Plug in the ESP32 via USB-C, select the COM port in **Tools $\rightarrow$ Port**.
8. Click **Upload**.
9. Open **Tools $\rightarrow$ Serial Monitor** (set baud rate to **115200**).
10. Note the assigned IP address shown in Serial Monitor (e.g. `192.168.1.50`).

---

## 5. Connecting CampusSync to ESP32

In the CampusSync project root, open `iot_config.json`:

```json
{
  "esp32_enabled": true,
  "esp32_host": "http://192.168.1.50:8080",
  "esp32_secret": "campus_sync_iot_secret_2026",
  "request_timeout_seconds": 1.0,
  "hardware": {
    "board": "ESP32 DevKit V1 (30-pin USB-C)",
    "pin_green_led": 18,
    "pin_red_led": 19,
    "pin_buzzer": 21,
    "buzzer_is_active": true
  }
}
```

1. Set `"esp32_enabled": true`.
2. Update `"esp32_host"` to your ESP32's IP address with port 8080 (e.g., `http://192.168.1.50:8080`).
3. Ensure `"esp32_secret"` matches the `ESP32_SECRET` string in the `.ino` firmware.
4. Save the file.

---

## 6. Verification & Troubleshooting

### Direct Browser Hardware Test (Standalone)
You can test the hardware directly from any browser on the same Wi-Fi network:
- Test Present: `http://192.168.1.50:8080/test/present` $\rightarrow$ Green LED turns ON for 2.5s and Buzzer beeps!
- Test Absent : `http://192.168.1.50:8080/test/absent` $\rightarrow$ Red LED turns ON for 2.5s (Buzzer stays OFF)!
- Status Check: `http://192.168.1.50:8080/api/status?secret=campus_sync_iot_secret_2026`

### Teacher Attendance UI Badge
- Navigate to **Teacher Attendance** (`/teacher/attendance`).
- The **ESP32 IoT** badge in the toolbar and camera widget will display:
  - **Connected** (Green badge) when ESP32 is online and reachable.
  - **Disconnected** (Yellow/Orange badge) if ESP32 host is set but offline.
  - **Not Configured** (Gray badge) if ESP32 is disabled.
