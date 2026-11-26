"""Reconstruct real A2DP SBC audio from this headset's HCI ACL TX packets.
AGPL-3.0-or-later. No microphone or PipeWire loopback recording is used.
"""
from array import array
from collections import defaultdict
import copy
import hashlib
import io
import json
import secrets
import shutil
import struct
import subprocess
import sys
import threading
import time
import wave


def sbc_info(data):
    if len(data)<4 or data[0]!=0x9c:
        raise ValueError('Missing SBC sync word')
    flags,bitpool=data[1],data[2]
    rate=(16000,32000,44100,48000)[flags>>6]
    blocks=(4,8,12,16)[(flags>>4)&3]
    mode=(flags>>2)&3;channels=1 if mode==0 else 2;subbands=8 if flags&1 else 4
    if not 2<=bitpool<=min(250,subbands*(16 if mode in (0,1) else 32)):
        raise ValueError('Invalid SBC bitpool')
    bits=blocks*bitpool*(channels if mode in (0,1) else 1)+(subbands if mode==3 else 0)
    size=4+(4*subbands*channels)//8+(bits+7)//8
    return {'sample_rate':rate,'channels':channels,'blocks':blocks,'subbands':subbands,
            'mode':('mono','dual channel','stereo','joint stereo')[mode],'bitpool':bitpool,
            'frame_bytes':size,'samples':blocks*subbands}


class A2dpDecoder:
    def __init__(self):
        self.partial={};self.fragments={};self.streams={};self.incomplete=0;self.invalid=0

    def feed(self,packet):
        if packet.get('direction')!='TX' or packet.get('label')!='HCI ACL':return
        raw=bytes.fromhex(packet['raw'])
        if len(raw)<8:return
        flags,length=struct.unpack_from('<HH',raw);handle=flags&0xfff;pb=(flags>>12)&3
        if length!=len(raw)-4:self.invalid+=1;return
        data=raw[4:]
        if pb in (0,2,3):
            if handle in self.partial:self.incomplete+=1
            self.partial[handle]=bytearray(data)
        elif pb==1 and handle in self.partial:self.partial[handle].extend(data)
        else:return
        buf=self.partial[handle]
        if len(buf)>65539:self.partial.pop(handle,None);self.invalid+=1;return
        while len(buf)>=4:
            size,cid=struct.unpack_from('<HH',buf);expected=size+4
            if len(buf)<expected:return
            payload=bytes(buf[4:expected]);del buf[:expected]
            self.media(handle,cid,payload,packet)
        if not buf:self.partial.pop(handle,None)

    def media(self,handle,cid,data,packet):
        if len(data)<13 or data[0]>>6!=2:return
        offset=12+4*(data[0]&15)
        if offset>len(data):return
        if data[0]&0x10:
            if len(data)<offset+4:return
            offset+=4+4*int.from_bytes(data[offset+2:offset+4],'big')
        end=len(data)
        if data[0]&0x20:
            padding=data[-1]
            if padding<1 or padding>end-offset:return
            end-=padding
        if offset>=end:return
        sequence=int.from_bytes(data[2:4],'big');ssrc=int.from_bytes(data[8:12],'big')
        key=(handle,cid,ssrc);header=data[offset];payload=data[offset+1:end]
        if header&0x80:
            if header&0x40:self.fragments[key]=bytearray()
            if key not in self.fragments:return
            self.fragments[key].extend(payload)
            if len(self.fragments[key])>4096:self.fragments.pop(key,None);return
            if not header&0x20:return
            payload=bytes(self.fragments.pop(key));expected_frames=1
        else:
            expected_frames=header&15
            if not expected_frames or header&0x70:return
        try:
            frames=[];position=0;info=None
            for _ in range(expected_frames):
                current=sbc_info(payload[position:]);size=current['frame_bytes']
                if position+size>len(payload):raise ValueError('Truncated SBC frame')
                if info and (current['sample_rate'],current['channels'])!=(info['sample_rate'],info['channels']):
                    raise ValueError('SBC format changed in a packet')
                info=current;frames.append(payload[position:position+size]);position+=size
            if position!=len(payload):return
        except ValueError:return
        stream=self.streams.setdefault(key,{'encoded':bytearray(),'info':info,'rtp_packets':0,'sbc_frames':0,'samples':0,'last_sequence':None,'gaps':0,'receipts':[]})
        if (info['sample_rate'],info['channels'])!=(stream['info']['sample_rate'],stream['info']['channels']):return
        previous=stream['last_sequence']
        if previous is not None:
            delta=(sequence-previous)&65535
            if delta==0 or delta>=32768:return
            if delta>1:stream['gaps']+=delta-1
        if stream['samples']/info['sample_rate']>32:return
        stream['last_sequence']=sequence;stream['rtp_packets']+=1;stream['sbc_frames']+=len(frames)
        stream['samples']+=sum(sbc_info(frame)['samples'] for frame in frames)
        stream['encoded'].extend(b''.join(frames))
        stream['receipts'].append({'hci_frame_id':packet.get('id'),'time':packet.get('time'),'rtp_sequence':sequence,
                                   'cid':f'0x{cid:04X}','sbc_frames':len(frames),'payload_sha256':hashlib.sha256(payload).hexdigest()})

    def result(self):
        if not self.streams:raise ValueError('No complete SBC media frames found. Play audio over A2DP using SBC/SBC-XQ and try again.')
        stream=max(self.streams.values(),key=lambda stream:stream['sbc_frames'])
        encoded=bytes(stream['encoded']);info=stream['info']
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:raise ValueError('Install FFmpeg with its SBC decoder to play these packets.')
        process=subprocess.run([ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-f','sbc','-i','pipe:0',
                                '-t','35','-f','s16le','-acodec','pcm_s16le','pipe:1'],input=encoded,capture_output=True,timeout=20)
        if process.returncode or not process.stdout:
            raise ValueError('FFmpeg could not decode the captured SBC stream: '+process.stderr.decode('utf-8','replace')[:180])
        pcm=process.stdout
        if len(pcm)%(2*info['channels']):raise ValueError('Incomplete decoded PCM sample')
        wav=pcm_wave(pcm,info['sample_rate'],info['channels'])
        duration=len(pcm)/(2*info['channels']*info['sample_rate'])
        receipt={'kind':'Real Bluetooth audio reconstructed from HCI ACL TX / L2CAP / RTP / SBC',
                 **info,'duration':duration,'rtp_packets':stream['rtp_packets'],'sbc_frames':stream['sbc_frames'],
                 'rtp_capture_gaps':stream['gaps'],'incomplete_l2cap':self.incomplete+len(self.partial),
                 'invalid_acl_packets':self.invalid,'encoded_bytes':len(encoded),
                 'encoded_bitrate_kbps':len(encoded)*8/duration/1000,
                 'encoded_sha256':hashlib.sha256(encoded).hexdigest(),'wav_sha256':hashlib.sha256(wav).hexdigest(),
                 'decode_warnings':process.stderr.decode('utf-8','replace')[:1000],
                 'note':'This is decoded transmitted SBC audio, before the headphone DSP/EQ. RTP gaps are capture gaps, not measured RF loss; missing audio is not invented.',
                 'packets':stream['receipts']}
        return encoded,pcm,wav,receipt


def pcm_wave(pcm,rate,channels):
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as wav:
        wav.setnchannels(channels);wav.setsampwidth(2);wav.setframerate(rate);wav.writeframes(pcm)
    return buffer.getvalue()


def pcm_effect(pcm,rate,channels,effect):
    if effect=='original':return pcm
    values=array('h');values.frombytes(pcm)
    if sys.byteorder!='little':values.byteswap()
    if effect=='reverse':
        output=array('h')
        for i in range(len(values)-channels,-1,-channels):output.extend(values[i:i+channels])
    elif effect=='orbit':
        output=array('h',values);delay=int(rate*.23)*channels
        for i in range(len(values)):
            reflected=values[i-delay+(1-2*(i%2) if channels==2 else 0)] if i>=delay else 0
            output[i]=round(max(-32767,min(32767,values[i]*.82+reflected*.18)))
    else:raise ValueError('Unknown audio effect')
    if sys.byteorder!='little':output.byteswap()
    return output.tobytes()


def waveform(pcm,channels):
    values=array('h');values.frombytes(pcm)
    if sys.byteorder!='little':values.byteswap()
    step=max(channels,len(values)//384)
    return [round(max(map(abs,values[i:i+step]),default=0)/32768,4) for i in range(0,len(values),step)][:384]


class PacketTape:
    def __init__(self,hci_provider,audio_provider):
        self.hci_provider=hci_provider;self.audio_provider=audio_provider;self.lock=threading.RLock()
        self.phase='idle';self.error=None;self.packets=[];self.bytes=0;self.started=None;self.deadline=None
        self.duration=10;self.key=None;self.clips={};self.timer=None

    def start(self,duration=10):
        if isinstance(duration,bool) or duration not in (5,10,20):raise ValueError('Choose a 5, 10 or 20 second recording.')
        with self.lock:
            if self.phase in ('recording','decoding'):raise ValueError('A packet recording is already in progress.')
            if not self.hci_provider()['active']:raise ValueError('Start the passive HCI helper first. Its command is in Nerd / HCI capture.')
            audio=self.audio_provider()
            if audio.get('codec') not in ('sbc','sbc_xq') or audio.get('call_mode'):
                raise ValueError('Real packet playback currently supports A2DP SBC/SBC-XQ. Current codec: '+str(audio.get('codec')))
            self.phase='recording';self.error=None;self.packets=[];self.bytes=0;self.started=time.time();self.deadline=time.monotonic()+duration
            self.duration=duration;self.key=secrets.token_hex(16)
            self.timer=threading.Timer(duration,self.finish);self.timer.daemon=True;self.timer.start()
        return self.snapshot()

    def feed(self,packet):
        with self.lock:
            if self.phase!='recording' or packet.get('direction')!='TX' or packet.get('label')!='HCI ACL':return
            size=packet['size']
            if self.bytes+size>8*1024*1024 or len(self.packets)>=16000:return
            self.packets.append(copy.copy(packet));self.bytes+=size

    def finish(self):
        with self.lock:
            if self.phase!='recording':return self.snapshot()
            self.phase='decoding';packets=list(self.packets);key=self.key
            if self.timer:self.timer.cancel()
        def decode():
            try:
                decoder=A2dpDecoder()
                for packet in packets:decoder.feed(packet)
                encoded,pcm,wav,receipt=decoder.result()
                receipt.update(hci_packet_count=len(packets),hci_bytes=sum(packet['size'] for packet in packets))
                clip={'encoded':encoded,'pcm':pcm,'original':wav,'receipt':receipt,'packets':packets,'peaks':waveform(pcm,receipt['channels'])}
                with self.lock:
                    while len(self.clips)>=2:del self.clips[next(iter(self.clips))]
                    self.clips[key]=clip;self.phase='ready';self.packets=[]
            except Exception as exc:
                with self.lock:self.phase='error';self.error=str(exc)[:300];self.packets=[]
        threading.Thread(target=decode,daemon=True,name='sbc-packet-decoder').start()
        return self.snapshot()

    def snapshot(self):
        with self.lock:
            result={'phase':self.phase,'error':self.error,'packet_count':len(self.packets),'bytes':self.bytes,
                    'remaining':max(0,self.deadline-time.monotonic()) if self.phase=='recording' else 0,
                    'hci_active':self.hci_provider()['active'],'record_id':self.key}
            clip=self.clips.get(self.key)
            if clip:
                result.update(receipt={k:v for k,v in clip['receipt'].items() if k!='packets'},peaks=clip['peaks'],
                              packet_count=clip['receipt']['hci_packet_count'])
            return result

    def resource(self,key,name):
        with self.lock:
            clip=self.clips.get(key)
            if clip is None:return None
            if name=='encoded.sbc':return bytes(clip['encoded']),'audio/x-sbc'
            if name=='receipt.json':return json.dumps(clip['receipt'],indent=2).encode(),'application/json'
            if name=='packets.json':return json.dumps({'source':'actual headset HCI ACL TX','packets':clip['packets']}).encode(),'application/json'
            effect=name.removesuffix('.wav')
            if name.endswith('.wav') and effect in ('original','reverse','orbit'):
                if effect not in clip:
                    info=clip['receipt'];clip[effect]=pcm_wave(pcm_effect(clip['pcm'],info['sample_rate'],info['channels'],effect),info['sample_rate'],info['channels'])
                return clip[effect],'audio/wav'
            return None
