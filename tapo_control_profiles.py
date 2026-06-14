import sys
import json
import asyncio
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QSlider, QPushButton, QColorDialog, QGroupBox, QMessageBox,
    QDialog, QLineEdit, QFormLayout, QDialogButtonBox, QMenu, QInputDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QAction
from kasa import Discover, Module

# ============ AYARLAR ============
TRANSITION_MS = 500
CONFIG_FILE = Path.home() / ".tapo_control_config.json"
NUM_PROFILES = 6

# Hızlı renkler (isim, H, S, V)
QUICK_COLORS = [
    ("Kırmızı", 0, 100, 100),
    ("Yeşil", 120, 100, 100),
    ("Mavi", 240, 100, 100),
    ("Sarı", 60, 100, 100),
    ("Camgöbeği", 180, 100, 100),
    ("Magenta", 300, 100, 100),
]

# Renk paleti (Windows tema bağımsız, sabit)
STATUS_BG = "#2b2b2b"
STATUS_FG = "#ffffff"
PROFILE_ACTIVE_BG = "#4a90d9"  # Sade mavi
PROFILE_ACTIVE_FG = "#ffffff"


# =================================


# ============ CONFIG ============
def default_config():
    return {
        "email": "",
        "password": "",
        "bulbs": [],
        "profiles": [
            {"name": f"Profil {i + 1}", "data": None}
            for i in range(NUM_PROFILES)
        ]
    }


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                # Eski configlerde profil yoksa ekle
                if "profiles" not in cfg:
                    cfg["profiles"] = default_config()["profiles"]
                return cfg
        except Exception:
            return None
    return None


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


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

    # ---- Profil komutu: tek bağlantıda renk + parlaklık ----
    async def apply_state(self, ip, state):
        """state = {'mode': 'color'|'daylight', 'h': , 's': , 'v': , 'brightness': }"""
        bulb = await self._get_bulb(ip)
        try:
            light = bulb.modules[Module.Light]
            if not bulb.is_on:
                await bulb.turn_on()
            if state["mode"] == "daylight":
                await light.set_color_temp(2500, transition=TRANSITION_MS)
                await light.set_brightness(state["brightness"], transition=TRANSITION_MS)
            else:  # color
                await light.set_hsv(state["h"], state["s"], state["v"], transition=TRANSITION_MS)
        finally:
            await bulb.disconnect()

    # ---- Global komutlar ----
    async def set_brightness_all(self, ips, value):
        await asyncio.gather(*[self.set_brightness(ip, value) for ip in ips])

    async def set_daylight_all(self, ips):
        await asyncio.gather(*[self.set_daylight(ip) for ip in ips])

    async def turn_off_all(self, ips):
        await asyncio.gather(*[self.turn_off(ip) for ip in ips])

    async def apply_profile(self, bulb_states):
        """bulb_states = [(ip, state), (ip, state)]"""
        await asyncio.gather(*[self.apply_state(ip, s) for ip, s in bulb_states])


class AsyncWorker(QThread):
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

    # Bu ampulün state'i değiştiğinde main window'a haber verir
    state_changed = pyqtSignal()

    def __init__(self, name, ip, kasa, parent_window):
        super().__init__(name)
        self.ip = ip
        self.name = name
        self.kasa = kasa
        self.parent_window = parent_window
        self.workers = []

        # Son bilinen state (ampule ne komut yolladıysak)
        self.last_state = {
            "mode": "color",  # 'color' veya 'daylight'
            "h": 0, "s": 0, "v": 100,
            "brightness": 75
        }

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

        # Hızlı renk butonları (2x3 grid)
        colors_grid = QGridLayout()
        colors_grid.setSpacing(4)
        for i, (cname, h, s, v) in enumerate(QUICK_COLORS):
            btn = QPushButton()
            btn.setToolTip(cname)
            btn.setMinimumHeight(32)
            qcolor = QColor.fromHsv(h, int(s * 255 / 100), int(v * 255 / 100))
            btn.setStyleSheet(
                f"background-color: {qcolor.name()}; "
                f"border: 1px solid #888; border-radius: 4px;"
            )
            btn.clicked.connect(lambda _, hh=h, ss=s, vv=v: self.apply_quick_color(hh, ss, vv))
            colors_grid.addWidget(btn, i // 3, i % 3)
        layout.addLayout(colors_grid)

        self.color_btn = QPushButton("🎨 Renk Seç")
        self.color_btn.clicked.connect(self.pick_color)
        self.color_btn.setMinimumHeight(36)
        layout.addWidget(self.color_btn)

        self.daylight_btn = QPushButton("☀️ Gün Işığı")
        self.daylight_btn.clicked.connect(self.set_daylight)
        self.daylight_btn.setMinimumHeight(36)
        layout.addWidget(self.daylight_btn)

        self.off_btn = QPushButton("💤 Kapat")
        self.off_btn.clicked.connect(self.turn_off)
        self.off_btn.setMinimumHeight(36)
        layout.addWidget(self.off_btn)

        layout.addStretch()
        self.setLayout(layout)

    def on_brightness_changed(self, value):
        self.brightness_label.setText(f"Parlaklık: {value}")

    def update_slider_silently(self, value):
        """Slider'ı sinyal göndermeden günceller."""
        self.brightness_slider.blockSignals(True)
        self.brightness_slider.setValue(value)
        self.brightness_slider.blockSignals(False)
        self.brightness_label.setText(f"Parlaklık: {value}")

    def apply_brightness(self):
        value = self.brightness_slider.value()
        self.last_state["brightness"] = value
        if self.last_state["mode"] == "color":
            self.last_state["v"] = value
        self.state_changed.emit()
        self.run_async(self.kasa.set_brightness, self.ip, value)

    def apply_quick_color(self, h, s, v):
        self.last_state = {"mode": "color", "h": h, "s": s, "v": v, "brightness": v}
        self.update_slider_silently(v)
        self.state_changed.emit()
        self.run_async(self.kasa.set_color, self.ip, h, s, v)

    def pick_color(self):
        # Şu anki renk dialog'da gözüksün
        h = self.last_state["h"]
        s = int(self.last_state["s"] * 255 / 100)
        v = int(self.last_state["v"] * 255 / 100)
        initial = QColor.fromHsv(h, s, v) if self.last_state["mode"] == "color" else QColor(255, 255, 255)

        color = QColorDialog.getColor(initial, self, "Renk Seç")
        if color.isValid():
            qh, qs, qv, _ = color.getHsv()
            h_tapo = qh if qh >= 0 else 0
            s_tapo = int(qs / 255 * 100)
            v_tapo = max(1, int(qv / 255 * 100))
            self.last_state = {"mode": "color", "h": h_tapo, "s": s_tapo, "v": v_tapo, "brightness": v_tapo}
            self.update_slider_silently(v_tapo)
            self.state_changed.emit()
            self.run_async(self.kasa.set_color, self.ip, h_tapo, s_tapo, v_tapo)

    def set_daylight(self):
        self.last_state = {"mode": "daylight", "h": 0, "s": 0, "v": 100, "brightness": 100}
        self.update_slider_silently(100)
        self.state_changed.emit()
        self.run_async(self.kasa.set_daylight, self.ip)

    def turn_off(self):
        self.run_async(self.kasa.turn_off, self.ip)

    # Profil veya global komutla state güncellendiğinde dışarıdan çağrılır
    def set_state_external(self, state):
        self.last_state = dict(state)
        self.update_slider_silently(state["brightness"])

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


class ProfileButton(QPushButton):
    """Profil için özel buton, sağ tık menüsü desteği var."""
    right_clicked = pyqtSignal()

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda _: self.right_clicked.emit())


class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.kasa = KasaCommands(config)
        self.ips = [b["ip"] for b in config["bulbs"]]
        self.global_workers = []

        # Profil takibi
        self.active_profile_idx = None  # Hangi profil aktif (None = hiçbiri)
        self.profile_dirty = False  # Profil seçildikten sonra state değişti mi

        self.setWindowTitle("Tapo L530 Kontrol")
        self.setMinimumSize(720, 720)

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
            panel.state_changed.connect(self.on_bulb_state_changed)
            self.panels.append(panel)
            bulbs_layout.addWidget(panel)
        main_layout.addLayout(bulbs_layout, stretch=3)

        # ---- Global kontroller ----
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
        self.global_daylight_btn.setMinimumHeight(40)
        self.global_daylight_btn.clicked.connect(self.global_daylight)
        global_buttons.addWidget(self.global_daylight_btn)

        self.off_btn = QPushButton("💤 HEPSİNİ KAPAT")
        self.off_btn.setMinimumHeight(40)
        self.off_btn.setStyleSheet(
            "font-weight: bold; background-color: #444; color: white; border-radius: 4px;"
        )
        self.off_btn.clicked.connect(self.turn_off_all)
        global_buttons.addWidget(self.off_btn)
        global_layout.addLayout(global_buttons)

        global_group.setLayout(global_layout)
        main_layout.addWidget(global_group, stretch=1)

        # ---- Profil butonları ----
        profile_group = QGroupBox("📌 Profiller (sağ tık ile düzenle)")
        profile_layout = QGridLayout()
        profile_layout.setSpacing(6)
        self.profile_buttons = []
        for i in range(NUM_PROFILES):
            pname = self.config["profiles"][i]["name"]
            btn = ProfileButton(pname)
            btn.setMinimumHeight(40)
            btn.clicked.connect(lambda _, idx=i: self.apply_profile(idx))
            btn.right_clicked.connect(lambda idx=i: self.show_profile_menu(idx))
            self.profile_buttons.append(btn)
            profile_layout.addWidget(btn, i // 3, i % 3)
        profile_group.setLayout(profile_layout)
        main_layout.addWidget(profile_group, stretch=1)
        self.refresh_profile_buttons()

        # ---- Profili Güncelle butonu ----
        self.update_profile_btn = QPushButton("💾 Profili Güncelle")
        self.update_profile_btn.setMinimumHeight(36)
        self.update_profile_btn.clicked.connect(self.update_active_profile)
        self.update_profile_btn.setEnabled(False)
        main_layout.addWidget(self.update_profile_btn)

        # ---- Alt: Durum + Ayarlar ----
        bottom_layout = QHBoxLayout()
        self.status_label = QLabel("Hazır")
        self.status_label.setStyleSheet(
            f"padding: 8px; background-color: {STATUS_BG}; color: {STATUS_FG}; "
            f"border-radius: 4px; font-size: 12px;"
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

    # ---- Bireysel ampul state değiştiğinde ----
    def on_bulb_state_changed(self):
        # Bir profil aktifse ve manuel değişiklik olduysa "dirty" işaretle
        if self.active_profile_idx is not None:
            self.profile_dirty = True
            self.update_profile_btn.setEnabled(True)

    # ---- Global kontroller ----
    def on_global_brightness_changed(self, value):
        self.global_brightness_label.setText(f"Tüm Parlaklık: {value}")
        for panel in self.panels:
            panel.update_slider_silently(value)

    def apply_global_brightness(self):
        value = self.global_brightness_slider.value()
        # Tüm ampullerin son state'inde parlaklığı güncelle
        for panel in self.panels:
            panel.last_state["brightness"] = value
            if panel.last_state["mode"] == "color":
                panel.last_state["v"] = value
        self.on_bulb_state_changed()
        self.run_global_async(self.kasa.set_brightness_all, self.ips, value)

    def global_daylight(self):
        for panel in self.panels:
            panel.set_state_external({"mode": "daylight", "h": 0, "s": 0, "v": 100, "brightness": 100})
        self.on_bulb_state_changed()
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

    # ---- Profil yönetimi ----
    def refresh_profile_buttons(self):
        """Profil butonlarının görsel durumunu (aktif/inaktif, isim) günceller."""
        for i, btn in enumerate(self.profile_buttons):
            pname = self.config["profiles"][i]["name"]
            is_saved = self.config["profiles"][i]["data"] is not None
            is_active = (i == self.active_profile_idx)

            display_name = pname if is_saved else f"{pname} (boş)"
            btn.setText(display_name)

            if is_active:
                btn.setStyleSheet(
                    f"background-color: {PROFILE_ACTIVE_BG}; color: {PROFILE_ACTIVE_FG}; "
                    f"font-weight: bold; border-radius: 4px;"
                )
            else:
                btn.setStyleSheet("")

    def apply_profile(self, idx):
        profile = self.config["profiles"][idx]
        if profile["data"] is None:
            # Boş profil: ya isim ver ya da mevcut state'ten kaydet seçeneği sun
            reply = QMessageBox.question(
                self, "Boş Profil",
                f"'{profile['name']}' boş. Mevcut ampul ayarlarını bu profile kaydetmek ister misiniz?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.save_current_to_profile(idx)
            return

        # Profili uygula
        self.active_profile_idx = idx
        self.profile_dirty = False
        self.update_profile_btn.setEnabled(False)

        # Ampullere state'i bildir (slider güncelle vs.)
        bulb_states = []
        for panel_idx, panel in enumerate(self.panels):
            if panel_idx < len(profile["data"]):
                state = profile["data"][panel_idx]
                panel.set_state_external(state)
                bulb_states.append((panel.ip, state))

        self.refresh_profile_buttons()
        self.set_status(f"Profil '{profile['name']}' uygulanıyor...")

        worker = AsyncWorker(self.kasa.apply_profile, bulb_states)
        worker.finished_signal.connect(self.on_global_finished)
        worker.finished.connect(
            lambda: self.global_workers.remove(worker) if worker in self.global_workers else None
        )
        self.global_workers.append(worker)
        worker.start()

    def save_current_to_profile(self, idx):
        """Şu anki ampul state'lerini profile kaydet."""
        states = [dict(panel.last_state) for panel in self.panels]
        self.config["profiles"][idx]["data"] = states
        save_config(self.config)
        self.active_profile_idx = idx
        self.profile_dirty = False
        self.update_profile_btn.setEnabled(False)
        self.refresh_profile_buttons()
        self.set_status(f"Profil '{self.config['profiles'][idx]['name']}' kaydedildi.")

    def update_active_profile(self):
        if self.active_profile_idx is None:
            return
        self.save_current_to_profile(self.active_profile_idx)

    def show_profile_menu(self, idx):
        menu = QMenu(self)
        rename_action = QAction("✏️ İsmini Değiştir", self)
        rename_action.triggered.connect(lambda: self.rename_profile(idx))
        menu.addAction(rename_action)

        save_action = QAction("💾 Mevcut Ayarlardan Kaydet", self)
        save_action.triggered.connect(lambda: self.save_current_to_profile(idx))
        menu.addAction(save_action)

        if self.config["profiles"][idx]["data"] is not None:
            clear_action = QAction("🗑️ Profili Temizle", self)
            clear_action.triggered.connect(lambda: self.clear_profile(idx))
            menu.addAction(clear_action)

        menu.exec(self.profile_buttons[idx].mapToGlobal(
            self.profile_buttons[idx].rect().bottomLeft()
        ))

    def rename_profile(self, idx):
        current_name = self.config["profiles"][idx]["name"]
        new_name, ok = QInputDialog.getText(
            self, "Profili Yeniden Adlandır",
            "Yeni isim:", text=current_name
        )
        if ok and new_name.strip():
            self.config["profiles"][idx]["name"] = new_name.strip()
            save_config(self.config)
            self.refresh_profile_buttons()

    def clear_profile(self, idx):
        reply = QMessageBox.question(
            self, "Profili Temizle",
            f"'{self.config['profiles'][idx]['name']}' temizlensin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.config["profiles"][idx]["data"] = None
            if self.active_profile_idx == idx:
                self.active_profile_idx = None
                self.update_profile_btn.setEnabled(False)
            save_config(self.config)
            self.refresh_profile_buttons()

    # ---- Ayarlar ----
    def open_settings(self):
        dialog = ConfigDialog(existing_config=self.config, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_data = dialog.get_config()
            self.config["email"] = new_data["email"]
            self.config["password"] = new_data["password"]
            self.config["bulbs"] = new_data["bulbs"]
            save_config(self.config)
            QMessageBox.information(
                self, "Kaydedildi",
                "Ayarlar kaydedildi. Değişikliklerin etkili olması için "
                "programı yeniden başlatın."
            )


def main():
    app = QApplication(sys.argv)

    config = load_config()

    if not config or not config.get("email") or not config.get("bulbs"):
        dialog = ConfigDialog()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_data = dialog.get_config()
            config = default_config()
            config["email"] = new_data["email"]
            config["password"] = new_data["password"]
            config["bulbs"] = new_data["bulbs"]
            save_config(config)
        else:
            sys.exit(0)

    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()