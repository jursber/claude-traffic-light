"""
BLE 冒烟测试：扫描 CC-TrafficLight 并写入一字节。

用法（在仓库根目录）:
  pip install -r requirements.txt
  pytest tests/test_ble.py -q
  或: python tests/test_ble.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from claude_tl.config import BLE_CHAR_UUID, BLE_DEVICE_NAME


async def run_test(cmd: str) -> None:
    from bleak import BleakClient, BleakScanner

    print("扫描设备:", BLE_DEVICE_NAME)
    dev = await BleakScanner.find_device_by_name(BLE_DEVICE_NAME, timeout=15.0)
    if dev is None:
        print("未找到设备")
        sys.exit(1)
    print("已发现:", dev.name, dev.address)
    async with BleakClient(dev) as client:
        if not client.is_connected:
            print("连接失败")
            sys.exit(1)
        payload = cmd.encode("ascii")[:1]
        await client.write_gatt_char(BLE_CHAR_UUID, payload, response=False)
        print("已写入", repr(cmd))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="g")
    args = ap.parse_args()
    if len(args.cmd) != 1:
        sys.exit(2)
    asyncio.run(run_test(args.cmd))


if __name__ == "__main__":
    main()
