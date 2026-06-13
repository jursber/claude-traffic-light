/*
 * VibeLight — ESP32-C3 三色灯控固件（工业向）
 *
 * - USB 调试时固件仍会 **initBle()**（NimBLE 占内存与 CPU）；若要做「纯串口」对比，可临时注释 `setup()` 里的 `initBle()`（需自行处理 NimBLE 相关编译依赖）
 * - 旧版单字节 ASCII（G/g/y/Y/r/R/O）与 v1 二进制帧并存（见 docs/VIBELIGHT_PROTOCOL.md）
 * - 有源低电平 + LEDC PWM；PROTO 灯效由 **FreeRTOS 任务 ~1kHz 刷新**，与 BLE/串口 loop 解耦，避免长时间不更新 PWM 造成「平顶」错觉
 * - v1：`cmd=1` 定长灯控 + `cmd=2` 可拖拽曲线式自定义呼吸（见 docs）；内置 **MODE_BREATH** = **三角包络** + 上升半周 **`TL_BREATH_RISE_PERCEPTUAL`**（默认可关）
 *
 * GPIO: 0 绿, 1 黄, 2 红  （与仓库硬件说明一致）
 */

#include <NimBLEDevice.h>
#include <esp_timer.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <string.h>

// -----------------------------------------------------------------------------
// 硬件与 BLE
// -----------------------------------------------------------------------------
static const int PIN_GREEN = 0;
static const int PIN_YELLOW = 1;
static const int PIN_RED = 2;

#define BLE_DEVICE_NAME "VibeLight"
#define BLE_SERVICE_UUID "e52c12b6-7ac3-4636-9c17-3d608bcea796"
#define BLE_CHAR_UUID "e52c12b7-7ac3-4636-9c17-3d608bcea796"

static const uint32_t LEDC_FREQ = 5000;
static const uint8_t LEDC_RES_BITS = 8;

// 协议常量（与 docs/VIBELIGHT_PROTOCOL.md 一致）
static const uint8_t PROTO_MAGIC0 = 0xA5;
static const uint8_t PROTO_MAGIC1 = 0x5A;
static const uint8_t PROTO_VER = 1;
static const uint8_t CMD_SET_LIGHTING = 1;
static const uint8_t CMD_SET_BREATH_CURVE = 2;
static const uint8_t MODE_OFF = 0;
static const uint8_t MODE_SOLID = 1;
static const uint8_t MODE_SYNC_BLINK = 2;
static const uint8_t MODE_BREATH = 3;
static const uint8_t MODE_BREATH_CURVE = 4;
#define CURVE_MAX_N 32
#define CURVE_MIN_N 8

static const uint16_t PERIOD_MS_MIN = 50;
static const uint16_t PERIOD_MS_MAX = 60000;
static const uint32_t PROTO_MIN_INTERVAL_MS = 4;
static const uint16_t STALE_MAGIC1_MS = 120;

/** PWM 刷新任务优先级：须高于 Arduino loopTask(≈1)，低于 NimBLE 主机任务；可按板子调 */
#ifndef TL_PWM_TASK_PRIO
#define TL_PWM_TASK_PRIO 8
#endif
/** 每圈 loop 最多从 USB CDC 取字节数，避免一次读爆占用过久 */
#ifndef TL_SERIAL_DRAIN_MAX
#define TL_SERIAL_DRAIN_MAX 64
#endif
/**
 * MODE_BREATH 上升半周：对线性三角做整数平方 (lin^2+127)/255，压低低占空比段的斜率，
 * 减轻「暗→亮前段一下冲到很亮、末段慢慢爬满」的人眼非线性（LED 线性 PWM vs 感知亮度）。
 * 下降半周保持线性，以保留多数用户认为自然的「亮→暗」。置 0 则全程数学对称线性三角。
 */
#ifndef TL_BREATH_RISE_PERCEPTUAL
#define TL_BREATH_RISE_PERCEPTUAL 1
#endif

#define RB_SIZE 256
static uint8_t s_rb[RB_SIZE];
static uint16_t s_rbLen = 0;
static portMUX_TYPE s_rbMux = portMUX_INITIALIZER_UNLOCKED;
static unsigned long s_lastRxMs = 0;
static unsigned long s_lastProtoApplyMs = 0;

typedef enum { ENGINE_LEGACY, ENGINE_PROTO } Engine_t;
static Engine_t s_engine = ENGINE_LEGACY;

// Legacy 动画
static unsigned long s_lastBlink = 0;
static bool s_blinkState = false;
static const int BLINK_INTERVAL = 500;
static int s_legacyMode = 0;

// PROTO 参数
static uint8_t s_protoMode = MODE_OFF;
static uint8_t s_protoMask = 0;
static uint16_t s_protoPeriod = 1000;
static uint8_t s_protoDg = 0;
static uint8_t s_protoDy = 0;
static uint8_t s_protoDr = 0;

static uint8_t s_curve[CURVE_MAX_N];
static uint8_t s_curveN = CURVE_MIN_N;
static bool s_haveCurve = false;

/** loop 与 PWM 刷新任务并发访问 PROTO/Legacy 灯态，与 tryApply 写路径互斥 */
static portMUX_TYPE s_ledMux = portMUX_INITIALIZER_UNLOCKED;

// -----------------------------------------------------------------------------
static uint8_t crc8Calc(const uint8_t *data, size_t len) {
    uint8_t crc = 0;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++) {
            if (crc & 0x80) {
                crc = (uint8_t)((crc << 1) ^ 0x07);
            } else {
                crc = (uint8_t)(crc << 1);
            }
        }
    }
    return crc;
}

/** duty×包络/255 四舍五入，减轻低亮度段「长时间为 0 再突然亮起」的截断感 */
static inline uint8_t dutyScaledRound(uint8_t duty, uint16_t base) {
    return (uint8_t)(((uint32_t)duty * (uint32_t)base + 127U) / 255U);
}

/**
 * 线性三角相位：上升 x=0..255，下降 x=256..509 → base=510-x。
 * 时钟用 esp_timer_get_time()，单式 x=ph*510/span，避免两半周期除法不对称。
 */
static uint16_t protoTriangleLinearHalf(uint32_t per_ms, bool *risingOut) {
    if (per_ms < PERIOD_MS_MIN) per_ms = PERIOD_MS_MIN;
    if (per_ms > PERIOD_MS_MAX) per_ms = PERIOD_MS_MAX;
    uint64_t span_us = (uint64_t)per_ms * 1000ULL;
    if (span_us < 2000ULL) {
        span_us = 2000ULL;
    }
    uint64_t now = (uint64_t)esp_timer_get_time();
    uint64_t ph = now % span_us;
    uint64_t x = (ph * 510ULL) / span_us;
    if (x <= 255ULL) {
        *risingOut = true;
        return (uint16_t)x;
    }
    *risingOut = false;
    return (uint16_t)(510ULL - x);
}

/** 仅 MODE_BREATH：上升半周可选感知整形；下降为线性 lin。 */
static uint16_t breathEnvelopeFromLinear(uint16_t lin, bool rising) {
#if TL_BREATH_RISE_PERCEPTUAL
    if (rising) {
        uint32_t t = (uint32_t)lin * (uint32_t)lin;
        return (uint16_t)((t + 127U) / 255U);
    }
#endif
    (void)rising;
    return lin;
}

/** 视觉亮度 0=灭 255=最亮 → 有源低：LEDC 占空越大越接近熄灭（Arduino-ESP32 3.x：按 GPIO 写 PWM） */
static void setChannelVisible(uint8_t pin, uint8_t visible) {
    if (visible > 255) visible = 255;
    ledcWrite(pin, 255 - visible);
}

static void pwmHardwareInit() {
    ledcAttach((uint8_t)PIN_GREEN, LEDC_FREQ, LEDC_RES_BITS);
    ledcAttach((uint8_t)PIN_YELLOW, LEDC_FREQ, LEDC_RES_BITS);
    ledcAttach((uint8_t)PIN_RED, LEDC_FREQ, LEDC_RES_BITS);
    setChannelVisible((uint8_t)PIN_GREEN, 0);
    setChannelVisible((uint8_t)PIN_YELLOW, 0);
    setChannelVisible((uint8_t)PIN_RED, 0);
}

static void rbPushUnsafe(uint8_t b) {
    if (s_rbLen >= RB_SIZE) {
        memmove(s_rb, s_rb + 1, RB_SIZE - 1);
        s_rbLen = RB_SIZE - 1;
    }
    s_rb[s_rbLen++] = b;
    s_lastRxMs = millis();
}

static void rbPush(uint8_t b) {
    portENTER_CRITICAL(&s_rbMux);
    rbPushUnsafe(b);
    portEXIT_CRITICAL(&s_rbMux);
}

static bool isLegacyChar(uint8_t c) {
    return c == 'G' || c == 'g' || c == 'y' || c == 'Y' || c == 'r' || c == 'R' || c == 'O';
}

static void applyLegacyCommand(char cmd) {
    portENTER_CRITICAL(&s_ledMux);
    s_engine = ENGINE_LEGACY;
    switch (cmd) {
        case 'G': s_legacyMode = 1; break;
        case 'g': s_legacyMode = 2; break;
        case 'y': s_legacyMode = 3; break;
        case 'Y': s_legacyMode = 4; break;
        case 'r': s_legacyMode = 5; break;
        case 'R': s_legacyMode = 6; break;
        case 'O': s_legacyMode = 0; break;
        default: break;
    }
    portEXIT_CRITICAL(&s_ledMux);
}

static bool tryApplyProtoFrame(const uint8_t *f) {
    if (f[0] != PROTO_MAGIC0 || f[1] != PROTO_MAGIC1) return false;
    if (f[2] != PROTO_VER) return false;
    if (f[3] != CMD_SET_LIGHTING) return false;
    uint8_t c = crc8Calc(&f[2], 9);
    if (c != f[11]) return false;

    unsigned long now = millis();
    if (s_lastProtoApplyMs != 0 && (now - s_lastProtoApplyMs) < PROTO_MIN_INTERVAL_MS) {
        return true;
    }
    s_lastProtoApplyMs = now;

    portENTER_CRITICAL(&s_ledMux);
    uint8_t mode = f[4];
    uint8_t mask = f[5] & 7;
    uint16_t period = (uint16_t)f[6] | ((uint16_t)f[7] << 8);
    if (period < PERIOD_MS_MIN) period = PERIOD_MS_MIN;
    if (period > PERIOD_MS_MAX) period = PERIOD_MS_MAX;

    s_protoMode = mode > MODE_BREATH ? MODE_OFF : mode;
    s_protoMask = mask;
    s_protoPeriod = period;
    s_protoDg = f[8] > 255 ? 255 : f[8];
    s_protoDy = f[9] > 255 ? 255 : f[9];
    s_protoDr = f[10] > 255 ? 255 : f[10];
    s_engine = ENGINE_PROTO;
    portEXIT_CRITICAL(&s_ledMux);
    return true;
}

/** 自定义呼吸曲线（CMD_SET_BREATH_CURVE），总长 12+n 字节 */
static bool tryApplyBreathCurveFrame(const uint8_t *f, uint16_t flen) {
    if (flen < 12 + (uint16_t)CURVE_MIN_N) return false;
    if (f[0] != PROTO_MAGIC0 || f[1] != PROTO_MAGIC1) return false;
    if (f[2] != PROTO_VER || f[3] != CMD_SET_BREATH_CURVE) return false;
    uint8_t n = f[7];
    if (n < CURVE_MIN_N || n > CURVE_MAX_N) return false;
    if (flen != (uint16_t)(12u + n)) return false;
    uint8_t c = crc8Calc(&f[2], (size_t)(9u + n));
    if (c != f[11u + n]) return false;

    unsigned long now = millis();
    if (s_lastProtoApplyMs != 0 && (now - s_lastProtoApplyMs) < PROTO_MIN_INTERVAL_MS) {
        return true;
    }
    s_lastProtoApplyMs = now;

    uint16_t period = (uint16_t)f[4] | ((uint16_t)f[5] << 8);
    if (period < PERIOD_MS_MIN) period = PERIOD_MS_MIN;
    if (period > PERIOD_MS_MAX) period = PERIOD_MS_MAX;

    portENTER_CRITICAL(&s_ledMux);
    s_protoMask = f[6] & 7;
    s_protoPeriod = period;
    s_protoDg = f[8] > 255 ? 255 : f[8];
    s_protoDy = f[9] > 255 ? 255 : f[9];
    s_protoDr = f[10] > 255 ? 255 : f[10];
    memcpy(s_curve, &f[11], n);
    s_curveN = n;
    s_haveCurve = true;
    s_protoMode = MODE_BREATH_CURVE;
    s_engine = ENGINE_PROTO;
    portEXIT_CRITICAL(&s_ledMux);
    return true;
}

/** 在快照缓冲上解析（无锁，供 loop 调用） */
static void processWorkBuffer(uint8_t *wb, uint16_t *wlen) {
    if (*wlen == 1 && wb[0] == PROTO_MAGIC0) {
        if (millis() - s_lastRxMs > STALE_MAGIC1_MS) {
            memmove(wb, wb + 1, --(*wlen));
        }
    }

    while (*wlen >= 12) {
        size_t i = 0;
        while (i + 12 <= (size_t)*wlen && !(wb[i] == PROTO_MAGIC0 && wb[i + 1] == PROTO_MAGIC1)) {
            i++;
        }
        if (i > 0) {
            memmove(wb, wb + i, *wlen - (uint16_t)i);
            *wlen -= (uint16_t)i;
        }
        if (*wlen < 12) break;
        if (wb[0] != PROTO_MAGIC0 || wb[1] != PROTO_MAGIC1) {
            memmove(wb, wb + 1, --(*wlen));
            continue;
        }
        if (wb[2] != PROTO_VER) {
            memmove(wb, wb + 1, --(*wlen));
            continue;
        }
        uint8_t cmd = wb[3];
        uint16_t need = 0;
        if (cmd == CMD_SET_LIGHTING) {
            need = 12;
        } else if (cmd == CMD_SET_BREATH_CURVE) {
            if (*wlen < 12) break;
            uint8_t n = wb[7];
            if (n < CURVE_MIN_N || n > CURVE_MAX_N) {
                memmove(wb, wb + 1, --(*wlen));
                continue;
            }
            need = (uint16_t)(12u + n);
        } else {
            memmove(wb, wb + 1, --(*wlen));
            continue;
        }
        if (*wlen < need) break;

        bool ok = false;
        if (cmd == CMD_SET_LIGHTING) {
            ok = tryApplyProtoFrame(wb);
        } else {
            ok = tryApplyBreathCurveFrame(wb, need);
        }
        if (!ok) {
            memmove(wb, wb + 1, --(*wlen));
            continue;
        }
        memmove(wb, wb + need, *wlen - need);
        *wlen -= need;
    }

    while (*wlen > 0 && wb[0] != PROTO_MAGIC0) {
        uint8_t c = wb[0];
        memmove(wb, wb + 1, --(*wlen));
        if (isLegacyChar(c)) {
            applyLegacyCommand((char)c);
        }
    }
}

/** 快照环形缓冲 → 无锁解析 → 残字节写回（避免 BLE 回调与 loop 死锁） */
static void processRingBuffer() {
    uint8_t wb[RB_SIZE];
    uint16_t wlen = 0;
    portENTER_CRITICAL(&s_rbMux);
    wlen = s_rbLen;
    if (wlen > RB_SIZE) {
        wlen = RB_SIZE;
    }
    if (wlen > 0) {
        memcpy(wb, s_rb, wlen);
    }
    s_rbLen = 0;
    portEXIT_CRITICAL(&s_rbMux);

    processWorkBuffer(wb, &wlen);

    if (wlen == 0) {
        return;
    }
    portENTER_CRITICAL(&s_rbMux);
    for (uint16_t i = 0; i < wlen; i++) {
        rbPushUnsafe(wb[i]);
    }
    portEXIT_CRITICAL(&s_rbMux);
}

static void updateLegacyLeds() {
    portENTER_CRITICAL(&s_ledMux);
    switch (s_legacyMode) {
        case 0:
            setChannelVisible(PIN_GREEN, 0);
            setChannelVisible(PIN_YELLOW, 0);
            setChannelVisible(PIN_RED, 0);
            break;
        case 1:
            if (millis() - s_lastBlink >= (unsigned)BLINK_INTERVAL) {
                s_lastBlink = millis();
                s_blinkState = !s_blinkState;
            }
            setChannelVisible(PIN_GREEN, s_blinkState ? 255 : 0);
            setChannelVisible(PIN_YELLOW, 0);
            setChannelVisible(PIN_RED, 0);
            break;
        case 2:
            setChannelVisible(PIN_GREEN, 255);
            setChannelVisible(PIN_YELLOW, 0);
            setChannelVisible(PIN_RED, 0);
            break;
        case 3:
            if (millis() - s_lastBlink >= (unsigned)BLINK_INTERVAL) {
                s_lastBlink = millis();
                s_blinkState = !s_blinkState;
            }
            setChannelVisible(PIN_GREEN, 0);
            setChannelVisible(PIN_YELLOW, s_blinkState ? 255 : 0);
            setChannelVisible(PIN_RED, 0);
            break;
        case 4:
            setChannelVisible(PIN_GREEN, 0);
            setChannelVisible(PIN_YELLOW, 255);
            setChannelVisible(PIN_RED, 0);
            break;
        case 5:
            if (millis() - s_lastBlink >= (unsigned)BLINK_INTERVAL) {
                s_lastBlink = millis();
                s_blinkState = !s_blinkState;
            }
            setChannelVisible(PIN_GREEN, 0);
            setChannelVisible(PIN_YELLOW, 0);
            setChannelVisible(PIN_RED, s_blinkState ? 255 : 0);
            break;
        case 6:
            setChannelVisible(PIN_GREEN, 0);
            setChannelVisible(PIN_YELLOW, 0);
            setChannelVisible(PIN_RED, 255);
            break;
        default:
            setChannelVisible(PIN_GREEN, 0);
            setChannelVisible(PIN_YELLOW, 0);
            setChannelVisible(PIN_RED, 0);
            break;
    }
    portEXIT_CRITICAL(&s_ledMux);
}

static void updateProtoLeds() {
    uint8_t g = 0, y = 0, r = 0;
    uint8_t mode;
    uint8_t mask;
    uint16_t period;
    uint8_t dg, dy, dr;
    uint8_t curveN;
    bool haveCurve;
    uint8_t curve[CURVE_MAX_N];

    portENTER_CRITICAL(&s_ledMux);
    if (s_engine != ENGINE_PROTO) {
        portEXIT_CRITICAL(&s_ledMux);
        return;
    }
    mode = s_protoMode;
    mask = s_protoMask;
    period = s_protoPeriod;
    dg = s_protoDg;
    dy = s_protoDy;
    dr = s_protoDr;
    curveN = s_curveN;
    haveCurve = s_haveCurve;
    if (curveN > CURVE_MAX_N) {
        curveN = CURVE_MAX_N;
    }
    memcpy(curve, s_curve, curveN);
    portEXIT_CRITICAL(&s_ledMux);

    if (mode == MODE_OFF) {
        setChannelVisible(PIN_GREEN, 0);
        setChannelVisible(PIN_YELLOW, 0);
        setChannelVisible(PIN_RED, 0);
        return;
    }
    unsigned long t = millis();
    uint32_t per = period == 0 ? PERIOD_MS_MIN : (uint32_t)period;

    if (mode == MODE_SOLID) {
        if (mask & 1) g = dg;
        if (mask & 2) y = dy;
        if (mask & 4) r = dr;
    } else if (mode == MODE_SYNC_BLINK) {
        uint32_t ph = (uint32_t)(t % per);
        bool on = (ph * 2u < per);
        if (mask & 1) g = on ? dg : 0;
        if (mask & 2) y = on ? dy : 0;
        if (mask & 4) r = on ? dr : 0;
    } else if (mode == MODE_BREATH_CURVE && haveCurve && curveN >= CURVE_MIN_N) {
        if (per < PERIOD_MS_MIN) per = PERIOD_MS_MIN;
        if (per > PERIOD_MS_MAX) per = PERIOD_MS_MAX;
        uint64_t span_us = (uint64_t)per * 1000ULL;
        if (span_us < 2000ULL) {
            span_us = 2000ULL;
        }
        uint64_t ph_us = (uint64_t)esp_timer_get_time() % span_us;
        double pos = (double)ph_us / (double)span_us * (double)curveN;
        while (pos >= (double)curveN) {
            pos -= (double)curveN;
        }
        uint16_t idx = (uint16_t)pos;
        if (idx >= curveN) idx = (uint16_t)(curveN - 1u);
        double frac = pos - (double)idx;
        uint8_t a = curve[idx];
        uint8_t b = curve[(idx + 1u) % (uint32_t)curveN];
        uint16_t base = (uint16_t)((double)a * (1.0 - frac) + (double)b * frac + 0.5);
        if (base > 255) base = 255;
        if (mask & 1) g = dutyScaledRound(dg, base);
        if (mask & 2) y = dutyScaledRound(dy, base);
        if (mask & 4) r = dutyScaledRound(dr, base);
    } else if (mode == MODE_BREATH) {
        bool rising = false;
        uint16_t lin = protoTriangleLinearHalf(per, &rising);
        uint16_t base = breathEnvelopeFromLinear(lin, rising);
        if (mask & 1) g = dutyScaledRound(dg, base);
        if (mask & 2) y = dutyScaledRound(dy, base);
        if (mask & 4) r = dutyScaledRound(dr, base);
    }
    setChannelVisible(PIN_GREEN, g);
    setChannelVisible(PIN_YELLOW, y);
    setChannelVisible(PIN_RED, r);
}

/** 与 loop 解耦：NimBLE/串口解析可能长时间占用 loop，呼吸需稳定刷新 PWM，否则会「长时间卡在峰值占空比」 */
static void pwmRefreshTask(void *param) {
    (void)param;
    const TickType_t dt = pdMS_TO_TICKS(1);
    TickType_t lastWake = xTaskGetTickCount();
    for (;;) {
        vTaskDelayUntil(&lastWake, dt);
        Engine_t eng;
        portENTER_CRITICAL(&s_ledMux);
        eng = s_engine;
        portEXIT_CRITICAL(&s_ledMux);
        if (eng == ENGINE_PROTO) {
            updateProtoLeds();
        }
    }
}

// --- BLE ---
class CmdCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pCharacteristic, NimBLEConnInfo& connInfo) override {
        (void)connInfo;
        std::string v = pCharacteristic->getValue();
        size_t n = v.length();
        if (n > 256) n = 256;
        portENTER_CRITICAL(&s_rbMux);
        for (size_t i = 0; i < n; i++) {
            rbPushUnsafe((uint8_t)v[i]);
        }
        portEXIT_CRITICAL(&s_rbMux);
    }
};

class ServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo) override {
        (void)pServer;
        (void)connInfo;
        Serial.println(F("[BLE] VibeLight 已连接"));
    }

    void onDisconnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo, int reason) override {
        (void)pServer;
        (void)connInfo;
        (void)reason;
        Serial.println(F("[BLE] 已断开，重新广播"));
        NimBLEDevice::getAdvertising()->start();
    }
};

static CmdCallbacks cmdCallbacks;
static ServerCallbacks serverCallbacks;

static void initBle() {
    NimBLEDevice::init(BLE_DEVICE_NAME);
    NimBLEServer* pServer = NimBLEDevice::createServer();
    pServer->setCallbacks(&serverCallbacks);
    NimBLEService* pSvc = pServer->createService(BLE_SERVICE_UUID);
    NimBLECharacteristic* pChr = pSvc->createCharacteristic(
        BLE_CHAR_UUID,
        NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
    pChr->setCallbacks(&cmdCallbacks);
    pSvc->start();
    NimBLEAdvertising* pAdv = NimBLEDevice::getAdvertising();
    pAdv->setName(BLE_DEVICE_NAME);
    pAdv->addServiceUUID(BLE_SERVICE_UUID);
    pAdv->enableScanResponse(true);
    pAdv->start();
}

void setup() {
    Serial.begin(115200);
    pwmHardwareInit();
    initBle();
    xTaskCreate(pwmRefreshTask, "tl_pwm", 6144, nullptr, TL_PWM_TASK_PRIO, nullptr);
    Serial.println(F("VibeLight firmware ready (legacy ASCII + proto v1)"));
}

void loop() {
    for (int n = 0; n < TL_SERIAL_DRAIN_MAX && Serial.available() > 0; n++) {
        rbPush((uint8_t)Serial.read());
    }
    processRingBuffer();
    Engine_t eng;
    portENTER_CRITICAL(&s_ledMux);
    eng = s_engine;
    portEXIT_CRITICAL(&s_ledMux);
    if (eng != ENGINE_PROTO) {
        updateLegacyLeds();
    }
    yield();
}
