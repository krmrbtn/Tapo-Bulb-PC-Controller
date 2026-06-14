import asyncio
import json
import sys
from pathlib import Path
from kasa import Discover, Module

# Shared with tapo_control*.py: email, password and bulbs are read from this file,
# which is created by the GUI on first launch. Nothing sensitive lives in the code.
CONFIG_FILE = Path.home() / ".tapo_control_config.json"


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        sys.exit(f"Config not found or invalid: {CONFIG_FILE}\n"
                 "Run tapo_control.py once to create it.")


async def connect_bulb(ip, username, password):
    bulb = await Discover.discover_single(ip, username=username, password=password)
    await bulb.update()
    return bulb


async def smooth_rainbow(bulbs, duration=60, step_seconds=2):
    """
    Donanımsal smooth geçişle rainbow.
    step_seconds: her renk geçişi kaç saniyede tamamlansın
    """
    lights = [b.modules[Module.Light] for b in bulbs]

    for bulb in bulbs:
        await bulb.turn_on()

    # Geçiş süresi MILISANIYE cinsinden
    transition_ms = int(step_seconds * 1000)

    elapsed = 0
    hue = 0

    while elapsed < duration:
        # transition parametresi ampule "bu renge X ms'de yumuşakça geç" diyor
        tasks = [
            light.set_hsv(hue, 100, 100, transition=transition_ms)
            for light in lights
        ]
        await asyncio.gather(*tasks)

        hue = (hue + 30) % 360  # Daha büyük adım, çünkü ampul aradaki geçişi yapacak
        await asyncio.sleep(step_seconds)  # Geçiş bitene kadar bekle
        elapsed += step_seconds


async def main():
    config = load_config()
    username, password = config["email"], config["password"]
    bulb_ips = [b["ip"] for b in config["bulbs"]]

    print("Bağlanılıyor...")
    bulbs = await asyncio.gather(*[connect_bulb(ip, username, password) for ip in bulb_ips])
    print(f"{len(bulbs)} ampul hazır!")

    try:
        print("Smooth rainbow başlıyor (donanımsal geçiş)...")
        await smooth_rainbow(bulbs, duration=60, step_seconds=2)
    finally:
        for bulb in bulbs:
            await bulb.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
