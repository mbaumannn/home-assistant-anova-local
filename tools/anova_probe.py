"""Read-only GATT round-trip from the Home Assistant side (phase 1 check)."""
import asyncio

from bleak import BleakClient, BleakScanner

ADDR = "<cooker BLE MAC, redacted>"
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
