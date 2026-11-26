"""Local audio/radio telemetry and exact socket-frame capture. AGPL-3.0-or-later."""
from collections import deque
import copy
import ctypes
import fcntl
import json
import os
from pathlib import Path
import socket
import statistics
import struct
import subprocess
import threading
import time
import sony_protocol as sony

OPCODES={0x00:'INIT',0x01:'INIT REPLY',0x04:'FIRMWARE GET',0x05:'FIRMWARE REPLY',0x10:'BATTERY GET',0x11:'BATTERY REPLY',0x13:'BATTERY NOTIFY',0x18:'CODEC GET',0x19:'CODEC REPLY',0x1b:'CODEC NOTIFY',0x56:'EQ GET',0x57:'EQ REPLY',0x58:'EQ SET',0x59:'EQ NOTIFY',0x66:'SOUND CONTROL GET',0x67:'SOUND CONTROL REPLY',0x68:'SOUND CONTROL SET',0x69:'SOUND CONTROL NOTIFY',0xe6:'AUDIO FEATURE GET',0xe7:'AUDIO FEATURE REPLY',0xe8:'AUDIO FEATURE SET',0xe9:'AUDIO FEATURE NOTIFY',0xf6:'SYSTEM GET',0xf7:'SYSTEM REPLY',0xf8:'SYSTEM SET',0xf9:'SYSTEM NOTIFY'}


class WireCapture:
    def __init__(self):
        self.lock=threading.RLock();self.buffers={'TX':bytearray(),'RX':bytearray()}
        self.frames=deque(maxlen=500);self.buckets={};self.acks=deque(maxlen=120)
        self.tx_bytes=self.rx_bytes=self.tx_frames=self.rx_frames=self.bad_frames=0
        self.sequence=0;self.started=time.time();self.ack_timeouts=0

    def count(self,direction,size,source='MDR'):
        second=int(time.time());key=(source,second)
        bucket=self.buckets.setdefault(key,{'time':second,'tx_bytes':0,'rx_bytes':0,'tx_packets':0,'rx_packets':0})
        prefix='tx' if direction=='TX' else 'rx'
        bucket[f'{prefix}_bytes']+=size;bucket[f'{prefix}_packets']+=1
        for old in list(self.buckets):
            if old[1]<second-120:del self.buckets[old]

    def ingest(self,direction,data):
        with self.lock:
            if direction=='TX':self.tx_bytes+=len(data)
            else:self.rx_bytes+=len(data)
            buf=self.buffers[direction];buf.extend(data)
            # RFCOMM is a byte stream. Reassemble Sony marker-delimited frames;
            # store the actual bytes, including escapes, checksum and ACKs.
            while sony.TRAILER in buf:
                end=buf.find(sony.TRAILER);start=buf.rfind(sony.HEADER,0,end)
                raw=bytes(buf[start:end+1]) if start>=0 else b''
                del buf[:end+1]
                if not raw:continue
                self.sequence+=1
                item={'id':self.sequence,'time':time.time(),'direction':direction,'source':'MDR','size':len(raw),'raw':raw.hex(' ').upper()}
                try:
                    kind,seq,payload=sony.decode_message(raw)
                    item.update(type=f'{kind:02X}',seq=seq,valid=True,payload=payload.hex(' ').upper(),label='ACK' if kind==sony.MSG_ACK else OPCODES.get(payload[0] if payload else -1,'MDR MESSAGE'))
                except sony.ProtocolError as exc:
                    self.bad_frames+=1;item.update(valid=False,label='INVALID FRAME',error=str(exc))
                self.frames.append(item);self.count(direction,len(raw))
                if direction=='TX':self.tx_frames+=1
                else:self.rx_frames+=1
            if len(buf)>4096:buf.clear()

    def ack(self,milliseconds):
        with self.lock:self.acks.append({'time':time.time(),'ms':milliseconds})

    def snapshot(self):
        with self.lock:
            samples=[sample['ms'] for sample in self.acks]
            ordered=sorted(samples);now=int(time.time())
            rates=[]
            for second in range(now-59,now+1):
                rates.append(copy.deepcopy(self.buckets.get(('MDR',second),{'time':second,'tx_bytes':0,'rx_bytes':0,'tx_packets':0,'rx_packets':0})))
            return {'frames':list(reversed(self.frames))[:120],'rates':rates,'started':self.started,
                    'tx_bytes':self.tx_bytes,'rx_bytes':self.rx_bytes,'tx_frames':self.tx_frames,'rx_frames':self.rx_frames,
                    'invalid_frames':self.bad_frames,'ack_timeouts':self.ack_timeouts,
                    'ack_last_ms':samples[-1] if samples else None,'ack_median_ms':statistics.median(samples) if samples else None,
                    'ack_p95_ms':ordered[min(len(ordered)-1,int((len(ordered)-1)*.95))] if samples else None,
                    'ack_samples':list(self.acks)}


class TappedSocket:
    def __init__(self,sock,capture):self.sock=sock;self.capture=capture
    def sendall(self,data):
        self.sock.sendall(data);self.capture.ingest('TX',data)
    def recv(self,n):
        data=self.sock.recv(n)
        if data:self.capture.ingest('RX',data)
        return data
    def __getattr__(self,name):return getattr(self.sock,name)


def audio_state(address):
    runtime=f'/run/user/{os.getuid()}'
    env=dict(os.environ,XDG_RUNTIME_DIR=runtime,PULSE_SERVER=f'unix:{runtime}/pulse/native',DBUS_SESSION_BUS_ADDRESS=f'unix:path={runtime}/bus')
    def run(args):
        result=subprocess.run(args,env=env,capture_output=True,text=True,timeout=3)
        if result.returncode:raise RuntimeError(result.stderr.strip()[:160] or 'Audio server unavailable')
        return json.loads(result.stdout)
    sinks=run(['/usr/bin/pactl','-f','json','list','sinks'])
    cards=run(['/usr/bin/pactl','-f','json','list','cards'])
    sources=run(['/usr/bin/pactl','-f','json','list','sources'])
    captures=run(['/usr/bin/pactl','-f','json','list','source-outputs'])
    target=(address or '').upper()
    sink=next((item for item in sinks if item.get('properties',{}).get('api.bluez5.address','').upper()==target),None)
    card=next((item for item in cards if item.get('properties',{}).get('api.bluez5.address','').upper()==target or item.get('name')=='bluez_card.'+target.replace(':','_')),None)
    result={'available':True,'sink_state':sink.get('state') if sink else None,'codec':None,'profile':card.get('active_profile') if card else None,
            'format':None,'reported_latency_ms':None,'audio_sample_rate':None,'channels':None,
            'call_mode':False,'active_recorders':[],'alternate_inputs':[], 'available_profiles':[],'autoswitch':None}
    if sink:
        props=sink.get('properties',{})
        result.update(codec=props.get('api.bluez5.codec'),format=sink.get('sample_specification'))
    result['call_mode']=bool(result['profile'] and ('headset' in result['profile'] or 'handsfree' in result['profile']))
    if card:result['available_profiles']=[{'name':name,'description':profile['description']} for name,profile in card.get('profiles',{}).items() if profile.get('available')]
    source_map={item['index']:item for item in sources}
    for item in captures:
        source=source_map.get(item.get('source'),{});props=item.get('properties',{})
        # Only application/source names; never microphone samples or audio content.
        result['active_recorders'].append({'application':props.get('application.name','Unknown application'),'source':source.get('description','Unknown input'),'headset_mic':target.replace(':','_') in source.get('name','').upper() or target in source.get('name','').upper(),'corked':item.get('corked',False)})
    result['alternate_inputs']=[item.get('description',item['name']) for item in sources if '.monitor' not in item['name'] and 'bluez_' not in item['name'] and item.get('properties',{}).get('device.class')!='monitor']
    try:
        objects=run(['/usr/bin/pw-dump'])
        node=next((obj for obj in objects if obj.get('info',{}).get('props',{}).get('api.bluez5.address','').upper()==target and obj.get('info',{}).get('props',{}).get('media.class')=='Audio/Sink'),None)
        if node:
            params=node['info'].get('params',{})
            latencies=[entry.get('maxNs',0) for entry in params.get('Latency',[]) if entry.get('maxNs',0)>0]
            if latencies:result['reported_latency_ms']=max(latencies)/1e6
            formats=params.get('Format') or params.get('EnumFormat') or []
            if formats:result.update(audio_sample_rate=formats[0].get('rate'),channels=formats[0].get('channels'))
    except (OSError,RuntimeError,subprocess.SubprocessError):pass
    try:
        setting=subprocess.run(['/usr/bin/wpctl','settings','bluetooth.autoswitch-to-headset-profile'],env=env,capture_output=True,text=True,timeout=2)
        if setting.returncode==0:result['autoswitch']='Value: true' in setting.stdout
    except (OSError,subprocess.SubprocessError):pass
    return result


def connections(sock,adapter=0):
    buffer=bytearray(struct.pack('<HH',adapter,32)+bytes(32*16))
    fcntl.ioctl(sock,0x800448d4,buffer,True)  # HCIGETCONNLIST, read-only.
    count=min(32,struct.unpack_from('<H',buffer,2)[0]);out=[]
    for i in range(count):
        handle,addr,kind,outgoing,state,mode=struct.unpack_from('<H6sBBHI',buffer,4+i*16)
        out.append({'handle':handle,'address':':'.join(f'{b:02X}' for b in addr[::-1]),'kind':kind,'state':state,'mode':mode})
    return out


def radio_state(address):
    sock=socket.socket(socket.AF_BLUETOOTH,socket.SOCK_RAW,socket.BTPROTO_HCI)
    try:
        sock.bind((0,0));conn=next((c for c in connections(sock) if c['address']==(address or '').upper() and c['kind']==1),None)
        if not conn:return {'available':False,'error':'No matching Classic ACL connection'}
        lib=ctypes.CDLL('libbluetooth.so.3',use_errno=True)
        handle=conn['handle'];result={'available':True,'handle':handle,'transport':'Bluetooth Classic BR/EDR','rssi_margin_db':None,'link_quality':None,'tx_power_dbm':None,'afh_channels':None,'supervision_ms':None,'encrypted':bool(conn['mode']&4),'authenticated':bool(conn['mode']&2)}
        for function,key,ctype,extra in [('hci_read_rssi','rssi_margin_db',ctypes.c_int8,[]),('hci_read_link_quality','link_quality',ctypes.c_uint8,[]),('hci_read_transmit_power_level','tx_power_dbm',ctypes.c_int8,[0]),('hci_read_link_supervision_timeout','supervision_ms',ctypes.c_uint16,[])]:
            value=ctype()
            if getattr(lib,function)(sock.fileno(),handle,*extra,ctypes.byref(value),500)==0:
                result[key]=value.value*.625 if key=='supervision_ms' else value.value
        mode=ctypes.c_uint8();channel_map=(ctypes.c_uint8*10)()
        if lib.hci_read_afh_map(sock.fileno(),handle,ctypes.byref(mode),channel_map,500)==0:
            result['afh_channels']=sum((channel_map[i//8]>>(i%8))&1 for i in range(79));result['afh_enabled']=bool(mode.value)
        return result
    finally:sock.close()


class Telemetry:
    def __init__(self,address_provider,on_event):
        self.address_provider=address_provider;self.on_event=on_event;self.lock=threading.RLock();self.stop=threading.Event()
        self.data={'audio':{},'radio':{},'updated':None,'history':[]};self.previous_profile=None
        self.thread=threading.Thread(target=self.run,daemon=True,name='audio-radio-metrics')
    def snapshot(self):
        with self.lock:return copy.deepcopy(self.data)
    def run(self):
        while not self.stop.is_set():
            address=self.address_provider()
            if address:
                result={'updated':time.time()}
                for name,fn in [('audio',audio_state),('radio',radio_state)]:
                    try:result[name]=fn(address)
                    except Exception as exc:result[name]={'available':False,'error':str(exc)[:200]}
                profile=result['audio'].get('profile')
                if profile and self.previous_profile and profile!=self.previous_profile:
                    self.on_event(f'Audio profile changed: {self.previous_profile} → {profile}', 'change')
                self.previous_profile=profile
                with self.lock:
                    history=self.data.get('history',[])
                    history.append({'time':result['updated'],'rssi':result['radio'].get('rssi_margin_db'),'quality':result['radio'].get('link_quality'),'latency':result['audio'].get('reported_latency_ms')})
                    result['history']=history[-120:];self.data=result
            self.stop.wait(3)


class HCIFeed:
    """Optional privileged passive monitor sends headset-only packets here."""
    def __init__(self,root,address_provider):
        self.path=str(Path(root)/'.runtime'/'hci-feed.sock');self.address_provider=address_provider
        self.lock=threading.RLock();self.frames=deque(maxlen=240);self.rates={};self.sequence=0;self.last=None;self.started=time.time()
        self.stop=threading.Event();self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
        try:os.unlink(self.path)
        except FileNotFoundError:pass
        self.sock.bind(self.path);os.chmod(self.path,0o600);self.sock.settimeout(.5)
        self.thread=threading.Thread(target=self.run,daemon=True,name='optional-hci-feed')
    def run(self):
        while not self.stop.is_set():
            try:
                data=json.loads(self.sock.recv(18000))
                if data.get('address')!=(self.address_provider() or '').upper():continue
                raw=bytes.fromhex(data.get('raw',''))
                if len(raw)>4096 or data.get('direction') not in ('TX','RX'):continue
                now=time.time()
                with self.lock:
                    self.last=now
                    if not raw:continue
                    self.sequence+=1
                    frame={'id':self.sequence,'time':data.get('time',now),'direction':data['direction'],'source':'HCI','size':len(raw),'raw':raw.hex(' ').upper(),'label':data.get('label','HCI ACL')[:30],'handle':data.get('handle')}
                    self.frames.append(frame)
                    second=int(now);bucket=self.rates.setdefault(second,{'time':second,'tx_bytes':0,'rx_bytes':0,'tx_packets':0,'rx_packets':0})
                    key='tx' if data['direction']=='TX' else 'rx';bucket[key+'_bytes']+=len(raw);bucket[key+'_packets']+=1
                    for old in list(self.rates):
                        if old<second-120:del self.rates[old]
            except (socket.timeout,json.JSONDecodeError,ValueError,TypeError,KeyError):continue
            except OSError:break
        self.sock.close()
        try:os.unlink(self.path)
        except FileNotFoundError:pass
    def snapshot(self):
        with self.lock:
            now=int(time.time())
            return {'active':self.last is not None and time.time()-self.last<5,'last':self.last,'frames':list(reversed(self.frames))[:120],'rates':[self.rates.get(s,{'time':s,'tx_bytes':0,'rx_bytes':0,'tx_packets':0,'rx_packets':0}) for s in range(now-59,now+1)]}
