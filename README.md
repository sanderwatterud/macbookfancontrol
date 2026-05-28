# macbookfancontrol

Terminal UI and system tray indicator for controlling MacBook fan speeds on Linux.

Built for Apple hardware (MacBook/MacBook Pro) running Ubuntu or similar distros. Uses the `applesmc` and `coretemp` kernel modules to read temperatures and set fan speed via sysfs.

## Features

- **TUI mode** — Full terminal interface with live RPM, temperatures, and manual/auto control
- **Menubar mode** — System tray indicator with a persistent control window (slider + presets)
- Auto-detects current fan mode on startup
- Restores auto mode and mbpfan on exit
- Quick RPM presets (Min / 2k / 3k / 4k / 5k / Max)

## Requirements

- Apple hardware with `applesmc` kernel module (MacBook, MacBook Pro, etc.)
- Linux with sysfs (`/sys/devices/platform/applesmc.768/`)
- Python 3.10+
- `sudo` access (required to write fan speed to sysfs)

### System packages (Ubuntu/Debian)

```
mbpfan python3 dbus-x11 gir1.2-ayatanaappindicator3-0.1
```

## Install

```bash
git clone https://github.com/sanderwatterud/macbookfancontrol.git
cd macbookfancontrol
./install.sh
```

The installer will:
1. Install system dependencies (`mbpfan`, `dbus-x11`, AppIndicator bindings)
2. Enable and start the `mbpfan` service
3. Copy scripts to `~/.local/bin/`
4. Create the `fan` command

## Usage

```bash
fan              # Open TUI (default)
fan tui          # Open TUI
fan menubar      # Start system tray indicator
```

### TUI controls

| Key | Action |
|-----|--------|
| Up/Dn | Adjust RPM (+200) |
| +/- | Adjust RPM |
| 0-5 | Quick set (min/2k/3k/4k/5k/max) |
| A | Auto mode (mbpfan/SMC) |
| M | Manual mode |
| Q | Quit |

### Menubar mode

- Click the tray icon to open the control window
- Use **Auto/Manual** buttons to switch mode
- Drag the slider or click presets to set RPM in manual mode
- Closing the window hides it to tray (doesn't quit)
- **Quit** from the tray menu to exit and restore auto mode

## Uninstall

```bash
./install.sh --uninstall
```

## How it works

- Reads fan speed from `/sys/devices/platform/applesmc.768/fan1_input`
- Reads temperatures from `/sys/class/thermal/thermal_zone*/temp`
- Writes target RPM to `fan1_output` and toggles `fan1_manual` (0=auto, 1=manual)
- When switching to manual mode, stops `mbpfan` and sets `fan1_manual=1`
- On exit, restores `fan1_manual=0` and restarts `mbpfan` if it was running

## License

MIT
