import sys
import json
import socket
import random
import asyncio
import ipaddress
import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QSlider, QPushButton, QColorDialog, QGroupBox, QMessageBox,
    QDialog, QLineEdit, QFormLayout, QDialogButtonBox, QMenu, QInputDialog,
    QScrollArea, QCheckBox, QFrame, QTextEdit, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QAction, QPainter, QBrush, QPen, QIcon
from kasa import Discover, Module
# ============ AYARLAR ============
TRANSITION_MS = 500
CONFIG_FILE = Path.home() / ".tapo_control_config.json"
NUM_PROFILES = 6

QUICK_COLORS = [
    ("Kırmızı", "#ff0000", 0, 100, 100),
    ("Sarı", "#ffff00", 60, 100, 100),
    ("Yeşil", "#00ff00", 120, 100, 100),
    ("Camgöbeği", "#00ffff", 180, 100, 100),
    ("Mavi", "#0000ff", 240, 100, 100),
    ("Magenta", "#ff00ff", 300, 100, 100),
]

STATUS_BG = "#2b2b2b"
STATUS_FG = "#ffffff"
PROFILE_ACTIVE_BG = "#4a90d9"
PROFILE_ACTIVE_FG = "#ffffff"
PANEL_MIN_WIDTH = 220


# =================================


# ============ AĞ TESPİTİ ============
def detect_broadcast_address():
    """Bilgisayarın yerel IP'sinden /24 broadcast adresini hesaplar."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # Gerçekten bağlanmaz, sadece routing tablosunu sorar
        local_ip = s.getsockname()[0]
        s.close()
        net = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
        return str(net.broadcast_address)
    except Exception:
        return "255.255.255.255"


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
                if "profiles" not in cfg:
                    cfg["profiles"] = default_config()["profiles"]
                return cfg
        except Exception:
            return None
    return None


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


class CredentialsDialog(QDialog):
    """Sadece email ve şifre soran, ilk açılış için basit dialog."""

    def __init__(self, existing=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tapo Kontrol - Hesap")
        self.setMinimumWidth(500)

        layout = QVBoxLayout()

        # Hazırlık adımları
        prep_group = QGroupBox("📋 Başlamadan Önce")
        prep_layout = QVBoxLayout()
        prep_text = QLabel(
            "<p><b>Programı kullanmadan önce şu adımları tamamladığınızdan emin olun:</b></p>"
            "<ol>"
            "<li>Ampulleriniz <b>Tapo uygulaması</b> ile kurulmuş, hesabınıza eşlenmiş ve "
            "halihazırda çalışıyor olmalı.</li>"
            "<li>Tapo hesabı oluştururken <b>Google / Apple ile giriş</b> gibi 3. parti yöntemler "
            "kullanmayın. Doğrudan <b>e-posta + şifre</b> ile bir Tapo hesabı oluşturun. "
            "Aksi halde bu programa giriş yapamazsınız.</li>"
            "<li>Tapo uygulaması ana ekranında sol üstteki <b>profil resmine</b> tıklayın → "
            "<b>Third-Party Services</b> (Üçüncü Taraf Hizmetleri) bölümüne girin → "
            "<b>Third-Party Compatibility</b> seçeneğini <b>açın</b>. Bu adımlar izlenmezse "
            "ampuller ağda görünmez veya komutları reddeder.</li>"
            "</ol>"
            "<p style='color: #888; font-size: 11px;'>Not: Bilgiler bilgisayarınızda yerel olarak "
            "saklanır, hiçbir yere gönderilmez.</p>"
        )
        prep_text.setWordWrap(True)
        prep_text.setStyleSheet("padding: 4px;")
        prep_layout.addWidget(prep_text)
        prep_group.setLayout(prep_layout)
        layout.addWidget(prep_group)

        # Footer
        footer = QLabel("krmrbtn 2026")
        footer.setStyleSheet("color: #aaa; padding: 2px; font-size: 10px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(footer)

        # Form
        form = QFormLayout()
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("ornek@gmail.com")
        form.addRow("Tapo E-posta:", self.email_input)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Tapo Şifre:", self.password_input)
        layout.addLayout(form)

        if existing:
            self.email_input.setText(existing.get("email", ""))
            self.password_input.setText(existing.get("password", ""))

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
        self.accept()

    def get_values(self):
        return self.email_input.text().strip(), self.password_input.text()


class ScanWorker(QThread):
    """Arka planda ağ taraması yapar."""
    finished_signal = pyqtSignal(list, str)  # devices, error

    def __init__(self, email, password, broadcast):
        super().__init__()
        self.email = email
        self.password = password
        self.broadcast = broadcast

    def run(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._scan())
            loop.close()
            self.finished_signal.emit(result, "")
        except Exception as e:
            self.finished_signal.emit([], str(e))

    async def _scan(self):
        # Adım 1: IP'leri keşfet
        discovered = await Discover.discover(timeout=5, target=self.broadcast)

        # Adım 2: Her IP için detayları al (discover_single ile, ayrı bağlantı)
        results = []
        for ip in discovered.keys():
            try:
                dev = await Discover.discover_single(
                    ip, username=self.email, password=self.password
                )
                await dev.update()
                results.append({
                    "ip": ip,
                    "name": dev.alias or "İsimsiz",
                    "model": dev.model or "Bilinmiyor",
                    "mac": dev.mac or "",
                    "is_on": dev.is_on,
                    "supported": True
                })
                await dev.disconnect()
            except Exception as e:
                results.append({
                    "ip": ip,
                    "name": "Erişilemedi",
                    "model": "?",
                    "mac": "",
                    "is_on": False,
                    "supported": False,
                    "error": str(e)
                })
        return results


class NetworkTroubleDialog(QDialog):
    """Ağda cihaz bulunamazsa açılır, manuel broadcast adresi girme ve troubleshooting."""

    def __init__(self, detected_broadcast, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ağda Cihaz Bulunamadı")
        self.setMinimumSize(560, 520)
        self.manual_broadcast = None

        layout = QVBoxLayout()

        title = QLabel("⚠️ Ağda hiç Tapo cihazı bulunamadı")
        title.setStyleSheet("font-size: 14px; font-weight: bold; padding: 6px;")
        layout.addWidget(title)

        info = QTextEdit()
        info.setReadOnly(True)
        info.setHtml("""
        <p><b>Olası nedenler ve çözümler:</b></p>

        <p><b>1. VPN veya WARP açık olabilir</b><br>
        Cloudflare WARP, NordVPN, ExpressVPN gibi servisler yerel ağ trafiğini bloklayabilir. 
        Bunları kapatıp tekrar deneyin. Sistem tepsisinde simgelerini bulup 
        <i>Disconnect</i> veya <i>Pause</i> seçin.</p>

        <p><b>2. GoodbyeDPI / Zapret / DPI bypass araçları</b><br>
        Türkiye'de yaygın kullanılan DPI atlatma araçları broadcast trafiğini bozabilir. 
        Geçici olarak kapatın ve tekrar deneyin.</p>

        <p><b>3. Birden fazla ağ adaptörü</b><br>
        Bilgisayarınızda Wi-Fi + Ethernet + sanal makineler (VirtualBox, VMware, Hyper-V) 
        + Bluetooth gibi birden çok ağ kartı varsa Python yanlış adaptörden tarama yapabilir. 
        Aşağıdaki manuel broadcast adresi yöntemini kullanın.</p>

        <p><b>4. Mesh router veya AP Isolation</b><br>
        Mesh sistemlerinde farklı node'lara bağlı cihazlar birbirini göremeyebilir. 
        Router yönetim panelinizden <i>AP Isolation</i>, <i>Client Isolation</i> veya 
        <i>Wireless Isolation</i> ayarını kapatın.</p>

        <p><b>5. Misafir ağı (Guest Network)</b><br>
        Ampulleriniz misafir ağına bağlıysa ana ağdan ulaşılamaz. Tapo uygulamasından 
        ampullerin hangi Wi-Fi'da olduğunu kontrol edin, bilgisayarınızı aynı ağa bağlayın.</p>

        <p><b>6. VLAN ayrımı</b><br>
        Router'ınızda VLAN tanımlıysa cihazlar farklı segmentlerde olabilir. Router'ınızın 
        manuel ayarlarına bakın.</p>

        <p><b>7. Windows Güvenlik Duvarı</b><br>
        Python.exe'nin "Özel ağlar" için izni olmayabilir. İlk çalıştırmada gelen 
        güvenlik duvarı sorusunu "Erişime izin ver" olarak yanıtlayın.</p>

        <hr>

        <p><b>Manuel broadcast adresi nasıl bulunur?</b></p>
        <ol>
            <li>Windows tuşu + R → <code>cmd</code> → Enter</li>
            <li><code>ipconfig</code> yazıp Enter</li>
            <li>Wi-Fi adaptörünüzü bulun (genelde "Kablosuz LAN bağdaştırıcısı Wi-Fi")</li>
            <li>"IPv4 Adresi" satırına bakın. Örnek: <code>192.168.1.42</code></li>
            <li>Bu IP'nin <b>son sayısını 255</b> yapın: <code>192.168.1.255</code></li>
            <li>Aşağıdaki kutuya bu adresi yazıp tekrar deneyin.</li>
        </ol>
        """)
        layout.addWidget(info)

        # Manuel adres alanı
        form_layout = QHBoxLayout()
        form_layout.addWidget(QLabel("Broadcast adresi:"))
        self.bc_input = QLineEdit()
        self.bc_input.setText(detected_broadcast)
        self.bc_input.setPlaceholderText("192.168.1.255")
        form_layout.addWidget(self.bc_input)
        layout.addLayout(form_layout)

        buttons = QDialogButtonBox()
        retry_btn = buttons.addButton("Tekrar Tara", QDialogButtonBox.ButtonRole.AcceptRole)
        cancel_btn = buttons.addButton("İptal", QDialogButtonBox.ButtonRole.RejectRole)
        retry_btn.clicked.connect(self._on_retry)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def _on_retry(self):
        addr = self.bc_input.text().strip()
        try:
            ipaddress.IPv4Address(addr)
            self.manual_broadcast = addr
            self.accept()
        except Exception:
            QMessageBox.warning(self, "Geçersiz adres", "Geçerli bir IP adresi girin.")


class ScanResultsDialog(QDialog):
    """Tarama sonuçlarını gösterir, checkbox ile seçim."""

    def __init__(self, devices, already_added_ips=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bulunan Ampuller")
        self.setMinimumSize(540, 400)
        self.selected_devices = []
        already_added_ips = already_added_ips or []

        layout = QVBoxLayout()

        info = QLabel(f"{len(devices)} cihaz bulundu. Eklemek istediklerinizi seçin:")
        info.setStyleSheet("padding: 4px; font-weight: bold;")
        layout.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        v = QVBoxLayout()
        v.setSpacing(4)

        self.checkboxes = []
        for dev in devices:
            already_added = dev["ip"] in already_added_ips
            row = QFrame()
            row.setFrameShape(QFrame.Shape.StyledPanel)
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(8, 4, 8, 4)

            cb = QCheckBox()
            if already_added:
                cb.setChecked(True)
                cb.setEnabled(False)
            elif not dev.get("supported", True):
                cb.setEnabled(False)
            row_layout.addWidget(cb)

            label_text = (
                f"<b>{dev['name']}</b><br>"
                f"<span style='color: #777; font-size: 11px;'>"
                f"IP: {dev['ip']}  ·  Model: {dev['model']}"
            )
            if already_added:
                label_text += "  ·  <i>(zaten ekli)</i>"
            elif not dev.get("supported", True):
                label_text += "  ·  <i>(erişilemedi - şifre/yetki?)</i>"
            label_text += "</span>"

            label = QLabel(label_text)
            row_layout.addWidget(label, stretch=1)
            row.setLayout(row_layout)
            v.addWidget(row)

            self.checkboxes.append((cb, dev, already_added))

        v.addStretch()
        container.setLayout(v)
        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Seçilenleri Ekle")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def _on_accept(self):
        for cb, dev, already_added in self.checkboxes:
            if cb.isChecked() and not already_added:
                self.selected_devices.append(dev)
        self.accept()


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
            try:
                await light.set_hsv(h, s, v, transition=TRANSITION_MS)
            except Exception:
                # Renksiz ampul ise (L510 gibi) set_hsv hata verebilir, brightness'a düş
                await light.set_brightness(v, transition=TRANSITION_MS)
        finally:
            await bulb.disconnect()

    async def set_daylight(self, ip):
        bulb = await self._get_bulb(ip)
        try:
            light = bulb.modules[Module.Light]
            if not bulb.is_on:
                await bulb.turn_on()
            try:
                await light.set_color_temp(2500, transition=TRANSITION_MS)
            except Exception:
                pass  # Color temp desteklemiyorsa atla
            await light.set_brightness(100, transition=TRANSITION_MS)
        finally:
            await bulb.disconnect()

    async def turn_off(self, ip):
        bulb = await self._get_bulb(ip)
        try:
            await bulb.turn_off()
        finally:
            await bulb.disconnect()

    async def apply_state(self, ip, state):
        bulb = await self._get_bulb(ip)
        try:
            light = bulb.modules[Module.Light]
            if not bulb.is_on:
                await bulb.turn_on()
            if state["mode"] == "daylight":
                try:
                    await light.set_color_temp(2500, transition=TRANSITION_MS)
                except Exception:
                    pass
                await light.set_brightness(state["brightness"], transition=TRANSITION_MS)
            else:
                try:
                    await light.set_hsv(state["h"], state["s"], state["v"], transition=TRANSITION_MS)
                except Exception:
                    await light.set_brightness(state["v"], transition=TRANSITION_MS)
        finally:
            await bulb.disconnect()

    async def set_brightness_all(self, ips, value):
        await asyncio.gather(*[self.set_brightness(ip, value) for ip in ips], return_exceptions=True)

    async def set_daylight_all(self, ips):
        await asyncio.gather(*[self.set_daylight(ip) for ip in ips], return_exceptions=True)

    async def turn_off_all(self, ips):
        await asyncio.gather(*[self.turn_off(ip) for ip in ips], return_exceptions=True)

    async def set_color_all(self, ip_color_list):
        """ip_color_list = [(ip, h, s, v), ...]"""
        await asyncio.gather(
            *[self.set_color(ip, h, s, v) for ip, h, s, v in ip_color_list],
            return_exceptions=True
        )

    async def apply_profile_mixed(self, apply_states, off_ips):
        """Profil uygulama: apply_states = [(ip, state)], off_ips = profilde olmayan ampuller"""
        tasks = [self.apply_state(ip, s) for ip, s in apply_states]
        tasks += [self.turn_off(ip) for ip in off_ips]
        await asyncio.gather(*tasks, return_exceptions=True)


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


# ============ ÖZEL WIDGETLAR ============
class ColorDotsBar(QWidget):
    """6 küçük renkli daire içeren kompakt renk seçim çubuğu."""
    color_clicked = pyqtSignal(int, int, int)  # h, s, v

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(34)
        self.setMaximumHeight(34)
        self.setMouseTracking(True)
        self.hover_index = -1
        self.colors = QUICK_COLORS
        self.setStyleSheet("background-color: #2b2b2b; border-radius: 6px;")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Arka plan
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#2b2b2b")))
        painter.drawRoundedRect(self.rect(), 6, 6)

        # Daireler
        n = len(self.colors)
        w = self.width()
        h = self.height()
        spacing = w / (n + 1)
        base_radius = 9

        for i, (name, hex_color, _, _, _) in enumerate(self.colors):
            x = int(spacing * (i + 1))
            y = h // 2
            radius = base_radius + (2 if i == self.hover_index else 0)

            # Hover gölgesi
            if i == self.hover_index:
                painter.setBrush(QBrush(QColor(255, 255, 255, 60)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(x - radius - 2, y - radius - 2, (radius + 2) * 2, (radius + 2) * 2)

            painter.setBrush(QBrush(QColor(hex_color)))
            painter.setPen(QPen(QColor("#444"), 1))
            painter.drawEllipse(x - radius, y - radius, radius * 2, radius * 2)

    def mouseMoveEvent(self, event):
        idx = self._index_at(event.position().x(), event.position().y())
        if idx != self.hover_index:
            self.hover_index = idx
            self.setToolTip(self.colors[idx][0] if idx >= 0 else "")
            self.update()

    def leaveEvent(self, event):
        self.hover_index = -1
        self.update()

    def mousePressEvent(self, event):
        idx = self._index_at(event.position().x(), event.position().y())
        if idx >= 0:
            _, _, h, s, v = self.colors[idx]
            self.color_clicked.emit(h, s, v)

    def _index_at(self, mx, my):
        n = len(self.colors)
        w = self.width()
        spacing = w / (n + 1)
        base_radius = 11  # Hit area biraz büyük

        for i in range(n):
            x = spacing * (i + 1)
            y = self.height() / 2
            if (mx - x) ** 2 + (my - y) ** 2 <= base_radius ** 2:
                return i
        return -1


class BulbPanel(QGroupBox):
    state_changed = pyqtSignal()

    def __init__(self, name, ip, kasa, parent_window):
        super().__init__(name)
        self.ip = ip
        self.name = name
        self.kasa = kasa
        self.parent_window = parent_window
        self.workers = []
        self.setMinimumWidth(PANEL_MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.last_state = {
            "mode": "color",
            "h": 0, "s": 0, "v": 100,
            "brightness": 75
        }

        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(8, 12, 8, 8)

        ip_label = QLabel(f"IP: {ip}")
        ip_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(ip_label)

        self.brightness_label = QLabel("Parlaklık: 75")
        layout.addWidget(self.brightness_label)

        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(1, 100)
        self.brightness_slider.setValue(75)
        self.brightness_slider.valueChanged.connect(self.on_brightness_changed)
        self.brightness_slider.sliderReleased.connect(self.apply_brightness)
        layout.addWidget(self.brightness_slider)

        # Renk çubuğu (kompakt daireler)
        self.color_bar = ColorDotsBar()
        self.color_bar.color_clicked.connect(self.apply_quick_color)
        layout.addWidget(self.color_bar)

        self.color_btn = QPushButton("🎨 Renk Seç")
        self.color_btn.clicked.connect(self.pick_color)
        self.color_btn.setMinimumHeight(32)
        layout.addWidget(self.color_btn)

        self.daylight_btn = QPushButton("☀️ Gün Işığı")
        self.daylight_btn.clicked.connect(self.set_daylight)
        self.daylight_btn.setMinimumHeight(32)
        layout.addWidget(self.daylight_btn)

        self.off_btn = QPushButton("💤 Kapat")
        self.off_btn.clicked.connect(self.turn_off)
        self.off_btn.setMinimumHeight(32)
        layout.addWidget(self.off_btn)

        layout.addStretch()
        self.setLayout(layout)

    def on_brightness_changed(self, value):
        self.brightness_label.setText(f"Parlaklık: {value}")

    def update_slider_silently(self, value):
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
    right_clicked = pyqtSignal()

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda _: self.right_clicked.emit())


class FlowGrid(QWidget):
    """Akışkan grid: genişliğe göre sütun sayısı otomatik ayarlanır."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self._layout = QGridLayout(self)
        self._layout.setSpacing(8)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._current_cols = 0

    def add_widget(self, w):
        self.items.append(w)
        self._relayout()

    def clear(self):
        for w in self.items:
            self._layout.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        self.items = []

    def resizeEvent(self, event):
        self._relayout()
        super().resizeEvent(event)

    def _relayout(self):
        if not self.items:
            return
        w = max(self.width(), 1)
        cols = max(1, w // (PANEL_MIN_WIDTH + 12))
        cols = min(cols, len(self.items))
        if cols == self._current_cols:
            return
        self._current_cols = cols
        # Önce hepsini layout'tan çıkar
        for item in self.items:
            self._layout.removeWidget(item)
        # Yeniden ekle
        for i, item in enumerate(self.items):
            self._layout.addWidget(item, i // cols, i % cols)


# ============ ANA PENCERE ============
class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.kasa = KasaCommands(config)
        self.global_workers = []
        self.active_profile_idx = None
        self.profile_dirty = False

        self.setWindowTitle("Tapo Bulb Controller 1453")
        self.setMinimumSize(360, 500)
        self.resize(780, 720)

        central = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Ampul panelleri için scroll alanı + akışkan grid
        self.bulbs_scroll = QScrollArea()
        self.bulbs_scroll.setWidgetResizable(True)
        self.bulbs_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.bulbs_grid = FlowGrid()
        self.bulbs_scroll.setWidget(self.bulbs_grid)
        main_layout.addWidget(self.bulbs_scroll, stretch=3)

        # Ampul panellerini oluştur
        self.panels = []
        self._build_bulb_panels()

        # Global kontroller
        global_group = QGroupBox("🌐 Global Kontroller")
        global_layout = QVBoxLayout()
        global_layout.setSpacing(6)

        self.global_brightness_label = QLabel("Tüm Parlaklık: 75")
        global_layout.addWidget(self.global_brightness_label)

        self.global_brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.global_brightness_slider.setRange(1, 100)
        self.global_brightness_slider.setValue(75)
        self.global_brightness_slider.valueChanged.connect(self.on_global_brightness_changed)
        self.global_brightness_slider.sliderReleased.connect(self.apply_global_brightness)
        global_layout.addWidget(self.global_brightness_slider)

        global_buttons1 = QHBoxLayout()
        self.global_daylight_btn = QPushButton("☀️ Gün Işığı")
        self.global_daylight_btn.setMinimumHeight(34)
        self.global_daylight_btn.clicked.connect(self.global_daylight)
        global_buttons1.addWidget(self.global_daylight_btn)

        self.random_color_btn = QPushButton("🎲 Random Renk")
        self.random_color_btn.setMinimumHeight(34)
        self.random_color_btn.clicked.connect(self.random_color_all)
        global_buttons1.addWidget(self.random_color_btn)
        global_layout.addLayout(global_buttons1)

        self.off_all_btn = QPushButton("💤 HEPSİNİ KAPAT")
        self.off_all_btn.setMinimumHeight(36)
        self.off_all_btn.setStyleSheet(
            "font-weight: bold; background-color: #444; color: white; border-radius: 4px;"
        )
        self.off_all_btn.clicked.connect(self.turn_off_all)
        global_layout.addWidget(self.off_all_btn)

        global_group.setLayout(global_layout)
        main_layout.addWidget(global_group)

        # Profil butonları
        profile_group = QGroupBox("📌 Profiller (sağ tık ile düzenle)")
        profile_layout = QGridLayout()
        profile_layout.setSpacing(6)
        self.profile_buttons = []
        for i in range(NUM_PROFILES):
            pname = self.config["profiles"][i]["name"]
            btn = ProfileButton(pname)
            btn.setMinimumHeight(34)
            btn.clicked.connect(lambda _, idx=i: self.apply_profile(idx))
            btn.right_clicked.connect(lambda idx=i: self.show_profile_menu(idx))
            self.profile_buttons.append(btn)
            profile_layout.addWidget(btn, i // 3, i % 3)
        profile_group.setLayout(profile_layout)
        main_layout.addWidget(profile_group)
        self.refresh_profile_buttons()

        self.update_profile_btn = QPushButton("💾 Profili Güncelle")
        self.update_profile_btn.setMinimumHeight(32)
        self.update_profile_btn.clicked.connect(self.update_active_profile)
        self.update_profile_btn.setEnabled(False)
        main_layout.addWidget(self.update_profile_btn)

        # Alt: Durum + Ayarlar
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

    def _build_bulb_panels(self):
        """Config'teki ampullerden BulbPanel'ları oluşturur."""
        self.bulbs_grid.clear()
        self.panels = []
        for cfg in self.config["bulbs"]:
            panel = BulbPanel(cfg["name"], cfg["ip"], self.kasa, self)
            panel.state_changed.connect(self.on_bulb_state_changed)
            self.panels.append(panel)
            self.bulbs_grid.add_widget(panel)

    @property
    def ips(self):
        return [b["ip"] for b in self.config["bulbs"]]

    def set_status(self, text):
        self.status_label.setText(text)

    def on_bulb_state_changed(self):
        if self.active_profile_idx is not None:
            self.profile_dirty = True
            self.update_profile_btn.setEnabled(True)

    def on_global_brightness_changed(self, value):
        self.global_brightness_label.setText(f"Tüm Parlaklık: {value}")
        for panel in self.panels:
            panel.update_slider_silently(value)

    def apply_global_brightness(self):
        value = self.global_brightness_slider.value()
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

    def random_color_all(self):
        """Her ampule farklı random renk, parlaklığa dokunmadan."""
        ip_color_list = []
        for panel in self.panels:
            h = random.randint(0, 359)
            s = random.randint(70, 100)  # Çok soluk olmasın
            v = panel.last_state.get("brightness", 75)
            panel.last_state = {"mode": "color", "h": h, "s": s, "v": v, "brightness": v}
            # Slider'a dokunmuyoruz, parlaklık aynı
            ip_color_list.append((panel.ip, h, s, v))
        self.on_bulb_state_changed()
        self.run_global_async(self.kasa.set_color_all, ip_color_list)

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
            self.set_status("✓ Komut tamamlandı")
        else:
            self.set_status("✗ Hata")
            QMessageBox.warning(self, "Hata", error_msg)

    # ---- Profil yönetimi ----
    def refresh_profile_buttons(self):
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
            reply = QMessageBox.question(
                self, "Boş Profil",
                f"'{profile['name']}' boş. Mevcut ampul ayarlarını bu profile kaydetmek ister misiniz?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.save_current_to_profile(idx)
            return

        self.active_profile_idx = idx
        self.profile_dirty = False
        self.update_profile_btn.setEnabled(False)

        # Profil verisi ip eşleştirmeli olabilir veya index'li.
        # Yeni format: her state'in içinde "ip" varsa onunla eşleştir; yoksa index'le.
        profile_data = profile["data"]
        apply_states = []
        covered_ips = set()

        # Yeni format kontrolü: data içinde dict varsa ve "ip" anahtarı varsa
        if profile_data and isinstance(profile_data[0], dict) and "ip" in profile_data[0]:
            data_by_ip = {item["ip"]: item["state"] for item in profile_data}
            for panel in self.panels:
                if panel.ip in data_by_ip:
                    state = data_by_ip[panel.ip]
                    panel.set_state_external(state)
                    apply_states.append((panel.ip, state))
                    covered_ips.add(panel.ip)
        else:
            # Eski format: sadece state listesi, index'le eşleştir
            for i, panel in enumerate(self.panels):
                if i < len(profile_data):
                    state = profile_data[i]
                    panel.set_state_external(state)
                    apply_states.append((panel.ip, state))
                    covered_ips.add(panel.ip)

        off_ips = [panel.ip for panel in self.panels if panel.ip not in covered_ips]

        self.refresh_profile_buttons()
        self.set_status(f"Profil '{profile['name']}' uygulanıyor...")

        worker = AsyncWorker(self.kasa.apply_profile_mixed, apply_states, off_ips)
        worker.finished_signal.connect(self.on_global_finished)
        worker.finished.connect(
            lambda: self.global_workers.remove(worker) if worker in self.global_workers else None
        )
        self.global_workers.append(worker)
        worker.start()

    def save_current_to_profile(self, idx):
        # Yeni format: ip + state çiftleri
        data = [
            {"ip": panel.ip, "state": dict(panel.last_state)}
            for panel in self.panels
        ]
        self.config["profiles"][idx]["data"] = data
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
            self, "Profili Yeniden Adlandır", "Yeni isim:", text=current_name
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
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_config = dialog.get_config()
            self.config["email"] = new_config["email"]
            self.config["password"] = new_config["password"]
            self.config["bulbs"] = new_config["bulbs"]
            self.kasa = KasaCommands(self.config)
            save_config(self.config)
            self._build_bulb_panels()
            self.set_status("Ayarlar güncellendi.")


# ============ AYARLAR PENCERESİ ============
class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ayarlar")
        self.setMinimumSize(560, 540)
        self.config = json.loads(json.dumps(config))  # Deep copy

        layout = QVBoxLayout()

        # Email/şifre
        cred_group = QGroupBox("Hesap")
        form = QFormLayout()
        self.email_input = QLineEdit(self.config.get("email", ""))
        form.addRow("E-posta:", self.email_input)
        self.password_input = QLineEdit(self.config.get("password", ""))
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Şifre:", self.password_input)
        cred_group.setLayout(form)
        layout.addWidget(cred_group)

        # Ampuller
        bulbs_group = QGroupBox("Ekli Ampuller")
        bulbs_outer = QVBoxLayout()

        self.bulbs_scroll = QScrollArea()
        self.bulbs_scroll.setWidgetResizable(True)
        self.bulbs_scroll.setMinimumHeight(160)
        self.bulbs_container = QWidget()
        self.bulbs_inner_layout = QVBoxLayout()
        self.bulbs_inner_layout.setSpacing(4)
        self.bulbs_container.setLayout(self.bulbs_inner_layout)
        self.bulbs_scroll.setWidget(self.bulbs_container)
        bulbs_outer.addWidget(self.bulbs_scroll)

        scan_btn = QPushButton("🔍 Ağı Tara ve Ampul Ekle")
        scan_btn.setMinimumHeight(36)
        scan_btn.clicked.connect(self.scan_network)
        bulbs_outer.addWidget(scan_btn)

        bulbs_group.setLayout(bulbs_outer)
        layout.addWidget(bulbs_group)

        footer = QLabel("krmrbtn 2026")
        footer.setStyleSheet("color: #aaa; font-size: 10px;")
        footer.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(footer)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)
        self._refresh_bulb_list()

    def _refresh_bulb_list(self):
        # Eski içerikleri temizle
        while self.bulbs_inner_layout.count():
            item = self.bulbs_inner_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self.config["bulbs"]:
            empty = QLabel("Henüz ekli ampul yok. Aşağıdaki butonla ağı tarayın.")
            empty.setStyleSheet("color: #888; padding: 12px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.bulbs_inner_layout.addWidget(empty)
            return

        for i, bulb in enumerate(self.config["bulbs"]):
            row = QFrame()
            row.setFrameShape(QFrame.Shape.StyledPanel)
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(8, 4, 8, 4)

            label = QLabel(
                f"<b>{bulb['name']}</b><br>"
                f"<span style='color: #777; font-size: 11px;'>IP: {bulb['ip']}</span>"
            )
            row_layout.addWidget(label, stretch=1)

            rename_btn = QPushButton("✏️")
            rename_btn.setMaximumWidth(36)
            rename_btn.setToolTip("Yeniden adlandır")
            rename_btn.clicked.connect(lambda _, idx=i: self._rename_bulb(idx))
            row_layout.addWidget(rename_btn)

            del_btn = QPushButton("❌")
            del_btn.setMaximumWidth(36)
            del_btn.setToolTip("Sil")
            del_btn.clicked.connect(lambda _, idx=i: self._delete_bulb(idx))
            row_layout.addWidget(del_btn)

            row.setLayout(row_layout)
            self.bulbs_inner_layout.addWidget(row)

        self.bulbs_inner_layout.addStretch()

    def _rename_bulb(self, idx):
        current = self.config["bulbs"][idx]["name"]
        new_name, ok = QInputDialog.getText(
            self, "Ampulü Yeniden Adlandır", "Yeni isim:", text=current
        )
        if ok and new_name.strip():
            self.config["bulbs"][idx]["name"] = new_name.strip()
            self._refresh_bulb_list()

    def _delete_bulb(self, idx):
        reply = QMessageBox.question(
            self, "Ampulü Sil",
            f"'{self.config['bulbs'][idx]['name']}' silinsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            del self.config["bulbs"][idx]
            self._refresh_bulb_list()

    def scan_network(self):
        if not self.email_input.text().strip() or not self.password_input.text():
            QMessageBox.warning(self, "Eksik", "Önce e-posta ve şifre girin.")
            return

        # Parent=None ile tarama akışını başlat — orphan dialog sorununu önler
        scan_result = {"bulbs": []}

        def collect_bulbs(bulbs):
            scan_result["bulbs"] = bulbs

        run_scan_flow(
            email=self.email_input.text().strip(),
            password=self.password_input.text(),
            existing_bulbs=self.config["bulbs"],
            parent=None,
            on_done=collect_bulbs
        )

        # Eklenen ampulleri config'e işle
        for b in scan_result["bulbs"]:
            self.config["bulbs"].append({"name": b["name"], "ip": b["ip"]})
        self._refresh_bulb_list()

    def validate_and_accept(self):
        if not self.email_input.text().strip():
            QMessageBox.warning(self, "Eksik", "E-posta girilmedi.")
            return
        if not self.password_input.text():
            QMessageBox.warning(self, "Eksik", "Şifre girilmedi.")
            return
        if not self.config["bulbs"]:
            reply = QMessageBox.question(
                self, "Ampul Yok",
                "Hiç ampul ekli değil. Devam etmek istiyor musunuz?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.accept()

    def get_config(self):
        return {
            "email": self.email_input.text().strip(),
            "password": self.password_input.text(),
            "bulbs": self.config["bulbs"]
        }


# ============ ORTAK SCAN AKIŞI ============
def run_scan_flow(email, password, existing_bulbs, parent, on_done):
    """
    Ağ tarama akışını yönetir. Tamamen senkron, blocking dialog akışı.
    Worker thread için QEventLoop kullanır.
    """
    from PyQt6.QtCore import QEventLoop

    def do_one_scan(bc):
        """Tek bir tarama denemesi, sonucu döndürür (list or None=hata)."""
        # Worker'ı bir QEventLoop ile blocking yapıyoruz
        worker = ScanWorker(email, password, bc)
        loop = QEventLoop()
        result_holder = {"devices": [], "error": ""}

        def on_finished(devices, error):
            result_holder["devices"] = devices
            result_holder["error"] = error
            loop.quit()

        worker.finished_signal.connect(on_finished)

        # Tarama mesajını göster
        progress = QMessageBox(parent)
        progress.setIcon(QMessageBox.Icon.Information)
        progress.setWindowTitle("Tarama")
        progress.setText(f"Ağ taranıyor...\nBroadcast: {bc}\n\nLütfen bekleyin (~10 sn)")
        progress.setStandardButtons(QMessageBox.StandardButton.NoButton)
        progress.show()

        worker.start()
        loop.exec()  # Worker bitince loop.quit() çağrılır
        worker.wait()  # Thread tamamen bitsin
        progress.close()

        # Bağlantıyı temizle (tekrar tetiklenmesin)
        try:
            worker.finished_signal.disconnect(on_finished)
        except (TypeError, RuntimeError):
            pass

        if result_holder["error"]:
            QMessageBox.critical(parent, "Tarama Hatası", f"Hata: {result_holder['error']}")
            return None

        return result_holder["devices"]

    # Ana akış
    current_broadcast = detect_broadcast_address()

    while True:
        devices = do_one_scan(current_broadcast)

        if devices is None:
            on_done([])
            return

        if not devices:
            trouble = NetworkTroubleDialog(current_broadcast, parent)
            if trouble.exec() == QDialog.DialogCode.Accepted and trouble.manual_broadcast:
                current_broadcast = trouble.manual_broadcast
                continue
            else:
                on_done([])
                return

        existing_ips = [b["ip"] for b in existing_bulbs]
        results = ScanResultsDialog(devices, existing_ips, parent)
        if results.exec() == QDialog.DialogCode.Accepted:
            on_done(results.selected_devices)
        else:
            on_done([])
        return

# ============ MAIN ============
def main():
    app = QApplication(sys.argv)
    # İkonu yükle - hem development hem PyInstaller exe'de çalışır
    if getattr(sys, 'frozen', False):
        # PyInstaller exe içinde çalışıyor
        icon_path = os.path.join(sys._MEIPASS, "icon.ico")
    else:
        # IDE'den / Python'dan çalışıyor
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")

    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    config = load_config()

    # İlk açılış
    if not config or not config.get("email"):
        # 1. Email/şifre al
        cred_dialog = CredentialsDialog()
        if cred_dialog.exec() != QDialog.DialogCode.Accepted:
            sys.exit(0)

        email, password = cred_dialog.get_values()

        # 2. Ağı tara - parent yok, tüm dialog'lar bağımsız
        scan_result = {"bulbs": []}

        def collect_bulbs(bulbs):
            scan_result["bulbs"] = bulbs

        run_scan_flow(email, password, [], None, collect_bulbs)

        # 3. Config'i hazırla ve kaydet
        config = default_config()
        config["email"] = email
        config["password"] = password
        for b in scan_result["bulbs"]:
            config["bulbs"].append({"name": b["name"], "ip": b["ip"]})
        save_config(config)

        if not config["bulbs"]:
            reply = QMessageBox.question(
                None, "Ampul Eklenmedi",
                "Hiç ampul eklemediniz. Programı yine de açmak ister misiniz?\n"
                "(Sonradan Ayarlardan ekleyebilirsiniz)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                sys.exit(0)

    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()