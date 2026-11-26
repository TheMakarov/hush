HUSH — A LOCAL SONY WH-1000XM4 CONTROL ROOM

Open http://127.0.0.1:8765 while Hush is running.

START
Run ./launch.sh from this folder. It starts the local service and opens the UI.
Keep that terminal open; Ctrl+C stops the service and releases the Bluetooth link.
You can also double-click Hush.desktop if your desktop allows local launchers.
For terminal-only startup: python3 server.py
For a different port: python3 server.py --port 8766

REQUIREMENTS
Linux, Python 3.10+ with Bluetooth sockets, and BlueZ's bluetoothctl.
No pip packages, npm install, cloud account, or build step.
Pair/connect the over-ear WH-1000XM4 in your normal Bluetooth settings first.
This app implements the WH-1000XM4's MDR v1 protocol, not the WF earbuds or XM5.

CONTROLS
ANC, ambient sound, off, ambient level, voice focus; quick listening scenes;
Sony EQ presets and custom Clear Bass + five-band EQ; DSEE Extreme;
Speak-to-Chat; wear detection; voice guidance; battery, firmware and codec.
The Activity view shows command/reply payloads and confirmed setting changes.
The Nerd view adds exact RFCOMM frames, including ACKs, sequence numbers, escapes
and checksums; filters, pause, a hex inspector, JSON export and a TX/RX rate graph.
It measures control ACK RTT and reads PipeWire codec/profile, host sample format,
reported sink latency, recording streams, RSSI margin, link quality, host transmit
power, encryption/authentication, AFH channels and the supervision timeout.
Read-only battery and audio-preference heartbeats run every two seconds.
Keys 1 / 2 / 3 select ANC / ambient / off when a form control is not focused.

Changes are read back before success is reported. The app reconnects when its
Bluetooth control link drops, and listens for the earcup button's notifications.
A disconnected screen shows last-known settings with controls disabled.
Scenes change exactly the settings listed under their names and retain them
until you change them. Sound settings are stored by the headphones themselves.

LATENCY, RANGE & DISCORD
Control RTT is measured. PipeWire sink latency is a host-reported estimate and
may be cached while idle. Acoustic end-to-end latency is unmeasured.
Classic RSSI is a dB margin relative to a controller-defined range, not dBm;
zero means within that range. Link quality is a vendor-defined 0..255 scale,
not packet delivery percentage. AFH counts permitted channels, not busy ones.
Sony's HD-audio gate is queried through E6 01; its inverse is shown as the
quality/stability preference. The actual PipeWire codec is displayed separately.
Distance is not reported by the link.

Opening the headset mic switches Classic Bluetooth from A2DP to HFP/HSP.
WirePlumber's automatic switch is enabled on this machine. Nerd flags call mode
and lists recording applications without recording microphone samples.
Use a separate mic in Discord and keep XM4 output on A2DP for stereo fidelity.
No Discord settings or system audio routing are changed automatically.

OPTIONAL FULL HCI CAPTURE
The regular app captures its own Sony RFCOMM traffic. It cannot monitor audio
traffic without HCI monitor permission. In Nerd, select the HCI source and run
the displayed sudo command for hci_capture.py in a terminal.
This passive helper filters by the headset's handles before sending packets
over a mode-0600 local Unix socket. No persistent capabilities are installed,
no raw capture is written to disk, and Ctrl+C stops it. HCI is host/controller
traffic: radio retransmissions, loss rate and acoustic delay are not observable.
This privileged capture path has not been run in this session; the OS denied
HCI monitor access to the regular user. Radio queries work without that capture.

PRIVACY & LOCAL ACCESS
The service binds only to 127.0.0.1. It checks Host/Origin and a per-run token
before accepting control requests. It makes no Internet requests. External
research links open only when clicked. Raw backups are never HTTP-served.
All app source is included under AGPL-3.0-or-later; see LICENSE and UPSTREAM.txt.

LAB / READ-ONLY PROBING
The Lab view displays the saved results from this headset: service channels,
NVDM backup size, record validation, and interesting configuration key names.

To repeat a single-page read and save a sanitized report:
  python3 probe.py --report probe-report.json

To also test physical flash page zero (one read request; returned bytes discarded):
  python3 probe.py --flash-header --report probe-report.json

To make a new private settings/calibration backup (choose a NEW filename):
  python3 probe.py --backup backups/new-nvdm.bin --report probe-report.json

To inspect a backup offline without printing identity or pairing values:
  python3 inspect_backup.py backups/new-nvdm.bin --report inventory-report.json

The backup contains Bluetooth pairing records and device identity. Keep the
backups directory local and private. Backup files use mode 0600. A SHA-256
sidecar and NVDM record checksums detect accidental corruption. This is a copy
of logical NVDM storage, not a complete firmware or bootloader image, and is
not a demonstrated recovery mechanism for a bricked headset.

No firmware flasher, raw command console, RAM writer, or calibration writer
is exposed by Hush. LAB-NOTES.txt explains what was observed and what is only
reported by the firmware research community.

TESTS
  python3 -m unittest -v test_hush.py

TROUBLESHOOTING
If audio works but control is unavailable, close other Sony-control desktop
apps and the phone's Sound Connect app, then use Reconnect in Hush. If the
device is disconnected, reconnect using your system's Bluetooth settings.
If Hush reports the local app is offline, start launch.sh and reload the page.
The runtime channel cache is private and lives under .runtime in this folder.
