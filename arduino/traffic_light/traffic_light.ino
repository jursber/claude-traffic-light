/*
 * =============================================================================
 * Claude Code 硬件红绿灯 — ESP32-C3 固件
 * =============================================================================
 *
 * 【功能概述】
 *   根据 PC 端（守护进程）发来的单字节命令，驱动三色 LED 的常亮 / 闪烁 / 全灭。
 *   支持两条通道（可同时使用）：
 *     1) USB 虚拟串口，115200 波特率，与早期版本兼容；
 *     2) BLE GATT：手机或电脑通过蓝牙写入同一套命令（需安装 NimBLE-Arduino）。
 *
 * 【命令与含义】（须与仓库根目录 config.py 里 COMMANDS 的约定一致）
 *   字符   灯光效果           在 CC/Codex 侧的典型含义
 *   ----   ----------------   ----------------------------------------
 *   'G'    绿灯闪烁           正在调用模型、等待 API 返回
 *   'g'    绿灯常亮           已有回复，正在写代码 / 跑工具
 *   'y'    黄灯闪烁           思考中
 *   'Y'    黄灯常亮           预留，当前 PC 端未使用
 *   'r'    红灯闪烁           需授权 / 报错 / 向你提问
 *   'R'    红灯常亮           一轮回复结束，等待你输入
 *   'O'    全灭               会话结束 / 关灯
 *   其它   忽略               不改变当前灯态
 *
 * 【硬件接线】（本工程使用「低电平点亮」：输出 0 时 LED 亮）
 *   GPIO0 → 绿色 LED 模块
 *   GPIO1 → 黄色 LED 模块
 *   GPIO2 → 红色 LED 模块
 *   （具体共阳/共阴接法以你的模块为准；此处 digitalWrite 低为「亮」）
 *
 * 【依赖】
 *   库管理器搜索并安装：NimBLE-Arduino（作者 h2zero）
 *   开发板菜单建议：USB CDC On Boot = Enabled，便于 USB 串口调试
 *
 * =============================================================================
 */

// NimBLE：轻量 BLE 协议栈，在 ESP32 系列上常用；须单独在 Arduino 库管理器中安装
#include <NimBLEDevice.h>

// -----------------------------------------------------------------------------
// GPIO 电平约定（有源低：写入 LOW/0 表示「点亮」该路）
// -----------------------------------------------------------------------------
#define On  0x0   // 引脚拉低 → LED 亮
#define Off 0x1   // 引脚拉高 → LED 灭

// 与 README 中接线说明一致；若你改硬件，请同步修改这三处
const int PIN_GREEN  = 0;
const int PIN_YELLOW = 1;
const int PIN_RED    = 2;

// -----------------------------------------------------------------------------
// BLE 广播名与 UUID（须与 PC 端 config.py 中 BLE_* 常量完全一致，否则连不上）
// -----------------------------------------------------------------------------
#define BLE_DEVICE_NAME  "CC-TrafficLight"  // 手机/电脑扫描时看到的设备名
#define BLE_SERVICE_UUID "e52c12b6-7ac3-4636-9c17-3d608bcea796"
#define BLE_CHAR_UUID    "e52c12b7-7ac3-4636-9c17-3d608bcea796"  // 中央设备向此特征「写」单字节命令

// -----------------------------------------------------------------------------
// 闪烁动画用的状态变量
// -----------------------------------------------------------------------------
unsigned long lastBlink = 0;       // 上次翻转闪烁相位的时间戳（millis）
bool blinkState = false;           // 当前闪烁半周期内「亮段」还是「暗段」
const int BLINK_INTERVAL = 500;    // 闪烁半周期约 500ms，即约 1Hz 视觉频率

// -----------------------------------------------------------------------------
// 内部灯效模式（与 applyCommand / updateLeds 中的 switch 分支一一对应）
//   0 = 全灭
//   1 = 绿闪   2 = 绿常   3 = 黄闪   4 = 黄常   5 = 红闪   6 = 红常
// -----------------------------------------------------------------------------
int mode = 0;

/**
 * 同时设置三路 LED 的亮灭（参数 true 表示该色「点亮」）
 */
void setAll(bool g, bool y, bool r) {
    digitalWrite(PIN_GREEN,  g ? On : Off);
    digitalWrite(PIN_YELLOW, y ? On : Off);
    digitalWrite(PIN_RED,    r ? On : Off);
}

/**
 * 解析来自 USB 串口或 BLE 的单个命令字符，只更新内部 mode，不直接改 GPIO。
 * 连续无效字符会被忽略，灯保持上一状态。
 */
void applyCommand(char cmd) {
    switch (cmd) {
        case 'G': mode = 1; break;  // 绿灯闪烁
        case 'g': mode = 2; break;  // 绿灯常亮
        case 'y': mode = 3; break;  // 黄灯闪烁
        case 'Y': mode = 4; break;  // 黄灯常亮（预留）
        case 'r': mode = 5; break;  // 红灯闪烁
        case 'R': mode = 6; break;  // 红灯常亮
        case 'O': mode = 0; break;  // 全灭 / 关灯
        default: break;             // 未知命令：不修改 mode
    }
}

/**
 * 根据当前 mode 刷新 GPIO；对闪烁类模式用 millis() 做非阻塞计时。
 * 注意：本函数应在 loop() 中频繁调用，才能保证闪烁流畅。
 */
void updateLeds() {
    switch (mode) {
        case 0:  // 全灭
            setAll(false, false, false);
            break;
        case 1:  // 绿灯闪烁
            if (millis() - lastBlink >= BLINK_INTERVAL) {
                lastBlink = millis();
                blinkState = !blinkState;
                setAll(blinkState, false, false);
            }
            break;
        case 2:  // 绿灯常亮
            setAll(true, false, false);
            break;
        case 3:  // 黄灯闪烁
            if (millis() - lastBlink >= BLINK_INTERVAL) {
                lastBlink = millis();
                blinkState = !blinkState;
                setAll(false, blinkState, false);
            }
            break;
        case 4:  // 黄灯常亮
            setAll(false, true, false);
            break;
        case 5:  // 红灯闪烁
            if (millis() - lastBlink >= BLINK_INTERVAL) {
                lastBlink = millis();
                blinkState = !blinkState;
                setAll(false, false, blinkState);
            }
            break;
        case 6:  // 红灯常亮
            setAll(false, false, true);
            break;
    }
}

/**
 * GATT 特征被中央设备「写入」时回调。
 * 一次写入可能包含多个字节：依次当作多条命令处理（与串口连续发多字符行为类似）。
 */
class CmdCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pCharacteristic, NimBLEConnInfo& connInfo) override {
        (void)connInfo;  // 当前逻辑不区分是哪台手机/电脑，故未使用连接信息
        std::string v = pCharacteristic->getValue();
        for (size_t i = 0; i < v.length(); i++) {
            applyCommand(v[i]);
        }
    }
};

/**
 * 连接生命周期：仅「建立链路」不会改灯色；灯只会在收到 GATT 写（或 USB 串口字节）时变化。
 * 用 USB 串口监视器可看到连接/断开提示，便于排查「已配对但灯不动」的误解。
 */
class ServerCallbacks : public NimBLEServerCallbacks {
    void onConnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo) override {
        (void)pServer;
        (void)connInfo;
        Serial.println(F("[BLE] 已连接：配对/连上后灯不会自动变，需 PC 写入命令或运行 test_ble.py"));
    }

    void onDisconnect(NimBLEServer* pServer, NimBLEConnInfo& connInfo, int reason) override {
        (void)pServer;
        (void)connInfo;
        (void)reason;  // 断开原因码；本灯控逻辑不需要区分，仅满足虚函数签名
        Serial.println(F("[BLE] 已断开，重新广播中"));
        NimBLEDevice::getAdvertising()->start();
    }
};

// 回调对象必须在整个程序生命周期内有效，故使用静态全局实例（避免悬空指针）
static CmdCallbacks cmdCallbacks;
static ServerCallbacks serverCallbacks;

/**
 * 初始化 NimBLE：建服务、特征、广播，并开始对外可见。
 * 特征属性含 WRITE 与 WRITE_NR（无响应写），便于 PC 端高频只发命令、不等待回包。
 */
void initBle() {
    // 设备名会出现在扫描列表，并与 PC 默认搜索名一致
    NimBLEDevice::init(BLE_DEVICE_NAME);

    NimBLEServer* pServer = NimBLEDevice::createServer();
    pServer->setCallbacks(&serverCallbacks);

    NimBLEService* pSvc = pServer->createService(BLE_SERVICE_UUID);
    NimBLECharacteristic* pChr = pSvc->createCharacteristic(
        BLE_CHAR_UUID,
        NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR
    );
    pChr->setCallbacks(&cmdCallbacks);
    pSvc->start();

    // 广播里带上服务 UUID，便于 PC（如 bleak）按 UUID 过滤；Scan Response 里带设备名
    NimBLEAdvertising* pAdv = NimBLEDevice::getAdvertising();
    pAdv->setName(BLE_DEVICE_NAME);
    pAdv->addServiceUUID(BLE_SERVICE_UUID);
    pAdv->enableScanResponse(true);
    pAdv->start();
}

void setup() {
    // USB CDC 串口：波特率须与 PC 端 config.BAUD_RATE 一致
    Serial.begin(115200);

    pinMode(PIN_GREEN, OUTPUT);
    pinMode(PIN_YELLOW, OUTPUT);
    pinMode(PIN_RED, OUTPUT);
    setAll(false, false, false);  // 上电先关灯，避免随机引脚态闪一下

    initBle();  // 启动 BLE 栈并开始广播（与 USB 可同时工作）
}

void loop() {
    // 尽快读空串口接收缓冲区，避免 USB 侧短时间连发时丢字节
    while (Serial.available() > 0) {
        applyCommand((char)Serial.read());
    }

    // 根据 mode 刷新 LED；BLE 协议栈在后台任务运行，此处给一点延时让出 CPU
    updateLeds();
    delay(1);
}
