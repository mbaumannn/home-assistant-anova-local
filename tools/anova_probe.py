"""Read-only Bluetooth check: connect to a cooker and ask for its version.

Useful to see whether a host can reach the cooker at all, without Home
Assistant in the way.

Usage:  python3 tools/anova_probe.py AA:BB:CC:DD:EE:FF
"""
import asyncio
import sys

from bleak import BleakClient, BleakScanner

ADDR = sys.argv[1]
CHAR = "0000ffe1-0000-1000-8000-00805f9b34fb"


async def main() -> None:
    dev = await BleakScanner.find_device_by_address(ADDR, timeout=20)
    assert dev, "Anova not in range"
    async with BleakClient(dev) as client:
        got: asyncio.Queue[bytes] = asyncio.Queue()
        await client.start_notify(CHAR, lambda _c, d: got.put_nowait(bytes(d)))
        await client.write_gatt_char(CHAR, b"version\r", response=False)
        print("answer:", await got.get())


asyncio.run(main())
