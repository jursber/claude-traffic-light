/*
 * Claude Code Traffic Light Controller
 * ESP32C3 - receives single-char commands via USB Serial
 *
 * Commands:
 *   G = green solid    (idle, waiting for input)
 *   y = yellow blink   (thinking, model processing)
 *   Y = yellow solid   (executing tools)
 *   r = red blink      (needs permission)
 *   R = red solid      (error)
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

// 0=off, 1=green, 2=yellow solid, 3=yellow blink, 4=red solid, 5=red blink
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
            case 'G': mode = 1; break;
            case 'Y': mode = 2; break;
            case 'y': mode = 3; break;
            case 'R': mode = 4; break;
            case 'r': mode = 5; break;
            case 'O': mode = 0; break;
        }
    }

    switch (mode) {
        case 0:
            setAll(false, false, false);
            break;
        case 1:
            setAll(true, false, false);
            break;
        case 2:
            setAll(false, true, false);
            break;
        case 3:
            if (millis() - lastBlink >= BLINK_INTERVAL) {
                lastBlink = millis();
                blinkState = !blinkState;
                setAll(false, blinkState, false);
            }
            break;
        case 4:
            setAll(false, false, true);
            break;
        case 5:
            if (millis() - lastBlink >= BLINK_INTERVAL) {
                lastBlink = millis();
                blinkState = !blinkState;
                setAll(false, false, blinkState);
            }
            break;
    }
}
