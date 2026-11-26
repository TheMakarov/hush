#!/usr/bin/env python3
"""Hush: a local, hardware-backed Sony WH-1000XM4 control room.
SPDX-License-Identifier: AGPL-3.0-or-later
"""
from __future__ import annotations

import argparse
import copy
import hmac
import json
import os
from pathlib import Path
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import sony_protocol as sony
from telemetry import WireCapture, TappedSocket, Telemetry, HCIFeed

ROOT = Path(__file__).resolve().parent
# Keep runtime artifacts beside the app; never write into the user's home config.
sony.CACHE_DIR = str(ROOT / ".runtime" / "channel-cache")

QUERIES = {
    "nc": (sony.MSG_COMMAND_1, bytes([sony.ASC_GET, 2])),
    "ambient-level": (sony.MSG_COMMAND_1, bytes([sony.ASC_GET, 2])),
    "focus-on-voice": (sony.MSG_COMMAND_1, bytes([sony.ASC_GET, 2])),
    "eq": (sony.MSG_COMMAND_1, bytes([sony.EQUALIZER_GET, 1])),
    "eq-bands": (sony.MSG_COMMAND_1, bytes([sony.EQUALIZER_GET, 1])),
    "dsee": (sony.MSG_COMMAND_1, bytes([sony.UPSAMPLING_GET, 2])),
    "speak-to-chat": (sony.MSG_COMMAND_1, bytes([sony.APO_GET, 5])),
    "pause-when-taken-off": (sony.MSG_COMMAND_1, bytes([sony.APO_GET, 3])),
    "voice-notifications": (sony.MSG_COMMAND_2, bytes([sony.VOICE_NOTIFICATIONS_GET, 1, 1])),
}
STATE_KEYS = {"nc": "nc_mode", "ambient-level": "ambient_level", "focus-on-voice": "focus_on_voice",
              "eq": "eq_preset", "eq-bands": "eq_bands", "dsee": "dsee", "speak-to-chat": "speak_to_chat",
              "pause-when-taken-off": "pause_when_taken_off", "voice-notifications": "voice_notifications"}
SCENES = {
    "focus": [("nc", "noise-cancelling"), ("speak-to-chat", False)],
    "aware": [("nc", "ambient-sound"), ("ambient-level", 12), ("focus-on-voice", True)],
    "natural": [("nc", "off")],
}


class ObservedLink(sony.Link):
    def __init__(self, address, owner):
        super().__init__(address, on_change=owner.publish)
        self.owner = owner
        self.replies = {}

    def _open(self, channel, timeout):
        return TappedSocket(super()._open(channel, timeout), self.owner.wire)

    def write(self, msg_type, payload, wait_ack=True):
        self.sent_at = time.monotonic()
        self.owner.packet("TX", msg_type, payload)
        super().write(msg_type, payload, wait_ack)

    def wait_for_ack(self):
        if not super().wait_for_ack():
            with self.owner.wire.lock:
                self.owner.wire.ack_timeouts += 1
            raise sony.NotConnected("The headphones did not acknowledge the command.")
        self.owner.wire.ack((time.monotonic()-self.sent_at)*1000)
        return True

    def dispatch(self, msg_type, payload):
        self.owner.packet("RX", msg_type, payload)
        if payload:
            self.replies[(msg_type, payload[0])] = time.monotonic()
        super().dispatch(msg_type, payload)
        if msg_type==sony.MSG_COMMAND_1 and len(payload)==4 and payload[0] in (0xe7,0xe9) and payload[1]==1 and payload[3] in (0,1):
            self.state['hd_audio_allowed']=payload[3]==0
            self.state['quality_priority']='sound-quality' if payload[3]==0 else 'stable-connection'
            self.owner.publish(self.state)

    def refresh(self):
        super().refresh()
        self.request([sony.req(bytes([0xe6,1]))],settle=.25)
        return self.state


class Controller:
    def __init__(self, address=None):
        (ROOT / ".runtime").mkdir(mode=0o700, exist_ok=True)
        self.address = address
        self.link = None
        self.lock = threading.RLock()
        self.state = sony.initial_state()
        self.phase = "discovering"
        self.updated = None
        self.events = []
        self.packets = []
        self.jobs = queue.Queue(maxsize=24)
        self.stop = threading.Event()
        self.next_attempt = 0
        self.next_poll = 0
        self.retry = 3
        self.revision = 0
        self.wire = WireCapture()
        self.connections = 0
        self.thread = threading.Thread(target=self.run, daemon=True, name="sony-bluetooth")

    def publish(self, state):
        with self.lock:
            self.state = copy.deepcopy(state)
            self.updated = time.time()
            self.revision += 1

    def event(self, message, kind="info"):
        with self.lock:
            self.events.append({"time": time.time(), "message": message, "kind": kind})
            self.events = self.events[-80:]

    def packet(self, direction, msg_type, payload):
        with self.lock:
            self.packets.append({"time": time.time(), "direction": direction,
                                 "type": f"{msg_type:02X}", "payload": payload.hex(" ").upper()})
            self.packets = self.packets[-100:]

    def snapshot(self):
        with self.lock:
            return {"state": copy.deepcopy(self.state), "phase": self.phase, "updated": self.updated,
                    "events": list(reversed(self.events[-30:])), "packets": list(reversed(self.packets[-40:])),
                    "revision": self.revision, "server_time": time.time()}

    def connect(self):
        with self.lock:
            self.phase = "connecting"
        device = sony.find_device(self.address)
        if device is None:
            raise sony.NotConnected("Connect your WH-1000XM4 in Bluetooth settings, then retry.")
        if device["name"].upper() != "WH-1000XM4":
            raise sony.NotConnected("Hush currently supports the over-ear WH-1000XM4 only.")
        link = ObservedLink(device["address"], self)
        self.link = link
        link.state["name"] = device["name"]
        link.state["features"] = sony.features_for(device["name"])
        channel = link.connect()
        link.refresh()
        if link.state["nc_mode"] is None:
            raise sony.NotConnected("Connected, but Sony did not return its sound-control state.")
        self.publish(link.state)
        with self.lock:
            self.phase = "connected"
        self.retry = 3
        self.next_poll = time.monotonic() + 2
        self.connections += 1
        self.event(f"WH-1000XM4 connected · RFCOMM channel {channel}", "connected")

    def disconnect(self, exc):
        if self.link:
            self.link.close()
            state = copy.deepcopy(self.link.state)
        else:
            state = sony.initial_state()
        self.link = None
        state["connected"] = False
        state["error"] = str(exc)
        self.publish(state)
        with self.lock:
            self.phase = "disconnected"
        self.event(str(exc), "error")
        self.next_attempt = time.monotonic() + self.retry
        self.retry = min(30, self.retry * 2)

    def set_verified(self, key, value):
        if key not in QUERIES:
            raise ValueError("That setting is not exposed by Hush.")
        # Validate before sending. Only ordinary sound settings are exposed.
        requests = sony.setting_requests(self.link.state, key, value)
        self.link.request(requests, settle=0.15)
        msg_type, query = QUERIES[key]
        started = time.monotonic()
        self.link.request([(msg_type, query)], settle=0.2)
        deadline = time.monotonic() + 2
        while self.link.replies.get((msg_type, query[0] + 1), 0) < started:
            if time.monotonic() >= deadline:
                raise sony.NotConnected("The command was sent, but its readback did not arrive. Reconnecting.")
            self.link.pump(0.15)
        state = self.link.state
        observed = state.get(STATE_KEYS[key])
        expected = value
        if key in ("dsee", "speak-to-chat", "pause-when-taken-off", "focus-on-voice", "voice-notifications"):
            expected = sony.parse_bool(value)
        elif key == "ambient-level":
            expected = int(value)
        elif key == "eq-bands":
            numbers = [int(x) for x in str(value).split(",")]
            expected = numbers[1:]
            if state.get("eq_bass") != numbers[0]:
                raise ValueError("The headset returned a different Clear Bass value. Try again.")
        if observed != expected:
            raise ValueError(f"The headset returned {observed!r} for {key}; requested {expected!r}.")
        self.publish(state)

    def execute(self, job):
        action = job.get("action")
        if action == "reconnect":
            if self.link:
                self.link.close()
            self.link = None
            self.connect()
        else:
            if self.link is None:
                raise sony.NotConnected("Headphones are disconnected. Reconnect them and try again.")
            if action == "refresh":
                self.link.refresh()
                self.publish(self.link.state)
                self.event("Headset settings refreshed")
            elif action == "set":
                key, value = job.get("key"), job.get("value")
                self.set_verified(key, value)
                self.event(f"{key.replace('-', ' ').capitalize()} · {str(value).replace('-', ' ')}", "change")
            elif action == "scene":
                scene = job.get("scene")
                if scene not in SCENES:
                    raise ValueError("Unknown scene")
                # Changes are confirmed individually. If a later one fails, report partial application.
                done = []
                try:
                    for key, value in SCENES[scene]:
                        self.set_verified(key, value)
                        done.append(key)
                except Exception as exc:
                    raise ValueError(f"Scene incomplete; applied: {', '.join(done) or 'none'}. {exc}") from exc
                self.event({"focus": "Deep work", "aware": "Stay aware", "natural": "Natural"}[scene] + " scene confirmed", "change")
            else:
                raise ValueError("Unknown action")

    def submit(self, job):
        done = threading.Event()
        result = {}
        self.jobs.put_nowait((job, done, result))
        if not done.wait(35):
            return {"ok": False, "error": "The device is taking longer than expected. Check live status before retrying.", **self.snapshot()}
        return {**result, **self.snapshot()}

    def run(self):
        while not self.stop.is_set():
            if self.link is None and time.monotonic() >= self.next_attempt:
                try:
                    self.connect()
                except Exception as exc:
                    self.disconnect(exc)
            try:
                job, done, result = self.jobs.get_nowait()
            except queue.Empty:
                job = None
            if job is not None:
                try:
                    self.execute(job)
                    result["ok"] = True
                except (sony.NotConnected, OSError) as exc:
                    self.disconnect(exc)
                    result.update(ok=False, error=str(exc))
                except Exception as exc:
                    self.event(str(exc), "error")
                    result.update(ok=False, error=str(exc))
                finally:
                    done.set()
            try:
                if self.link:
                    self.link.pump(0.12)
                    if time.monotonic() >= self.next_poll:
                        before = self.link.last_rx
                        self.link.request([sony.req(bytes([sony.BATTERY_GET, sony.BATTERY_SINGLE])), sony.req(bytes([0xe6,1]))], settle=0.05)
                        if self.link.last_rx <= before:
                            raise sony.NotConnected("The headset stopped answering. Reconnecting.")
                        self.publish(self.link.state)
                        self.next_poll = time.monotonic() + 2
                else:
                    self.stop.wait(0.12)
            except Exception as exc:
                self.disconnect(exc)
        if self.link:
            self.link.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "Hush/1.0"

    def log_message(self, *args):
        pass

    def permitted(self):
        # Exact Host + Origin checks prevent DNS rebinding and cross-site device writes.
        host = self.headers.get("Host", "")
        if host not in self.server.allowed_hosts:
            self.respond(403, {"error": "Local access only"})
            return False
        return True

    def respond(self, status, data, mime="application/json"):
        body = json.dumps(data).encode() if mime == "application/json" else data
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.permitted():
            return
        path = urlsplit(self.path).path
        if path == "/api/state":
            self.respond(200, {**self.server.controller.snapshot(), "token": self.server.token})
        elif path == "/api/nerd":
            state=self.server.controller.snapshot()
            self.respond(200, {"wire":self.server.controller.wire.snapshot(),"telemetry":self.server.telemetry.snapshot(),
                               "hci":self.server.hci.snapshot(),"connections":self.server.controller.connections,
                               "state":state["state"],"phase":state["phase"],"capture_socket":self.server.hci.path})
        elif path == "/api/lab":
            report = ROOT / "probe-report.json"
            data = json.loads(report.read_text()) if report.exists() else {"nvdm": {"status": "not-tested"}, "services": []}
            inventory = ROOT / "inventory-report.json"
            if inventory.exists():
                data["inventory"] = json.loads(inventory.read_text())
            self.respond(200, data)
        elif path in ("/", "/index.html", "/style.css", "/nerd.css", "/app.js", "/nerd.js", "/headphones.svg", "/icon.svg", "/LICENSE"):
            name = "index.html" if path == "/" else path[1:]
            mime = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}.get(Path(name).suffix, "text/plain; charset=utf-8")
            self.respond(200, (ROOT / name).read_bytes(), mime)
        elif path == "/api/source":
            self.respond(200, {"license": "AGPL-3.0-or-later", "source": str(ROOT),
                               "upstream": "https://github.com/gabamnml/omarchy-sony-headphones"})
        else:
            self.respond(404, {"error": "Not found"})

    def do_POST(self):
        if not self.permitted():
            return
        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{h}" for h in self.server.allowed_hosts}:
            self.respond(403, {"error": "Invalid origin"})
            return
        if not hmac.compare_digest(self.headers.get("X-Hush-Token", ""), self.server.token):
            self.respond(403, {"error": "Refresh Hush to authorize this request"})
            return
        if self.path != "/api/control":
            self.respond(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2048:
                raise ValueError("Invalid request size")
            self.connection.settimeout(5)
            job = json.loads(self.rfile.read(length))
            if not isinstance(job, dict):
                raise ValueError("Expected an object")
            result = self.server.controller.submit(job)
            self.respond(200 if result["ok"] else 409, result)
        except (ValueError, queue.Full) as exc:
            self.respond(400, {"ok": False, "error": str(exc) or "Device queue is full"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--address", help="Optional paired WH-1000XM4 Bluetooth address")
    args = parser.parse_args()
    if args.address and not sony.MAC_RE.fullmatch(args.address):
        parser.error("Invalid Bluetooth address")
    controller = Controller(args.address)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    server.controller = controller
    server.token = secrets.token_hex(32)
    server.allowed_hosts = {f"127.0.0.1:{args.port}", f"localhost:{args.port}"}
    address_provider=lambda: controller.snapshot()["state"].get("address")
    server.telemetry=Telemetry(address_provider,controller.event)
    server.hci=HCIFeed(ROOT,address_provider)
    server.telemetry.thread.start()
    server.hci.thread.start()
    controller.thread.start()
    print(f"Hush is listening at http://127.0.0.1:{args.port}", flush=True)
    print("Bluetooth stays local. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop.set()
        server.telemetry.stop.set()
        server.hci.stop.set()
        controller.thread.join(timeout=3)
        server.server_close()


if __name__ == "__main__":
    main()
