# 💡 Tapo Bulb Controller 1453

> **Note:** This is a personal vibecoding project built for my own use. The UI is in Turkish, but it's straightforward enough that you don't really need to know Turkish to use it — sliders, color pickers, and buttons are pretty universal.

A fast, local-network Windows desktop app to control **TP-Link Tapo smart bulbs** (L530, L535, and others) without going through the cloud. Built with Python + PyQt6.

---

## ⚠️ Before Anything Else — Required Setup

> **If you skip this, the app will find your bulbs but all commands will be rejected (HTTP 403).**

In the **Tapo mobile app**:

1. Tap your **profile picture** (top left of the home screen)
2. Go to **Third-Party Services**
3. Enable **Third-Party Compatibility**

That's it. Do this before you even open this app.

---

## 📥 Download

**[⬇️ Download TapoBulbController1453.exe](../../releases/latest)**

Windows only. No installation required — just run the exe.

> On first run the app will ask for your Tapo credentials and scan your network for bulbs automatically.

---

## 🚀 Before You Start

1. Your bulbs must already be **set up and working** in the official Tapo app
2. **Do not use Google or Apple sign-in** for your Tapo account — you must have a Tapo account with a regular **email + password**. Third-party login methods don't expose credentials this app can use
3. Enable **Third-Party Compatibility** as described above ⬆️

---

## ⚡ Why This Exists

The official Tapo app routes every command through TP-Link's cloud servers even when you're sitting in the same room as your bulbs. This adds ~3–7 seconds of lag per command. This app talks **directly to the bulbs over your local network**, so commands execute in ~150ms.
This app:     Your PC → Router → Bulb   (~150ms, no internet)
Official app: App → TP-Link Cloud → Router → Bulb   (~3–7s)

---

## ✨ Features

- **Auto network scan** — discovers all Tapo bulbs on your Wi-Fi automatically
- **Individual bulb control** — brightness slider, color picker, quick color buttons, daylight mode, on/off per bulb
- **Global controls** — control all bulbs at once (brightness, daylight, random color, turn off all)
- **6 customizable profiles** — save your favorite scenes with custom names (right-click a profile to manage)
- **Random color** — assigns a different random color to each bulb without touching brightness
- **Fluid layout** — window resizes dynamically, columns adjust to however many bulbs you have
- **Fully local** — commands never leave your home network
- **Configurable daylight temperature** — set anywhere from 2500K (warm/amber) to 6500K (cool/daylight) in settings
- **Config stored locally** — credentials and profiles saved to `~/.tapo_control_config.json`

---

## 🔧 Running From Source

```bash
# Clone the repo
git clone https://github.com/krmrbtn/Tapo-Bulb-PC-Controller.git
cd Tapo-Bulb-PC-Controller

# Create a virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install python-kasa PyQt6

# Run
python tapo_control_ipscan.py
```

### Build the exe yourself

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --collect-all PyQt6 --collect-all kasa --icon=icon.ico --add-data="icon.ico;." --name "TapoBulbController1453" tapo_control_ipscan.py
```

Output will be at `dist\TapoBulbController1453.exe`

---

## 📁 Repo Structure

- **tapo_control_ipscan.py** — Main app, latest version with network scan and profile support
- **tapo_control_profiles.py** — Older version with profiles, before the network scan feature
- **tapo_control.py** — Early version, basic controls only
- **bulb_control.py** — Initial test script, the very first prototype
- **rainbow.py** — Rainbow effect experiment (didn't make it into the main app)
- **icon.ico** — App icon

---

## ⚠️ Known Issues

- **TPAP encryption**: Some newer Tapo firmware versions use a `TPAP` encryption scheme not yet supported by python-kasa. If your bulbs are discovered but commands fail, try toggling Third-Party Compatibility off and back on in the Tapo app — this sometimes reverts the firmware to a supported encryption mode
- **Network scan finds nothing**: Check for active VPNs (Cloudflare WARP, NordVPN, etc.), AP isolation / guest network separation on your router, or multiple network adapters confusing the broadcast. The app will show a detailed troubleshooting guide and let you enter the broadcast address manually if auto-detection fails
- **Antivirus warnings**: PyInstaller-packed executables sometimes trigger false positives. Full source is available here for review

---

## 📝 License


GPL-3.0 — because [python-kasa](https://github.com/python-kasa/python-kasa) 
and [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) are both GPL-3.0 licensed,
this project inherits the same license. Source code is fully available in this repo.

---

*Built with [python-kasa](https://github.com/python-kasa/python-kasa) (GPL-3.0) and [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) (GPL-3.0).*
