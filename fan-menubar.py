#!/usr/bin/env python3
"""mbpfan-menubar — System tray indicator for MacBook fan control on Linux."""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')

import os
import signal
import subprocess
import sys
import time

from gi.repository import Gtk, GLib
from gi.repository import AyatanaAppIndicator3 as AppIndicator

# ── sysfs paths ──────────────────────────────────────────────
APPLESMC = "/sys/devices/platform/applesmc.768"
FAN_INPUT = f"{APPLESMC}/fan1_input"
FAN_MANUAL = f"{APPLESMC}/fan1_manual"
FAN_MIN = f"{APPLESMC}/fan1_min"
FAN_MAX = f"{APPLESMC}/fan1_max"
FAN_OUTPUT = f"{APPLESMC}/fan1_output"

THERMAL_ZONES = "/sys/class/thermal"
MBPFAN_SERVICE = "mbpfan.service"


def read_int(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError, PermissionError, OSError):
        return None


def write_int(path, value):
    try:
        with open(path, "w") as f:
            f.write(str(value) + "\n")
        return True
    except (PermissionError, OSError):
        return False


def read_temps():
    temps = []
    for entry in sorted(os.listdir(THERMAL_ZONES)):
        if not entry.startswith("thermal_zone"):
            continue
        base = f"{THERMAL_ZONES}/{entry}"
        try:
            with open(f"{base}/type") as f:
                label = f.read().strip()
            with open(f"{base}/temp") as f:
                raw = int(f.read().strip())
            temps.append((label, raw / 1000.0))
        except (FileNotFoundError, ValueError):
            continue
    return temps


def is_mbpfan_active():
    try:
        result = subprocess.run(
            ["systemctl", "is-active", MBPFAN_SERVICE],
            capture_output=True, text=True, timeout=2
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def toggle_mbpfan(enable):
    action = "start" if enable else "stop"
    try:
        subprocess.run(
            ["systemctl", action, MBPFAN_SERVICE],
            capture_output=True, timeout=5
        )
        return True
    except Exception:
        return False


class FanIndicator:
    def __init__(self):
        self.min_rpm = read_int(FAN_MIN) or 1299
        self.max_rpm = read_int(FAN_MAX) or 6199
        self.manual_mode = False
        self.target_rpm = self.min_rpm
        self.we_stopped_mbpfan = False

        # Detect current state
        current_manual = read_int(FAN_MANUAL)
        if current_manual == 1:
            self.manual_mode = True
            current_output = read_int(FAN_OUTPUT)
            self.target_rpm = current_output if current_output else (read_int(FAN_INPUT) or self.min_rpm)

        # Create indicator
        self.indicator = AppIndicator.Indicator.new(
            "mbpfan-indicator",
            "fan",
            AppIndicator.IndicatorCategory.HARDWARE
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("MacBook Fan Control")

        # Build menu
        self.menu = Gtk.Menu()
        self._build_menu()
        self.indicator.set_menu(self.menu)

        # Start update loop
        GLib.timeout_add(2000, self._update)

    def _build_menu(self):
        # ── Info section ──
        self.item_fan = Gtk.MenuItem(label="Fan: -- RPM")
        self.item_fan.set_sensitive(False)
        self.menu.append(self.item_fan)

        self.item_cpu = Gtk.MenuItem(label="CPU: --C")
        self.item_cpu.set_sensitive(False)
        self.menu.append(self.item_cpu)

        self.item_mode = Gtk.MenuItem(label="Mode: AUTO")
        self.item_mode.set_sensitive(False)
        self.menu.append(self.item_mode)

        # Separator
        self.menu.append(Gtk.SeparatorMenuItem())

        # ── Mode toggle ──
        self.item_auto = Gtk.MenuItem(label="Switch to Auto")
        self.item_auto.connect("activate", self._on_auto)
        self.menu.append(self.item_auto)

        self.item_manual = Gtk.MenuItem(label="Switch to Manual")
        self.item_manual.connect("activate", self._on_manual)
        self.menu.append(self.item_manual)

        # Separator
        self.menu.append(Gtk.SeparatorMenuItem())

        # ── RPM presets ──
        self.rpm_presets = [
            ("Min", self.min_rpm),
            ("2000 RPM", 2000),
            ("3000 RPM", 3000),
            ("4000 RPM", 4000),
            ("5000 RPM", 5000),
            ("Max", self.max_rpm),
        ]
        self.preset_items = []
        for label, rpm in self.rpm_presets:
            item = Gtk.MenuItem(label=f"  {label}")
            item.connect("activate", lambda w, r=rpm: self._on_set_rpm(r))
            self.menu.append(item)
            self.preset_items.append((item, rpm))

        # Separator
        self.menu.append(Gtk.SeparatorMenuItem())

        # ── Open TUI ──
        item_tui = Gtk.MenuItem(label="Open TUI")
        item_tui.connect("activate", self._on_open_tui)
        self.menu.append(item_tui)

        # ── Quit ──
        item_quit = Gtk.MenuItem(label="Quit")
        item_quit.connect("activate", self._on_quit)
        self.menu.append(item_quit)

        self.menu.show_all()

    def _on_auto(self, _):
        if self.manual_mode:
            write_int(FAN_MANUAL, 0)
            self.manual_mode = False
            if self.we_stopped_mbpfan:
                toggle_mbpfan(True)
                self.we_stopped_mbpfan = False

    def _on_manual(self, _):
        if not self.manual_mode:
            if is_mbpfan_active():
                toggle_mbpfan(False)
                self.we_stopped_mbpfan = True
            else:
                self.we_stopped_mbpfan = False
            ok = write_int(FAN_MANUAL, 1)
            if ok:
                self.manual_mode = True
                self.target_rpm = read_int(FAN_INPUT) or self.min_rpm
                write_int(FAN_OUTPUT, self.target_rpm)

    def _on_set_rpm(self, rpm):
        rpm = max(self.min_rpm, min(self.max_rpm, rpm))
        if not self.manual_mode:
            self._on_manual(None)
        ok = write_int(FAN_OUTPUT, rpm)
        if ok:
            self.target_rpm = rpm

    def _on_open_tui(self, _):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        tui_path = os.path.join(script_dir, "mbpfan-tui.py")
        subprocess.Popen(["x-terminal-emulator", "-e", "sudo", "python3", tui_path],
                         start_new_session=True)

    def _on_quit(self, _):
        self._cleanup()
        Gtk.main_quit()

    def _cleanup(self):
        if self.manual_mode:
            write_int(FAN_MANUAL, 0)
        if self.we_stopped_mbpfan:
            toggle_mbpfan(True)
            self.we_stopped_mbpfan = False

    def _update(self):
        current_rpm = read_int(FAN_INPUT)
        temps = read_temps()
        mbpfan_on = is_mbpfan_active()

        # Find CPU temp
        cpu_temp = None
        for label, temp in temps:
            if label == "x86_pkg_temp":
                cpu_temp = temp
                break

        # Update info items
        rpm_str = f"{current_rpm}" if current_rpm is not None else "--"
        self.item_fan.set_label(f"Fan: {rpm_str} RPM")

        if cpu_temp is not None:
            self.item_cpu.set_label(f"CPU: {cpu_temp:.0f}C")
        else:
            self.item_cpu.set_label("CPU: --C")

        mode = "MANUAL" if self.manual_mode else "AUTO"
        mbpfan_str = " (mbpfan)" if mbpfan_on else ""
        self.item_mode.set_label(f"Mode: {mode}{mbpfan_str}")

        # Update indicator label (short text in panel)
        self.indicator.set_label(f"{rpm_str}", "")

        # Highlight active preset
        for item, rpm in self.preset_items:
            if self.manual_mode and self.target_rpm == rpm:
                item.set_label(f"> {dict(self.rpm_presets)[rpm]}")
            else:
                label = dict(self.rpm_presets)[rpm]
                item.set_label(f"  {label}")

        return True  # keep the timeout running


def main():
    if not os.path.exists(APPLESMC):
        print("Error: applesmc not found — is this a Mac?", file=sys.stderr)
        sys.exit(1)

    # Handle SIGINT gracefully
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    indicator = FanIndicator()
    Gtk.main()


if __name__ == "__main__":
    main()
