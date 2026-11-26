"""Failure handling and loopback control security; no real hardware writes."""
import json
import socket
import struct
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import server
import sony_protocol as sony
import probe
from telemetry import WireCapture


class EchoDemo(sony.DemoLink):
    def __init__(self):
        super().__init__()
        self.replies = {}
    def dispatch(self, kind, payload):
        self.replies[(kind, payload[0])] = time.monotonic()
        super().dispatch(kind, payload)


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.controller = server.Controller()
        self.controller.link = EchoDemo()
        self.controller.link.refresh()

    def test_device_refusal_does_not_claim_success(self):
        # It acknowledges writes but keeps reporting the old sound mode.
        original = self.controller.link.write
        def refusing(kind, payload, wait_ack=True):
            if payload[0] != sony.ASC_SET:
                original(kind, payload, wait_ack)
        self.controller.link.write = refusing
        with self.assertRaisesRegex(ValueError, "headset returned"):
            self.controller.set_verified('nc', 'off')

    def test_unsupported_commands_never_reach_device(self):
        with patch.object(self.controller.link, 'write') as write:
            for key in ['power-off', 'firmware', 'touch-sensor', 'raw']:
                with self.assertRaises(ValueError):
                    self.controller.set_verified(key, True)
            write.assert_not_called()

    def test_actual_readback_for_scene(self):
        self.controller.execute({'action':'scene','scene':'aware'})
        self.assertEqual(self.controller.state['nc_mode'], 'ambient-sound')
        self.assertEqual(self.controller.state['ambient_level'],12)
        self.assertTrue(self.controller.state['focus_on_voice'])


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.http = ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.http.allowed_hosts = {f'127.0.0.1:{self.http.server_port}'}
        self.http.token='a'*64
        self.http.controller=server.Controller()
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.url=f'http://127.0.0.1:{self.http.server_port}'
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join()
    def reject(self, path, headers=None, data=None):
        request=urllib.request.Request(self.url+path,headers=headers or {},data=data)
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request)
        code=raised.exception.code
        raised.exception.close()
        return code
    def test_cross_site_and_missing_token_blocked(self):
        data=b'{"action":"set","key":"nc","value":"off"}'
        self.assertEqual(self.reject('/api/control',data=data),403)
        self.assertEqual(self.reject('/api/control',headers={'Origin':'https://evil.example','X-Hush-Token':self.http.token},data=data),403)
        self.assertTrue(self.http.controller.jobs.empty())
    def test_host_rebinding_and_private_backup_not_served(self):
        self.assertEqual(self.reject('/api/state',headers={'Host':'evil.example'}),403)
        self.assertEqual(self.reject('/backups/xm4-nvdm-2026-11-26.bin'),404)
        self.assertEqual(self.reject('/../server.py'),404)


class FakeSocket:
    def __init__(self,response):self.response=response;self.sent=[]
    def settimeout(self,t):pass
    def sendall(self,data):self.sent.append(data)
    def recv(self,n):
        chunk,self.response=self.response[:n],self.response[n:]
        return chunk


class ProbeTests(unittest.TestCase):
    def test_bounded_read_only_and_address_checked(self):
        body=struct.pack('<HBBHI',0x0403,0,1,0,256)+b'NVDM'+bytes(252)
        frame=struct.pack('<BBH',5,0x5B,len(body))+body
        sock=FakeSocket(frame)
        self.assertEqual(probe.read_page(sock,256)[:4],b'NVDM')
        self.assertEqual(int.from_bytes(sock.sent[0][4:6],'little'),0x0403)
        wrong=FakeSocket(frame)
        with self.assertRaisesRegex(ValueError,'different page address'):probe.read_page(wrong,0)
        for address in [-1,1,probe.TOTAL]:
            with self.assertRaises(ValueError):probe.read_page(FakeSocket(b''),address)
    def test_error_reply_is_not_a_dump(self):
        body=struct.pack('<HB',0x0403,3)
        sock=FakeSocket(struct.pack('<BBH',5,0x5B,len(body))+body)
        with self.assertRaises(PermissionError):probe.read_page(sock,0)


class CaptureTests(unittest.TestCase):
    def test_fragmented_exact_frames_and_acks(self):
        capture=WireCapture()
        frame=sony.encode_message(sony.MSG_COMMAND_1,0,bytes([0x68,0x3e,0x3d,0x3c]))
        ack=sony.encode_message(sony.MSG_ACK,1,b'')
        capture.ingest('TX',frame)
        capture.ingest('RX',ack[:3])
        self.assertEqual(len(capture.snapshot()['frames']),1)
        capture.ingest('RX',ack[3:])
        data=capture.snapshot()
        self.assertEqual(bytes.fromhex(data['frames'][1]['raw']),frame)
        self.assertEqual(data['frames'][0]['label'],'ACK')
        self.assertTrue(all(item['valid'] for item in data['frames']))
        self.assertEqual(data['tx_bytes']+data['rx_bytes'],len(frame)+len(ack))

    def test_invalid_frame_not_marked_verified_and_bounded(self):
        capture=WireCapture()
        frame=bytearray(sony.encode_message(sony.MSG_COMMAND_1,0,b'\x10\x00'))
        frame[-2]^=1
        capture.ingest('RX',frame)
        self.assertFalse(capture.snapshot()['frames'][0]['valid'])
        self.assertEqual(capture.snapshot()['invalid_frames'],1)
        capture.ingest('RX',b'x'*10000)
        self.assertLessEqual(len(capture.buffers['RX']),4096)


if __name__=='__main__':unittest.main()
