#!/usr/bin/env python3
"""Read-only XM4 service discovery and a bounded Airoha NVDM page probe.

Default: resolve advertised services and read logical NVDM page zero.
--backup PATH: copy all 512 KiB of logical NVDM to a private local file.
No update mode, flash erase/program, RAM writes, reboot, or firmware installation.
--flash-header: additionally request just physical flash page zero (read-only).
SPDX-License-Identifier: AGPL-3.0-or-later
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import time
import sony_protocol as sony

SERVICES = {
    "Sony sound control": sony.SERVICE_UUID,
    "Sony Serial MC": "b9b213ce-eeab-49e4-8fd9-aa478ed1b26b",
    "Airoha RACE": "8901dfa8-5c7e-4d8f-9f0c-c2b70683f5f0",
}
TOTAL = 512 * 1024


def receive_exact(sock, size):
    result = bytearray()
    while len(result) < size:
        chunk = sock.recv(size-len(result))
        if not chunk:
            raise ConnectionError("The headset closed the diagnostic channel.")
        result.extend(chunk)
    return bytes(result)


def read_page(sock, address):
    # Exactly one operation is implemented: RACE PAGE_READ (0x0403),
    # logical NVDM storage 1, one 256-byte page. No arbitrary opcode parameter.
    if address % 256 or not 0 <= address < TOTAL:
        raise ValueError("Outside the logical NVDM store")
    payload = struct.pack("<BBI", 1, 1, address)
    sock.sendall(struct.pack("<BBHH", 5, 0x5A, 2+len(payload), 0x0403)+payload)
    deadline = time.monotonic()+5
    for _ in range(8):
        sock.settimeout(max(.01,deadline-time.monotonic()))
        header = receive_exact(sock, 4)
        if header[0] != 5 or header[1] not in (0x5B, 0x5D):
            raise ValueError("Unexpected RACE response framing")
        length = int.from_bytes(header[2:4], "little")
        if not 3 <= length <= 2048:
            raise ValueError("Invalid RACE response length")
        body = receive_exact(sock,length)
        if int.from_bytes(body[:2],"little") != 0x0403:
            continue
        if body[2] != 0:
            raise PermissionError(f"RACE page read returned status 0x{body[2]:02X}.")
        if len(body) != 266:
            raise ValueError(f"Unexpected page response size: {len(body)}")
        if body[3] != 1:
            raise ValueError("The response did not identify NVDM storage")
        # Observed on this XM4: status/storage, two reserved zero bytes,
        # address (u32 LE), then 256 data bytes. Validate address before saving.
        if int.from_bytes(body[6:10],"little") != address:
            raise ValueError("The device returned a different page address")
        return body[10:]
    raise TimeoutError("No matching NVDM page reply")


def run_probe(address=None, backup=None):
    device=sony.find_device(address)
    if not device or device['name'].upper()!='WH-1000XM4':
        raise RuntimeError("Connect an over-ear WH-1000XM4 first.")
    report={"checked_at":time.time(),"model":device['name'],"read_only":True,"services":[],
            "nvdm":{"status":"not-tested"},"firmware":{"installed":None,"full_flash_dump":"not-tested",
            "flashing":"Not performed. Community tools support known official signed images; not arbitrary custom firmware.",
            "note":"A logical settings-store read is not a full firmware or bootloader dump."}}
    race_channel=None
    for name,uuid in SERVICES.items():
        channel=sony.sdp_channel(device['address'],bytes.fromhex(uuid.replace('-','')),timeout=4)
        report['services'].append({"name":name,"uuid":uuid,"channel":channel})
        if name=='Airoha RACE':race_channel=channel
    if race_channel is None:
        report['nvdm']={"status":"unavailable","detail":"The headset did not advertise a resolvable RACE service."}
        return report
    sock=socket.socket(socket.AF_BLUETOOTH,socket.SOCK_STREAM,socket.BTPROTO_RFCOMM)
    sock.settimeout(5)
    try:
        sock.connect((device['address'],race_channel))
        page=read_page(sock,0)
        if page[:4]!=b'NVDM':
            raise ValueError("Page zero did not contain the expected NVDM signature")
        report['nvdm']={"status":"readable","detail":"Read 256 bytes from logical NVDM page zero; NVDM signature verified.",
                        "sample_bytes":len(page),"signature":"NVDM","backup_bytes":None}
        if backup:
            target=Path(backup).resolve()
            target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            data=bytearray(page)
            for offset in range(256,TOTAL,256):
                data.extend(read_page(sock,offset))
            valid=sum(data[i:i+4]==b'NVDM' for i in range(0,TOTAL,4096))
            if valid!=128:
                raise ValueError(f"Expected 128 NVDM block headers, found {valid}. Backup not saved.")
            # Exclusive creation: never overwrite an earlier device backup.
            fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as file:file.write(data)
            digest=hashlib.sha256(data).hexdigest()
            sidecar=target.with_suffix(target.suffix+'.sha256')
            fd=os.open(sidecar,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as file:file.write(f'{digest}  {target.name}\n')
            report['nvdm'].update(backup_bytes=len(data),sha256=digest,blocks_valid=valid,backup_path=str(target))
    except (OSError,ValueError) as exc:
        report['nvdm']={"status":"blocked","detail":str(exc),"backup_bytes":None}
    finally:sock.close()
    return report


def probe_flash_header(address, channel):
    """Request physical flash page zero, report status, discard any returned data."""
    sock=socket.socket(socket.AF_BLUETOOTH,socket.SOCK_STREAM,socket.BTPROTO_RFCOMM)
    sock.settimeout(5)
    try:
        sock.connect((address,channel))
        payload=struct.pack('<BBI',0,1,0)
        sock.sendall(struct.pack('<BBHH',5,0x5a,2+len(payload),0x0403)+payload)
        header=receive_exact(sock,4)
        length=int.from_bytes(header[2:4],'little')
        if header[:2]!=bytes([5,0x5b]) or not 3<=length<=2048:
            raise ValueError('Unexpected flash-read reply')
        body=receive_exact(sock,length)
        if body[:2]!=struct.pack('<H',0x0403):raise ValueError('Unexpected response opcode')
        return {'status':'header-readable' if body[2]==0 else 'denied','return_code':f'0x{body[2]:02X}',
                'storage_type':0,'address':0,'request':'One read-only 256-byte physical-flash page request. No update-mode handshake.'}
    except (OSError,ValueError) as exc:
        return {'status':'unavailable','detail':str(exc)}
    finally:sock.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address')
    parser.add_argument('--backup',type=Path,help='Read all 512 KiB to this NEW private file; contains pairing records. Keep local.')
    parser.add_argument('--report',type=Path,help='Save a sanitized report (never raw memory or pairing values).')
    parser.add_argument('--flash-header',action='store_true',help='Also test physical flash page zero with a single read request.')
    args=parser.parse_args()
    report=run_probe(args.address,args.backup)
    if args.flash_header:
        device=sony.find_device(args.address)
        channel=next((item['channel'] for item in report['services'] if item['name']=='Airoha RACE'),None)
        if device and channel:
            report['firmware']['physical_flash_probe']=probe_flash_header(device['address'],channel)
    # Firmware comes from the local live app if it is running; otherwise unknown.
    report['firmware']['installed']=None
    try:
        import urllib.request
        live=json.load(urllib.request.urlopen('http://127.0.0.1:8765/api/state',timeout=2))
        report['firmware']['installed']=live['state'].get('firmware')
    except Exception:pass
    if args.report:args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
