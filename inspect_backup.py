#!/usr/bin/env python3
"""Offline NVDM inventory: validates records, emits names, never pairing values.
SPDX-License-Identifier: AGPL-3.0-or-later
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct


def checksum(buf):
    return (sum(buf[::2]) & 255) | ((sum(buf[1::2]) & 255) << 8)


def name_hash(buf):
    result, factor = 0, 63689
    for char in buf:
        result=(result*factor+char)&0xffffffff
        factor=(factor*378551)&0xffffffff
    return result


def inventory(path):
    data=Path(path).read_bytes()
    if len(data)!=524288:raise ValueError('Expected a 512 KiB logical NVDM backup')
    latest={};valid=invalid=blocks=0
    for block_index in range(128):
        block=data[block_index*4096:(block_index+1)*4096]
        if block[:4]!=b'NVDM':raise ValueError('Invalid block header')
        blocks+=1;offset=12
        while offset+20<=4096 and block[offset]!=255:
            status,pnum,reserved,relative,glen,nlen,vlen,index,seq,hash_value=struct.unpack_from('<BBHHBBHHII',block,offset)
            end=offset+20+glen+nlen+vlen
            if status not in (0xfc,0xf8,0xfe) or not glen or not nlen or end+2>4096:
                invalid+=1;break
            group=block[offset+20:offset+20+glen]
            name=block[offset+20+glen:offset+20+glen+nlen]
            value=block[offset+20+glen+nlen:end]
            header=block[offset+1:offset+20]
            stored=int.from_bytes(block[end:end+2],'little')
            concat=checksum(header+group+name+value)
            chunks=[checksum(part) for part in (header,group+name,value)]
            accumulator=(sum(c&255 for c in chunks)&255)|((sum(c>>8 for c in chunks)&255)<<8)
            good=stored in (concat,accumulator) and name_hash(group.rstrip(b'\0')+name.rstrip(b'\0'))==hash_value
            if good:
                valid+=1
                if status==0xfc:
                    key=(group.rstrip(b'\0').decode('ascii','replace'),name.rstrip(b'\0').decode('ascii','replace'))
                    old=latest.get(key)
                    if old is None or 0<(seq-old)&0xffffffff<0x80000000:latest[key]=seq
            else:invalid+=1
            next_offset=end+2;aligned=(next_offset+3)&~3
            offset=aligned if aligned<4096 and block[aligned] in (0xfc,0xf8,0xfe) else next_offset
    groups=Counter(group for group,name in latest)
    return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'valid_blocks':blocks,
            'valid_records':valid,'invalid_records':invalid,'active_keys':len(latest),
            'groups':dict(sorted(groups.items())),
            'config_names':sorted(name for group,name in latest if group=='config'),
            'calibration_names':sorted(f'{group}/{name}' for group,name in latest if group in ('CXD90050','DNC')),
            'privacy':'Only key names and counts are listed. Device identity and pairing values are omitted.',
            'interpretation':'A stored key name is evidence of storage, not proof that a hidden feature can be enabled.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('backup',type=Path);parser.add_argument('--report',type=Path)
    args=parser.parse_args();result=inventory(args.backup)
    if args.report:args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
