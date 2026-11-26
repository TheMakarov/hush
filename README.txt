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
Nerd metrics use PipeWire, pactl, wpctl and libbluetooth. Real packet audio
playback additionally needs FFmpeg with its SBC decoder (available on this machine).
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

PARADE HALL / MARCH EQ
Sound includes a locally named preset intended as a starting point for brass
and snare-heavy marches: Clear Bass +2, 400 Hz -2, 1 kHz +1, 2.5 kHz +2,
6.3 kHz +2, 16 kHz +1. It is a taste choice, not a measured universal optimum.
Before its first application, Hush privately saves the previous headset preset
and full curve in .runtime/eq-before-music.json. Restore previous EQ reads the
original curve back after restoring it. These local preferences are Git-ignored.

PACKET STUDIO
The primary Studio recorder reconstructs actual audio sent to the XM4:
  1. Start the optional headset-only HCI helper shown in Nerd.
  2. Play audio on this computer through the XM4 using A2DP SBC / SBC-XQ.
  3. Open Studio and record 5, 10 or 20 seconds of real packets.
  4. Play/download the decoded WAV, exact extracted SBC stream, raw packet JSON,
     and a receipt with RTP sequence numbers, source frame IDs and hashes.

The pipeline reassembles HCI ACL TX fragments into L2CAP PDUs, removes RTP/SBC
transport headers, validates SBC frame boundaries and invokes the system FFmpeg
decoder. No microphone or PipeWire loopback source supplies the recording.
The resulting WAV contains the decoded transmitted audio before the headset's
DSP/EQ. It is the stream sent by this computer, not a recording of the earcups.
AAC, LDAC and HFP/microphone decoding are not implemented. Capture gaps and
decoder warnings are reported in the receipt; missing audio is not invented.

Original audio, reverse tape, and orbit echo operate on the actual decoded PCM.
The original encoded SBC bytes remain available. Recordings are bounded to
20 seconds / 8 MiB of captured data, two clips are retained in memory, and no
recorded audio is committed to Git. Save downloads you want to keep before
restarting the server. Capturing is passive and does not change audio routing.

Verified on this XM4: 10.00 seconds reconstructed from 750 RTP media packets,
3,750 SBC frames; 48 kHz dual-channel stereo, bitpool 39, 504 kb/s, zero RTP
sequence gaps and no decoder warnings. This measures the host-side capture;
it does not measure over-the-air loss or the headset's acoustic output.

The separate, collapsible Byte instruments section turns captured bytes into
newly synthesized music:
  Packet Garden: C major pentatonic bells, left/right conversation, short echo.
  Modem Dreams: selected payload bytes become custom two-tone FSK (560/900 Hz).
  Wire Drums: outgoing packets kick, incoming packets clap, ACKs become hats.
Choose a live capture, the packet bench selection, the included saved real XM4
capture, or import a JSON export. Compose 8/16/32 seconds, fit timestamps to a
groove at 60–160 BPM or preserve their relative spacing, then play/download WAV.
The score view traces each event to a frame ID, wire-byte hash and payload byte.
Download score JSON for source packets and the full recipe. All renders are
local, deterministic, stereo 16-bit PCM at 24 kHz. They are sonifications,
not recovered audio recordings. Rendering never sends settings to the headset.

Listen live previews new packet arrivals with short synthesized tones at the
chosen listening level. Leaving Studio stops live synthesis and pauses playback.
The browser starts sound only after a Play/Listen action. In-memory renders
expire after 20 minutes or when displaced by four newer renders; downloaded
files and the browser's loaded audio remain yours.

Offline rendering (no connected headphones needed):
  python3 sonification.py examples/xm4-control.json --output sonifications/garden.wav
  python3 sonification.py examples/xm4-control.json --preset modem --output sonifications/modem.wav
  python3 sonification.py examples/xm4-control.json --preset drums --output sonifications/drums.wav
Each command also writes a .score.json sidecar. Runtime exports are Git-ignored.

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
The regular user cannot open the HCI monitor channel. The user-started privileged
helper and real SBC-XQ reconstruction have now been verified on this headset.
Radio queries and Sony control-frame capture also work without that helper.

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
