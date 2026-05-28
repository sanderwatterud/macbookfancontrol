#!/usr/bin/env python3
"""macbookfancontrol — Terminal UI for MacBook fan control on Linux."""

import curses
import os
import signal
import subprocess
import sys
import time

# ── sysfs paths ──────────────────────────────────────────────
APPLESMC = "/sys/devices/platform/applesmc.768"
FAN_INPUT = f"{APPLESMC}/fan1_input"      # current RPM (read-only)
FAN_MANUAL = f"{APPLESMC}/fan1_manual"     # 1=manual, 0=auto
FAN_MIN = f"{APPLESMC}/fan1_min"
FAN_MAX = f"{APPLESMC}/fan1_max"
FAN_OUTPUT = f"{APPLESMC}/fan1_output"     # write target RPM here

THERMAL_ZONES = "/sys/class/thermal"

MBPFAN_CONF = "/etc/mbpfan.conf"
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
    except (PermissionError, OSError) as e:
        return False


def read_temps():
    """Return list of (label, temp_celsius) tuples."""
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


def read_mbpfan_conf():
    """Parse mbpfan.conf for display."""
    try:
        with open(MBPFAN_CONF) as f:
            lines = f.readlines()
        conf = {}
        for line in lines:
            line = line.split("#")[0].strip()
            if "=" in line:
                k, v = line.split("=", 1)
                conf[k.strip()] = v.strip()
        return conf
    except FileNotFoundError:
        return {}


def rpm_bar(rpm, min_rpm, max_rpm, width=30):
    """Return a visual bar for RPM level."""
    if max_rpm <= min_rpm or rpm is None:
        return "[" + " " * width + "]"
    pct = max(0.0, min(1.0, (rpm - min_rpm) / (max_rpm - min_rpm)))
    filled = int(pct * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def temp_color(temp):
    """Return curses color pair index for temperature."""
    if temp < 50:
        return 1  # green
    elif temp < 70:
        return 2  # yellow
    else:
        return 3  # red


def safe_addstr(stdscr, y, x, text, attr=0):
    """addstr that won't crash if text exceeds window bounds."""
    try:
        h, w = stdscr.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        max_len = w - x
        if max_len <= 0:
            return
        text = text[:max_len]
        if y == h - 1 and x + len(text) >= w:
            text = text[:w - x - 1]
        stdscr.addstr(y, x, text, attr)
    except curses.error:
        pass


class FanTUI:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.running = True
        self.manual_mode = False
        self.target_rpm = 0
        self.min_rpm = read_int(FAN_MIN) or 1299
        self.max_rpm = read_int(FAN_MAX) or 6199
        self.status_msg = ""
        self.status_time = 0

        # Track whether WE stopped mbpfan (so we only restart if we did)
        self.we_stopped_mbpfan = False

        # Detect current state
        current_manual = read_int(FAN_MANUAL)
        mbpfan_was_active = is_mbpfan_active()

        if current_manual == 1:
            # Fan is already in manual mode — adopt it
            self.manual_mode = True
            current_output = read_int(FAN_OUTPUT)
            self.target_rpm = current_output if current_output else (read_int(FAN_INPUT) or self.min_rpm)
        else:
            self.manual_mode = False
            self.target_rpm = self.min_rpm

        # Setup curses
        curses.curs_set(0)
        curses.noecho()
        self.stdscr.nodelay(True)
        self.stdscr.timeout(500)  # refresh every 500ms
        # Enable mouse tracking so scroll events become KEY_MOUSE
        # instead of being misinterpreted as KEY_UP/KEY_DOWN
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)

        # Colors
        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(3, curses.COLOR_RED, curses.COLOR_BLACK)
        curses.init_pair(4, curses.COLOR_CYAN, curses.COLOR_BLACK)
        curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLUE)

    def set_status(self, msg):
        self.status_msg = msg
        self.status_time = time.time()

    def set_manual(self, manual):
        if manual == self.manual_mode:
            return
        if manual:
            # Only stop mbpfan if it's actually running
            if is_mbpfan_active():
                toggle_mbpfan(False)
                self.we_stopped_mbpfan = True
            else:
                self.we_stopped_mbpfan = False

            ok = write_int(FAN_MANUAL, 1)
            if ok:
                self.manual_mode = True
                # Read current RPM as starting point
                current = read_int(FAN_INPUT) or self.min_rpm
                self.target_rpm = current
                # Re-apply current speed to make sure output matches
                write_int(FAN_OUTPUT, self.target_rpm)
                self.set_status("Manual mode — use Up/Dn to adjust RPM")
            else:
                self.set_status("Need sudo for manual mode")
        else:
            # Switch to auto: set manual=0 first, then maybe restart mbpfan
            write_int(FAN_MANUAL, 0)
            self.manual_mode = False
            if self.we_stopped_mbpfan:
                toggle_mbpfan(True)
                self.we_stopped_mbpfan = False
                self.set_status("Auto mode — mbpfan controls fan")
            else:
                self.set_status("Auto mode — SMC controls fan")

    def set_rpm(self, rpm):
        rpm = max(self.min_rpm, min(self.max_rpm, rpm))
        if not self.manual_mode:
            self.set_manual(True)
        ok = write_int(FAN_OUTPUT, rpm)
        if ok:
            self.target_rpm = rpm
        else:
            self.set_status("Need sudo to set fan speed")

    def cleanup(self):
        """Restore sane state on exit."""
        if self.manual_mode:
            write_int(FAN_MANUAL, 0)
        if self.we_stopped_mbpfan:
            toggle_mbpfan(True)
            self.we_stopped_mbpfan = False

    def handle_input(self):
        try:
            key = self.stdscr.getch()
        except curses.error:
            return

        if key == ord("q") or key == ord("Q"):
            self.running = False
        elif key == curses.KEY_MOUSE:
            pass  # Ignore mouse events
        elif key == ord("a") or key == ord("A"):
            self.set_manual(False)
        elif key == ord("m") or key == ord("M"):
            self.set_manual(True)
        elif key == curses.KEY_UP or key == ord("+"):
            step = 200 if (self.target_rpm >= 2000) else 100
            self.set_rpm(self.target_rpm + step)
        elif key == curses.KEY_DOWN or key == ord("-"):
            step = 200 if (self.target_rpm >= 2200) else 100
            self.set_rpm(self.target_rpm - step)
        elif key == ord("0"):
            self.set_rpm(self.min_rpm)
        elif key == ord("1"):
            self.set_rpm(2000)
        elif key == ord("2"):
            self.set_rpm(3000)
        elif key == ord("3"):
            self.set_rpm(4000)
        elif key == ord("4"):
            self.set_rpm(5000)
        elif key == ord("5"):
            self.set_rpm(self.max_rpm)

    def draw(self):
        h, w = self.stdscr.getmaxyx()
        self.stdscr.erase()

        # Read current values
        current_rpm = read_int(FAN_INPUT)
        temps = read_temps()
        mbpfan_on = is_mbpfan_active()
        conf = read_mbpfan_conf()

        # ── Header ──
        header = " macbookfancontrol — MacBook Fan Control "
        safe_addstr(self.stdscr, 0, 0, header.center(w), curses.color_pair(5) | curses.A_BOLD)

        y = 2

        # ── Mode ──
        mode_str = "MANUAL" if self.manual_mode else "AUTO"
        mode_attr = curses.color_pair(3) | curses.A_BOLD if self.manual_mode else curses.color_pair(1)
        safe_addstr(self.stdscr, y, 2, "Mode:", curses.A_BOLD)
        safe_addstr(self.stdscr, y, 9, f" {mode_str} ", mode_attr)
        if mbpfan_on:
            safe_addstr(self.stdscr, y, 20, "(mbpfan active)", curses.color_pair(4))
        y += 2

        # ── Fan speed ──
        rpm_str = f"{current_rpm}" if current_rpm is not None else "--"
        safe_addstr(self.stdscr, y, 2, "Fan:", curses.A_BOLD)
        safe_addstr(self.stdscr, y, 9, f"{rpm_str} RPM", curses.color_pair(1) | curses.A_BOLD)
        y += 1
        bar = rpm_bar(current_rpm, self.min_rpm, self.max_rpm, width=min(40, w - 4))
        safe_addstr(self.stdscr, y, 2, bar)
        pct = 0
        if current_rpm and self.max_rpm > self.min_rpm:
            pct = int(100 * (current_rpm - self.min_rpm) / (self.max_rpm - self.min_rpm))
        safe_addstr(self.stdscr, y, 2 + len(bar) + 1, f"{pct}%")
        y += 1
        safe_addstr(self.stdscr, y, 2, f"Min: {self.min_rpm}  Max: {self.max_rpm}", curses.A_DIM)
        if self.manual_mode:
            safe_addstr(self.stdscr, y, 30, f"  Target: {self.target_rpm} RPM", curses.color_pair(2))
        y += 2

        # ── Temperatures ──
        safe_addstr(self.stdscr, y, 2, "Temperatures:", curses.A_BOLD)
        y += 1
        for label, temp in temps:
            cp = temp_color(temp)
            name = label.replace("x86_pkg_temp", "CPU").replace("pch_wildcat_point", "PCH").replace("BAT0", "Battery")
            safe_addstr(self.stdscr, y, 4, f"{name:12s}", curses.A_DIM)
            safe_addstr(self.stdscr, y, 17, f"{temp:5.1f}C", curses.color_pair(cp) | curses.A_BOLD)
            bar_w = min(20, w - 40)
            if bar_w > 5:
                filled = int(min(1.0, temp / 105.0) * bar_w)
                bar = "#" * filled + "-" * (bar_w - filled)
                safe_addstr(self.stdscr, y, 25, bar, curses.color_pair(cp))
            y += 1
        y += 1

        # ── mbpfan config ──
        if conf:
            safe_addstr(self.stdscr, y, 2, "mbpfan.conf:", curses.A_BOLD)
            y += 1
            for key in ("low_temp", "high_temp", "max_temp"):
                if key in conf:
                    label = {"low_temp": "Low", "high_temp": "High", "max_temp": "Max"}[key]
                    safe_addstr(self.stdscr, y, 4, f"{label}: {conf[key]}C", curses.A_DIM)
                    y += 1
            y += 1

        # ── Controls ──
        safe_addstr(self.stdscr, y, 2, "Controls:", curses.A_BOLD)
        y += 1
        controls = [
            ("Up/Dn ", "Adjust RPM (+200)"),
            ("+/-   ", "Adjust RPM"),
            ("0-5   ", "Quick set (min/2k/3k/4k/5k/max)"),
            ("A     ", "Auto mode (mbpfan/SMC)"),
            ("M     ", "Manual mode"),
            ("Q     ", "Quit"),
        ]
        for key, desc in controls:
            safe_addstr(self.stdscr, y, 4, key, curses.color_pair(4) | curses.A_BOLD)
            safe_addstr(self.stdscr, y, 11, desc)
            y += 1

        # ── Status message ──
        if self.status_msg and time.time() - self.status_time < 5:
            safe_addstr(self.stdscr, h - 2, 2, self.status_msg, curses.color_pair(2))

        # ── Footer ──
        safe_addstr(self.stdscr, h - 1, 0, f" Refreshing every 0.5s · Ctrl+C to quit ".center(w), curses.A_DIM)

        self.stdscr.noutrefresh()
        curses.doupdate()

    def run(self):
        try:
            while self.running:
                self.handle_input()
                self.draw()
        finally:
            # Always cleanup, even on KeyboardInterrupt or crash
            self.cleanup()


def main():
    if not os.path.exists(APPLESMC):
        print("Error: applesmc not found — is this a Mac?", file=sys.stderr)
        print("Check kernel module: lsmod | grep applesmc", file=sys.stderr)
        sys.exit(1)

    rpm = read_int(FAN_INPUT)
    if rpm is None:
        print("Error: Cannot read fan speed.", file=sys.stderr)
        print("Try: sudo modprobe applesmc", file=sys.stderr)
        sys.exit(1)

    try:
        curses.wrapper(lambda stdscr: FanTUI(stdscr).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
