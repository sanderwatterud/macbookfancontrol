#!/usr/bin/env python3
"""macbookfancontrol — System tray indicator for MacBook fan control on Linux."""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')

import os
import signal
import subprocess
import sys
import time

from gi.repository import Gtk, GLib, Gdk
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


class FanControlWindow(Gtk.Window):
    """Persistent control window that stays open."""

    def __init__(self, fan_indicator):
        super().__init__(title="MacBook Fan Control")
        self.fan = fan_indicator
        self.set_default_size(260, -1)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_position(Gtk.WindowPosition.NONE)

        # Close to tray instead of quitting
        self.connect("delete-event", self._on_close)

        # Build UI
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(12)
        self.add(box)

        # ── Info ──
        self.lbl_fan = Gtk.Label(label="Fan: -- RPM")
        self.lbl_fan.set_xalign(0)
        box.pack_start(self.lbl_fan, False, False, 0)

        self.lbl_cpu = Gtk.Label(label="CPU: --C")
        self.lbl_cpu.set_xalign(0)
        box.pack_start(self.lbl_cpu, False, False, 0)

        self.lbl_mode = Gtk.Label(label="Mode: AUTO")
        self.lbl_mode.set_xalign(0)
        box.pack_start(self.lbl_mode, False, False, 0)

        box.pack_start(Gtk.Separator(), False, False, 4)

        # ── Mode buttons ──
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.btn_auto = Gtk.Button(label="Auto")
        self.btn_auto.connect("clicked", self._on_auto)
        btn_box.pack_start(self.btn_auto, True, True, 0)

        self.btn_manual = Gtk.Button(label="Manual")
        self.btn_manual.connect("clicked", self._on_manual)
        btn_box.pack_start(self.btn_manual, True, True, 0)

        box.pack_start(btn_box, False, False, 0)

        box.pack_start(Gtk.Separator(), False, False, 4)

        # ── RPM slider ──
        self.lbl_target = Gtk.Label(label="Target: -- RPM")
        self.lbl_target.set_xalign(0)
        box.pack_start(self.lbl_target, False, False, 0)

        self.rpm_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 1299, 6199, 100
        )
        self.rpm_scale.set_draw_value(False)
        self.rpm_scale.connect("value-changed", self._on_scale_changed)
        self.rpm_scale.set_sensitive(False)
        box.pack_start(self.rpm_scale, False, False, 0)

        # ── Quick presets ──
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for label, rpm in [("Min", 1299), ("2k", 2000), ("3k", 3000),
                           ("4k", 4000), ("5k", 5000), ("Max", 6199)]:
            btn = Gtk.Button(label=label)
            btn.connect("clicked", lambda w, r=rpm: self._on_preset(r))
            preset_box.pack_start(btn, True, True, 0)
        box.pack_start(preset_box, False, False, 0)

        self.show_all()

    def _on_close(self, _widget, _event):
        """Hide to tray instead of quitting."""
        self.hide()
        return True  # prevent default destruction

    def _on_auto(self, _):
        self.fan.set_auto()

    def _on_manual(self, _):
        self.fan.set_manual()

    def _on_scale_changed(self, scale):
        rpm = int(scale.get_value())
        self.fan.set_rpm(rpm)

    def _on_preset(self, rpm):
        self.fan.set_rpm(rpm)
        self.rpm_scale.set_value(rpm)

    def update(self, current_rpm, cpu_temp, manual_mode, target_rpm, mbpfan_on, min_rpm, max_rpm):
        rpm_str = f"{current_rpm}" if current_rpm is not None else "--"
        self.lbl_fan.set_text(f"Fan: {rpm_str} RPM")

        if cpu_temp is not None:
            self.lbl_cpu.set_text(f"CPU: {cpu_temp:.0f}C")
        else:
            self.lbl_cpu.set_text("CPU: --C")

        mode = "MANUAL" if manual_mode else "AUTO"
        mbpfan_str = " (mbpfan)" if mbpfan_on else ""
        self.lbl_mode.set_text(f"Mode: {mode}{mbpfan_str}")

        # Update slider
        self.rpm_scale.set_range(min_rpm, max_rpm)
        self.rpm_scale.set_sensitive(manual_mode)
        if manual_mode:
            # Block signal to avoid feedback loop
            self.rpm_scale.handler_block_by_func(self._on_scale_changed)
            self.rpm_scale.set_value(target_rpm)
            self.rpm_scale.handler_unblock_by_func(self._on_scale_changed)
            self.lbl_target.set_text(f"Target: {target_rpm} RPM")
        else:
            self.lbl_target.set_text("Target: --")

        # Highlight active mode button
        if manual_mode:
            self.btn_manual.get_style_context().add_class("suggested-action")
            self.btn_auto.get_style_context().remove_class("suggested-action")
        else:
            self.btn_auto.get_style_context().add_class("suggested-action")
            self.btn_manual.get_style_context().remove_class("suggested-action")


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
            "macbookfancontrol",
            "fan",
            AppIndicator.IndicatorCategory.HARDWARE
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("MacBook Fan Control")

        # Build tray menu (minimal — just show/hide window and quit)
        self.menu = Gtk.Menu()
        self._build_menu()
        self.indicator.set_menu(self.menu)

        # Create control window
        self.window = FanControlWindow(self)

        # Start update loop
        GLib.timeout_add(2000, self._update)

    def _build_menu(self):
        item_show = Gtk.MenuItem(label="Show Controls")
        item_show.connect("activate", lambda _: self.window.show())
        self.menu.append(item_show)

        item_tui = Gtk.MenuItem(label="Open TUI")
        item_tui.connect("activate", self._on_open_tui)
        self.menu.append(item_tui)

        self.menu.append(Gtk.SeparatorMenuItem())

        item_quit = Gtk.MenuItem(label="Quit")
        item_quit.connect("activate", self._on_quit)
        self.menu.append(item_quit)

        self.menu.show_all()

    # ── Public methods for FanControlWindow ──

    def set_auto(self):
        if self.manual_mode:
            write_int(FAN_MANUAL, 0)
            self.manual_mode = False
            if self.we_stopped_mbpfan:
                toggle_mbpfan(True)
                self.we_stopped_mbpfan = False

    def set_manual(self):
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

    def set_rpm(self, rpm):
        rpm = max(self.min_rpm, min(self.max_rpm, rpm))
        if not self.manual_mode:
            self.set_manual()
        ok = write_int(FAN_OUTPUT, rpm)
        if ok:
            self.target_rpm = rpm

    # ── Menu callbacks ──

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

    # ── Update loop ──

    def _update(self):
        current_rpm = read_int(FAN_INPUT)
        temps = read_temps()
        mbpfan_on = is_mbpfan_active()

        cpu_temp = None
        for label, temp in temps:
            if label == "x86_pkg_temp":
                cpu_temp = temp
                break

        rpm_str = f"{current_rpm}" if current_rpm is not None else "--"
        self.indicator.set_label(f"{rpm_str}", "")

        # Update control window
        self.window.update(
            current_rpm, cpu_temp, self.manual_mode,
            self.target_rpm, mbpfan_on, self.min_rpm, self.max_rpm
        )

        return True


def main():
    if not os.path.exists(APPLESMC):
        print("Error: applesmc not found — is this a Mac?", file=sys.stderr)
        sys.exit(1)

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    indicator = FanIndicator()
    # Show window on startup
    indicator.window.show()
    Gtk.main()


if __name__ == "__main__":
    main()
