/*
 * Claude Code Traffic Light Controller
 * ESP32C3 - receives single-char commands via USB Serial
 *
 * Commands:
 *   G = green blink    (calling model - API request)
 *   g = green solid    (working - writing code etc.)
 *   y = yellow blink   (thinking)
 *   Y = yellow solid   (calling tools)
 *   r = red blink      (needs permission OR error)
 *   R = red solid      (finished reply, waiting for input)
 *   O = all off        (session ended)
 *
 * Wiring (active low):
 *   GPIO0 -> Green LED  -> VCC
 *   GPIO1 -> Yellow LED -> VCC
 *   GPIO2 -> Red LED    -> VCC
 */

#define On  0x0
#define Off 0x1

const int PIN_GREEN  = 0;
const int PIN_YELLOW = 1;
const int PIN_RED    = 2;

unsigned long lastBlink = 0;
bool blinkState = false;
const int BLINK_INTERVAL = 500;

// 0=off, 1=green blink, 2=green solid, 3=yellow blink, 4=yellow solid,
// 5=red blink, 6=red solid
int mode = 0;

void setAll(bool g, bool y, bool r) {
    digitalWrite(PIN_GREEN,  g ? On : Off);
    digitalWrite(PIN_YELLOW, y ? On : Off);
    digitalWrite(PIN_RED,    r ? On : Off);
}

void setup() {
    Serial.begin(115200);
    pinMode(PIN_GREEN, OUTPUT);
    pinMode(PIN_YELLOW, OUTPUT);
    pinMode(PIN_RED, OUTPUT);
    setAll(false, false, false);
}

void loop() {
    if (Serial.available() > 0) {
        char cmd = Serial.read();
        switch (cmd) {
            case 'G': mode = 1; break;  // green blink
            case 'g': mode = 2; break;  // green solid
            case 'y': mode = 3; break;  // yellow blink
            case 'Y': mode = 4; break;  // yellow solid
            case 'r': mode = 5; break;  // red blink
            case 'R': mode = 6; break;  // red solid
            case 'O': mode = 0; break;  // off
        }
    }

    switch (mode) {
        case 0: // off
            setAll(false, false, false);
            break;
        case 1: // green blink
            if (millis() - lastBlink >= BLINK_INTERVAL) {
                lastBlink = millis();
                blinkState = !blinkState;
                setAll(blinkState, false, false);
            }
            break;
        case 2: // green solid
            setAll(true, false, false);
            break;
        case 3: // yellow blink
            if (millis() - lastBlink >= BLINK_INTERVAL) {
                lastBlink = millis();
                blinkState = !blinkState;
                setAll(false, blinkState, false);
            }
            break;
        case 4: // yellow solid
            setAll(false, true, false);
            break;
        case 5: // red blink
            if (millis() - lastBlink >= BLINK_INTERVAL) {
                lastBlink = millis();
                blinkState = !blinkState;
                setAll(false, false, blinkState);
            }
            break;
        case 6: // red solid
            setAll(false, false, true);
            break;
    }
}
