#!/usr/bin/env python3
"""Optional passive HCI monitor. Needs CAP_NET_RAW/NET_ADMIN (typically sudo).
Filters ACL/SCO packets by this headset's current handles before local delivery.
Never sends Bluetooth commands, records to disk, or changes controller settings.
AGPL-3.0-or-later.
"""
import argparse
import fcntl
import json
from pathlib import Path
import socket
import struct
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address',required=True)
    parser.add_argument('--socket',default=str(Path(__file__).resolve().parent/'.runtime'/'hci-feed.sock'))
    args=parser.parse_args();address=args.address.upper()
    monitor=socket.socket(socket.AF_BLUETOOTH,socket.SOCK_RAW,socket.BTPROTO_HCI)
    monitor.bind((65535,2));monitor.settimeout(.2)
    radio=socket.socket(socket.AF_BLUETOOTH,socket.SOCK_RAW,socket.BTPROTO_HCI);radio.bind((0,0))
    feed=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);feed.settimeout(.05)
    handles=set();next_scan=0
    print('Passive HCI capture started. Only the selected headset is forwarded to Hush. Ctrl+C stops it.',flush=True)
    try:
        while True:
            if time.monotonic()>=next_scan:
                buffer=bytearray(struct.pack('<HH',0,32)+bytes(512));fcntl.ioctl(radio,0x800448d4,buffer,True)
                count=min(32,struct.unpack_from('<H',buffer,2)[0]);handles=set()
                for i in range(count):
                    handle,addr=struct.unpack_from('<H6s',buffer,4+16*i)
                    if ':'.join(f'{b:02X}' for b in addr[::-1])==address:handles.add(handle)
                try:feed.sendto(json.dumps({'address':address,'direction':'RX','raw':''}).encode(),args.socket)
                except OSError:pass
                next_scan=time.monotonic()+1
            try:data=monitor.recv(8192)
            except socket.timeout:continue
            if len(data)<10:continue
            opcode,index,length=struct.unpack_from('<HHH',data)
            if index!=0 or opcode not in (4,5,6,7) or len(data)!=6+length:continue
            packet=data[6:];handle=int.from_bytes(packet[:2],'little')&0xfff
            if handle not in handles:continue
            row={'address':address,'time':time.time(),'direction':'TX' if opcode in (4,6) else 'RX','raw':packet.hex(),
                 'label':'HCI ACL' if opcode in (4,5) else 'HCI SCO','handle':handle}
            try:feed.sendto(json.dumps(row).encode(),args.socket)
            except OSError:pass
    except KeyboardInterrupt:pass
    finally:monitor.close();radio.close();feed.close()


if __name__=='__main__':main()
