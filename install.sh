#!/bin/bash
# macbookfancontrol installer
# Usage: ./install.sh [--uninstall]

set -e

INSTALL_DIR="$HOME/.local/bin"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

uninstall=false
if [ "$1" = "--uninstall" ]; then
    uninstall=true
fi

if $uninstall; then
    echo "Uninstalling macbookfancontrol..."
    rm -f "$INSTALL_DIR/fan"
    rm -f "$INSTALL_DIR/fan-menubar.py"
    rm -f "$INSTALL_DIR/mbpfan-tui.py"
    echo "Removed from $INSTALL_DIR"
    echo "Note: system packages (mbpfan, dbus-x11, gir1.2-ayatanaappindicator3-0.1) were not removed."
    exit 0
fi

echo "Installing macbookfancontrol..."

# ── Check Apple hardware ──
if [ ! -d /sys/devices/platform/applesmc.768 ]; then
    echo "Warning: applesmc not found. This tool is designed for Apple hardware running Linux."
    echo "Make sure the applesmc kernel module is loaded: lsmod | grep applesmc"
    read -p "Continue anyway? [y/N] " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        exit 1
    fi
fi

# ── Install system dependencies ──
echo "Installing system dependencies..."
sudo apt update
sudo apt install -y mbpfan python3 dbus-x11 gir1.2-ayatanaappindicator3-0.1

# ── Enable mbpfan at boot ──
sudo systemctl enable --now mbpfan

# ── Install scripts ──
mkdir -p "$INSTALL_DIR"

# Copy Python scripts
cp "$SCRIPT_DIR/mbpfan-tui.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/fan-menubar.py" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/mbpfan-tui.py" "$INSTALL_DIR/fan-menubar.py"

# Create fan wrapper
cat > "$INSTALL_DIR/fan" << 'WRAPPER'
#!/bin/bash
if [ "$1" = "menubar" ]; then
    sudo -v || exit 1
    sudo -b python3 ~/.local/bin/fan-menubar.py
    echo "Fan menubar indicator started"
elif [ "$1" = "tui" ] || [ -z "$1" ]; then
    sudo python3 ~/.local/bin/mbpfan-tui.py
else
    echo "Usage: fan [tui|menubar]"
    echo "  fan          Open TUI (default)"
    echo "  fan tui      Open TUI"
    echo "  fan menubar  Start system tray indicator"
fi
WRAPPER
chmod +x "$INSTALL_DIR/fan"

echo ""
echo "Done! Usage:"
echo "  fan          Open TUI fan control"
echo "  fan menubar  Start system tray indicator"
echo ""
echo "To uninstall: ./install.sh --uninstall"
