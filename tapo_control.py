import sys
import json
import asyncio
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QSlider, QPushButton, QColorDialog, QGroupBox, QMessageBox,
    QDialog, QLineEdit, QFormLayout, QDialogButtonBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from kasa import Discover, Module

# ============ AYARLAR ============
TRANSITION_MS = 500
CONFIG_FILE = Path.home() / ".tapo_control_config.json"


# =================================


# ============ CONFIG YÖNETİMİ ============
def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


class ConfigDialog(QDialog):
    """İlk açılışta veya ayar değiştirirken bilgileri sorar."""

    def __init__(self, existing_config=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tapo Kontrol - Ayarlar")
        self.setMinimumWidth(420)

        layout = QVBoxLayout()

        info = QLabel(
            "Tapo hesap bilgilerinizi ve ampul IP adreslerini girin.\n"
            "Bu bilgiler bilgisayarınızda yerel olarak saklanır."
        )
        info.setStyleSheet("color: #555; padding: 6px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("ornek@gmail.com")
        form.addRow("Tapo E-posta:", self.email_input)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Tapo şifreniz")
        form.addRow("Tapo Şifre:", self.password_input)

        self.bulb1_name = QLineEdit("Ampul 1")
        form.addRow("1. Ampul Adı:", self.bulb1_name)

        self.bulb1_ip = QLineEdit()
        self.bulb1_ip.setPlaceholderText("192.168.1.100")
        form.addRow("1. Ampul IP:", self.bulb1_ip)

        self.bulb2_name = QLineEdit("Ampul 2")
        form.addRow("2. Ampul Adı:", self.bulb2_name)

        self.bulb2_ip = QLineEdit()
        self.bulb2_ip.setPlaceholderText("192.168.1.101")
        form.addRow("2. Ampul IP:", self.bulb2_ip)

        layout.addLayout(form)

        # Mevcut config'i doldur
        if existing_config:
            self.email_input.setText(existing_config.get("email", ""))
            self.password_input.setText(existing_config.get("password", ""))
            bulbs = existing_config.get("bulbs", [])
            if len(bulbs) >= 1:
                self.bulb1_name.setText(bulbs[0].get("name", "Ampul 1"))
                self.bulb1_ip.setText(bulbs[0].get("ip", ""))
            if len(bulbs) >= 2:
                self.bulb2_name.setText(bulbs[1].get("name", "Ampul 2"))
                self.bulb2_ip.setText(bulbs[1].get("ip", ""))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def validate_and_accept(self):
        if not self.email_input.text().strip():
            QMessageBox.warning(self, "Eksik", "E-posta girilmedi.")
            return
        if not self.password_input.text():
            QMessageBox.warning(self, "Eksik", "Şifre girilmedi.")
            return
        if not self.bulb1_ip.text().strip() or not self.bulb2_ip.text().strip():
            QMessageBox.warning(self, "Eksik", "İki ampulün de IP adresi girilmeli.")
            return
        self.accept()

    def get_config(self):
        return {
            "email": self.email_input.text().strip(),
            "password": self.password_input.text(),
            "bulbs": [
                {"name": self.bulb1_name.text().strip() or "Ampul 1",
                 "ip": self.bulb1_ip.text().strip()},
                {"name": self.bulb2_name.text().strip() or "Ampul 2",
                 "ip": self.bulb2_ip.text().strip()},
            ]
        }


# ============ KASA İŞLEMLERİ ============
class KasaCommands:
    """Config'i tek seferde okuyup komutları gönderir."""

    def __init__(self, config):
        self.email = config["email"]
        self.password = config["password"]

    async def _get_bulb(self, ip):
        bulb = await Discover.discover_single(
            ip, username=self.email, password=self.password
        )
        await bulb.update()
        return bulb

    async def set_brightness(self, ip, value):
        bulb = await self._get_bulb(ip)
        try:
            light = bulb.modules[Module.Light]
            if not bulb.is_on:
                await bulb.turn_on()
            await light.set_brightness(value, transition=TRANSITION_MS)
        finally:
            await bulb.disconnect()

    async def set_color(self, ip, h, s, v):
        bulb = await self._get_bulb(ip)
        try:
            light = bulb.modules[Module.Light]
            if not bulb.is_on:
                await bulb.turn_on()
            await light.set_hsv(h, s, v, transition=TRANSITION_MS)
        finally:
            await bulb.disconnect()

    async def set_daylight(self, ip):
        """Gün ışığı: 2500K, parlaklık 100."""
        bulb = await self._get_bulb(ip)
        try:
            light = bulb.modules[Module.Light]
            if not bulb.is_on:
                await bulb.turn_on()
            await light.set_color_temp(2500, transition=TRANSITION_MS)
            await light.set_brightness(100, transition=TRANSITION_MS)
        finally:
            await bulb.disconnect()

    async def turn_off(self, ip):
        bulb = await self._get_bulb(ip)
        try:
            await bulb.turn_off()
        finally:
            await bulb.disconnect()

    # ---- Global (paralel) komutlar ----
    async def set_brightness_all(self, ips, value):
        await asyncio.gather(*[self.set_brightness(ip, value) for ip in ips])

    async def set_daylight_all(self, ips):
        await asyncio.gather(*[self.set_daylight(ip) for ip in ips])

    async def turn_off_all(self, ips):
        await asyncio.gather(*[self.turn_off(ip) for ip in ips])


class AsyncWorker(QThread):
    """Asenkron Kasa komutlarını arka planda çalıştırır."""
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, coro_func, *args, **kwargs):
        super().__init__()
        self.coro_func = coro_func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.coro_func(*self.args, **self.kwargs))
            loop.close()
            self.finished_signal.emit(True, "")
        except Exception as e:
            self.finished_signal.emit(False, str(e))


# ============ GUI ============
class BulbPanel(QGroupBox):
    """Tek bir ampul için kontrol paneli."""

    def __init__(self, name, ip, kasa, parent_window):
        super().__init__(name)
        self.ip = ip
        self.name = name
        self.kasa = kasa
        self.parent_window = parent_window
        self.current_color = QColor(255, 255, 255)
        self.workers = []

        layout = QVBoxLayout()
        layout.setSpacing(8)

        ip_label = QLabel(f"IP: {ip}")
        ip_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(ip_label)

        self.brightness_label = QLabel("Parlaklık: 75")
        layout.addWidget(self.brightness_label)

        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(1, 100)
        self.brightness_slider.setValue(75)
        self.brightness_slider.valueChanged.connect(self.on_brightness_changed)
        self.brightness_slider.sliderReleased.connect(self.apply_brightness)
        layout.addWidget(self.brightness_slider)

        self.color_btn = QPushButton("🎨 Renk Seç")
        self.color_btn.clicked.connect(self.pick_color)
        self.color_btn.setMinimumHeight(40)
        layout.addWidget(self.color_btn)

        self.daylight_btn = QPushButton("☀️ Gün Işığı")
        self.daylight_btn.clicked.connect(self.set_daylight)
        self.daylight_btn.setMinimumHeight(40)
        layout.addWidget(self.daylight_btn)

        layout.addStretch()  # Elemanları yukarı toplar
        self.setLayout(layout)

    def on_brightness_changed(self, value):
        self.brightness_label.setText(f"Parlaklık: {value}")

    def set_brightness_from_global(self, value):
        """Global slider değiştiğinde kendi slider'ını da güncelle."""
        self.brightness_slider.blockSignals(True)
        self.brightness_slider.setValue(value)
        self.brightness_slider.blockSignals(False)
        self.brightness_label.setText(f"Parlaklık: {value}")

    def apply_brightness(self):
        value = self.brightness_slider.value()
        self.run_async(self.kasa.set_brightness, self.ip, value)

    def pick_color(self):
        color = QColorDialog.getColor(self.current_color, self, "Renk Seç")
        if color.isValid():
            self.current_color = color
            self.color_btn.setStyleSheet(
                f"background-color: {color.name()}; color: "
                f"{'white' if color.lightness() < 128 else 'black'};"
            )
            h, s, v, _ = color.getHsv()
            h_tapo = h if h >= 0 else 0
            s_tapo = int(s / 255 * 100)
            v_tapo = max(1, int(v / 255 * 100))
            self.run_async(self.kasa.set_color, self.ip, h_tapo, s_tapo, v_tapo)

    def set_daylight(self):
        self.run_async(self.kasa.set_daylight, self.ip)

    def run_async(self, coro_func, *args):
        self.parent_window.set_status(f"{self.name}: Komut gönderiliyor...")
        worker = AsyncWorker(coro_func, *args)
        worker.finished_signal.connect(self.on_command_finished)
        worker.finished.connect(
            lambda: self.workers.remove(worker) if worker in self.workers else None
        )
        self.workers.append(worker)
        worker.start()

    def on_command_finished(self, success, error_msg):
        if success:
            self.parent_window.set_status(f"{self.name}: ✓ Tamam")
        else:
            self.parent_window.set_status(f"{self.name}: ✗ Hata")
            QMessageBox.warning(self, "Hata", f"{self.name}\n\n{error_msg}")


class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.kasa = KasaCommands(config)
        self.ips = [b["ip"] for b in config["bulbs"]]
        self.global_workers = []

        self.setWindowTitle("Tapo L530 Kontrol")
        self.setMinimumSize(640, 520)

        central = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(12, 12, 12, 12)

        # ---- Üst: Ampul panelleri ----
        bulbs_layout = QHBoxLayout()
        bulbs_layout.setSpacing(10)
        self.panels = []
        for cfg in config["bulbs"]:
            panel = BulbPanel(cfg["name"], cfg["ip"], self.kasa, self)
            self.panels.append(panel)
            bulbs_layout.addWidget(panel)
        main_layout.addLayout(bulbs_layout, stretch=2)

        # ---- Orta: Global kontroller ----
        global_group = QGroupBox("🌐 Global Kontroller (Tümü)")
        global_layout = QVBoxLayout()
        global_layout.setSpacing(8)

        self.global_brightness_label = QLabel("Tüm Parlaklık: 75")
        global_layout.addWidget(self.global_brightness_label)

        self.global_brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.global_brightness_slider.setRange(1, 100)
        self.global_brightness_slider.setValue(75)
        self.global_brightness_slider.valueChanged.connect(self.on_global_brightness_changed)
        self.global_brightness_slider.sliderReleased.connect(self.apply_global_brightness)
        global_layout.addWidget(self.global_brightness_slider)

        global_buttons = QHBoxLayout()

        self.global_daylight_btn = QPushButton("☀️ Hepsine Gün Işığı")
        self.global_daylight_btn.setMinimumHeight(42)
        self.global_daylight_btn.clicked.connect(self.global_daylight)
        global_buttons.addWidget(self.global_daylight_btn)

        self.off_btn = QPushButton("💤 HEPSİNİ KAPAT")
        self.off_btn.setMinimumHeight(42)
        self.off_btn.setStyleSheet(
            "font-weight: bold; background-color: #333; color: white; border-radius: 4px;"
        )
        self.off_btn.clicked.connect(self.turn_off_all)
        global_buttons.addWidget(self.off_btn)

        global_layout.addLayout(global_buttons)
        global_group.setLayout(global_layout)
        main_layout.addWidget(global_group, stretch=1)

        # ---- Alt: Durum + Ayarlar butonu ----
        bottom_layout = QHBoxLayout()

        self.status_label = QLabel("Hazır")
        self.status_label.setStyleSheet(
            "padding: 6px; background-color: #f0f0f0; border-radius: 4px;"
        )
        bottom_layout.addWidget(self.status_label, stretch=1)

        self.settings_btn = QPushButton("⚙️ Ayarlar")
        self.settings_btn.clicked.connect(self.open_settings)
        bottom_layout.addWidget(self.settings_btn)

        main_layout.addLayout(bottom_layout)

        central.setLayout(main_layout)
        self.setCentralWidget(central)

    def set_status(self, text):
        self.status_label.setText(text)

    def on_global_brightness_changed(self, value):
        self.global_brightness_label.setText(f"Tüm Parlaklık: {value}")
        # Bireysel slider'ları da güncelle (görsel sync)
        for panel in self.panels:
            panel.set_brightness_from_global(value)

    def apply_global_brightness(self):
        value = self.global_brightness_slider.value()
        self.run_global_async(self.kasa.set_brightness_all, self.ips, value)

    def global_daylight(self):
        self.run_global_async(self.kasa.set_daylight_all, self.ips)

    def turn_off_all(self):
        self.run_global_async(self.kasa.turn_off_all, self.ips)

    def run_global_async(self, coro_func, *args):
        self.set_status("Global komut gönderiliyor...")
        worker = AsyncWorker(coro_func, *args)
        worker.finished_signal.connect(self.on_global_finished)
        worker.finished.connect(
            lambda: self.global_workers.remove(worker) if worker in self.global_workers else None
        )
        self.global_workers.append(worker)
        worker.start()

    def on_global_finished(self, success, error_msg):
        if success:
            self.set_status("✓ Global komut tamamlandı")
        else:
            self.set_status("✗ Global komut hatası")
            QMessageBox.warning(self, "Hata", error_msg)

    def open_settings(self):
        dialog = ConfigDialog(existing_config=self.config, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_config = dialog.get_config()
            save_config(new_config)
            QMessageBox.information(
                self, "Kaydedildi",
                "Ayarlar kaydedildi. Değişikliklerin etkili olması için "
                "programı yeniden başlatın."
            )


def main():
    app = QApplication(sys.argv)

    config = load_config()

    # Config yoksa ya da eksikse sihirbazı aç
    if not config or "email" not in config or "bulbs" not in config:
        dialog = ConfigDialog()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            config = dialog.get_config()
            save_config(config)
        else:
            sys.exit(0)  # İptal edildiyse çık

    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()