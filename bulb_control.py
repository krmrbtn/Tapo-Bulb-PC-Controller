import asyncio
import json
import sys
from pathlib import Path
from kasa import Discover, Module

# Shared with tapo_control*.py: email, password and bulbs are read from this file,
# which is created by the GUI on first launch. Nothing sensitive lives in the code.
CONFIG_FILE = Path.home() / ".tapo_control_config.json"

COLORS = {
    "red": (0, 100, 100),
    "green": (120, 100, 100),
    "blue": (240, 100, 100),
    "yellow": (60, 100, 100),
    "purple": (280, 100, 100),
    "cyan": (180, 100, 100),
    "orange": (30, 100, 100),
    "pink": (330, 80, 100),
}


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        sys.exit(f"Config not found or invalid: {CONFIG_FILE}\n"
                 "Run tapo_control.py once to create it.")


async def control_bulb(action, value=None, bulb_index=0):
    config = load_config()
    ip = config["bulbs"][bulb_index]["ip"]
    bulb = await Discover.discover_single(
        ip,
        username=config["email"],
        password=config["password"],
    )
    try:
        await bulb.update()
        light = bulb.modules[Module.Light]

        if action == "on":
            await bulb.turn_on()
        elif action == "off":
            await bulb.turn_off()
        elif action == "color" and value in COLORS:
            await bulb.turn_on()
            await light.set_hsv(*COLORS[value])
        elif action == "brightness":
            await light.set_brightness(int(value))
        elif action == "warm":  # Sıcak beyaz
            await light.set_color_temp(2700)
        elif action == "cool":  # Soğuk beyaz
            await light.set_color_temp(6500)
    finally:
        await bulb.disconnect()


# Kullanım:
if __name__ == "__main__":
    asyncio.run(control_bulb("color", "red"))
    asyncio.run(control_bulb("brightness", 10))
    # asyncio.run(control_bulb("off"))
