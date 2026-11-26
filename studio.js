/* Packet Studio — a byte-driven instrument. AGPL-3.0-or-later. */
let studioPreset='garden', studioBusy=false, studioSaved=null, studioImported=null, studioRender=null;
let studioWavUrl=null, studioAnimation=0, studioSelectedEvent=-1, studioLive=null;
const studioTitles={garden:'The garden is talking.',modem:'Dreams of a dial-up moon.',drums:'A rhythm in the handshake.'};
const studioAudio=$('#studioAudio');
studioAudio.volume=.3;

function studioFrames(){
  const source=$('#studioSource').value;
  if(source==='saved')return studioSaved||[];
  if(source==='imported')return studioImported||[];
  if(source==='bench')return typeof filteredFrames==='function'?filteredFrames():[];
  return source==='HCI'?(nerdData?.hci.frames||[]):(nerdData?.wire.frames||[]);
}
function studioLevel(){return Number($('#studioVolume').value)/100;}
function studioSurface(canvas,height){
  const width=canvas.clientWidth,scale=window.devicePixelRatio||1;
  if(!width)return null;
  canvas.width=width*scale;canvas.height=height*scale;
  const context=canvas.getContext('2d');context.scale(scale,scale);
  return {context,width,height};
}
function drawStudioConstellation(){
  if($('#studio').hidden)return;
  const surface=studioSurface($('#studioConstellation'),$('#studioConstellation').clientHeight||300);if(!surface)return;
  const {context:c,width:w,height:h}=surface,cx=w/2,cy=h/2,r=Math.min(w,h)*.29;
  const frames=studioFrames().slice(0,40).reverse();
  [1,1.28,1.55].forEach((scale,i)=>{c.beginPath();c.arc(cx,cy,r*scale,0,Math.PI*2);c.strokeStyle=i===0?'#6a8b4b50':'#48643a38';c.lineWidth=1;c.stroke();});
  c.strokeStyle='#7c9d5950';c.lineWidth=1;c.beginPath();
  const points=frames.map((frame,i)=>{const bytes=frame.raw?.match(/[0-9a-f]{2}/gi)||['00'];const value=parseInt(bytes[Math.min(7,bytes.length-1)],16);const angle=(i/Math.max(1,frames.length))*Math.PI*2-Math.PI/2;const radius=r*(.64+.45*value/255);return {x:cx+Math.cos(angle)*radius,y:cy+Math.sin(angle)*radius,color:frame.direction==='TX'?'#d1f6a1':'#9ac8e9',ack:frame.label==='ACK'};});
  points.forEach((p,i)=>{i?c.lineTo(p.x,p.y):c.moveTo(p.x,p.y);});c.stroke();
  points.forEach(p=>{c.beginPath();c.arc(p.x,p.y,p.ack?2:3.8,0,Math.PI*2);c.fillStyle=p.color;c.shadowColor=p.color;c.shadowBlur=p.ack?0:10;c.fill();});c.shadowBlur=0;
  const pulse=studioLive||!studioAudio.paused?1+.07*Math.sin(performance.now()/400):1;
  const glow=c.createRadialGradient(cx,cy,0,cx,cy,r*.55);glow.addColorStop(0,'#c7fa8a26');glow.addColorStop(1,'#c7fa8a00');c.fillStyle=glow;c.beginPath();c.arc(cx,cy,r*.6,0,Math.PI*2);c.fill();
  c.fillStyle='#ccefad';c.font=`${26*pulse}px monospace`;c.textAlign='center';c.fillText('⌁',cx,cy+9);
  c.fillStyle='#769963';c.font='10px monospace';c.fillText(studioLive?'LISTENING':studioRender?'SCORED':'WIRE TO WONDER',cx,cy+31);
}
function drawStudioWave(){
  if(!studioRender||$('#studio').hidden)return;
  const surface=studioSurface($('#studioWaveform'),80);if(!surface)return;
  const {context:c,width:w}=surface,peaks=studioRender.peaks,progress=(studioAudio.currentTime||0)/studioRender.score.duration;
  peaks.forEach((peak,i)=>{const x=i*w/peaks.length,half=Math.max(1,peak*49);c.fillStyle=i/peaks.length<progress?'#d3fba6':'#496737';c.fillRect(x,40-half,Math.max(1,w/peaks.length-1),half*2);});
  c.fillStyle='#e3ffd0';c.fillRect(progress*w,5,1,70);
}
function drawStudioScore(){
  if(!studioRender||$('#studio').hidden)return;
  const surface=studioSurface($('#studioScore'),180);if(!surface)return;
  const {context:c,width:w,height:h}=surface,events=studioRender.score.events,duration=studioRender.score.duration,pad=30;
  c.font='10px monospace';c.fillStyle='#73935f';c.strokeStyle='#2c4120';c.lineWidth=1;
  for(let tick=0;tick<=duration;tick+=duration/4){const x=pad+(w-pad-8)*tick/duration;c.beginPath();c.moveTo(x,10);c.lineTo(x,h-23);c.stroke();c.fillText(`${tick}s`,Math.min(w-21,x),h-8);}
  if(studioRender.score.preset==='garden')[48,60,72,84].forEach(midi=>{const y=140-(midi-48)*3;c.fillText(`C${midi/12-1}`,3,y+4);c.beginPath();c.moveTo(pad,y);c.lineTo(w,y);c.stroke();});
  else [['FSK',55],['KICK',85],['CLAP',115],['ACK',150]].forEach(([label,y])=>{c.fillText(label,2,y+4);c.beginPath();c.moveTo(pad,y);c.lineTo(w,y);c.stroke();});
  events.forEach((event,i)=>{const x=pad+(w-pad-8)*event.time/duration,y=event.voice==='hat'?150:event.voice==='bell'?140-(event.midi-48)*3:({fsk:55,kick:85,clap:115}[event.voice]||85);const length=Math.max(event.voice==='hat'?2:4,(w-pad-8)*event.duration/duration*.45);c.fillStyle=event.voice==='hat'?'#728065':event.direction==='TX'?'#c9f29b':'#91c1e4';if(i===studioSelectedEvent){c.shadowColor='#e2ffd2';c.shadowBlur=9;}c.fillRect(x,y,length,event.voice==='hat'?3:6);c.shadowBlur=0;});
  const x=pad+(w-pad-8)*(studioAudio.currentTime||0)/duration;c.strokeStyle='#edffdd';c.beginPath();c.moveTo(x,10);c.lineTo(x,h-23);c.stroke();
}
function studioClock(value){const seconds=Math.max(0,Math.floor(value||0));return `${Math.floor(seconds/60).toString().padStart(2,'0')}:${(seconds%60).toString().padStart(2,'0')}`;}
function animateStudio(){
  cancelAnimationFrame(studioAnimation);
  if($('#studio').hidden)return;
  drawStudioConstellation();drawStudioWave();drawStudioScore();
  $('#studioPlayTime').textContent=studioClock(studioAudio.currentTime);
  if(studioLive||!studioAudio.paused)studioAnimation=requestAnimationFrame(animateStudio);
}
function studioSelectEvent(index){
  if(!studioRender)return;
  studioSelectedEvent=index;const event=studioRender.score.events[index];
  const notes=['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'];
  const pitch=event.voice==='bell'?`${notes[event.midi%12]}${Math.floor(event.midi/12)-1} / ${event.frequency.toFixed(1)} Hz`:({hat:'soft ACK hat',fsk:'byte-driven FSK / 560 & 900 Hz',kick:'kick / 128 to 48 Hz sweep',clap:'seeded noise clap'}[event.voice]);
  $('#studioEventDetail').textContent=`Frame ${event.frame_id} · ${event.direction} ${event.label} · byte 0x${event.byte.toString(16).padStart(2,'0').toUpperCase()} · ${pitch} · ${event.time.toFixed(2)}s · ${event.pan<0?'left':'right'}`;
  $$('#studioNoteList button').forEach(button=>button.classList.toggle('selected',Number(button.dataset.event)===index));drawStudioScore();
}
function updateStudio(){
  const frames=studioFrames(),source=$('#studioSource').value,liveSource=['MDR','HCI'].includes(source),count=Math.min(96,frames.length);
  $('#studioFrameCount').textContent=frames.length;
  $('#studioSourceBadge').textContent={MDR:'SONY / MDR',HCI:'BLUETOOTH / HCI',bench:'BENCH / SELECTION',saved:'SAVED / REAL CAPTURE',imported:'IMPORTED / CAPTURE'}[source];
  $('#studioSourceInfo').textContent=frames.length?`${count} ${source==='saved'?'saved':source==='imported'?'imported':liveSource?'live':'selected'} packets ready · ${frames.slice(0,96).reduce((sum,frame)=>sum+(frame.raw?.replace(/\s/g,'').length||0)/2,0).toLocaleString()} wire bytes${frames.length>96?' · using the newest 96':''}`:source==='HCI'?'Start the optional HCI helper in Nerd to capture this audio/control stream.':'No captured packets yet. Use a saved real capture or import your JSON export.';
  $('#studioCompose').disabled=studioBusy||!frames.length;
  $('#studioCompose').textContent=studioBusy?'Scoring your packets…':`Compose ${$('#studioLength').value} seconds`;
  $('#studioListenLive').disabled=studioBusy||(!studioLive&&(!liveSource||!frames.length));
  $('#studioLiveLight').classList.toggle('on',Boolean(studioLive));
  $$('[data-voice],#studioSource,#studioLength,#studioTiming,#studioTempo,#studioUseSaved,#studioImport').forEach(el=>{el.disabled=studioBusy;});
  $('#studioSource option[value=saved]').disabled=!studioSaved;$('#studioSource option[value=imported]').disabled=!studioImported;
  $('#studioTempo').disabled=studioBusy||$('#studioTiming').value==='wire';
  if(!$('#studio').hidden)drawStudioConstellation();
}
async function loadSavedStudio(){
  try{const response=await fetch('/api/sample-capture');if(!response.ok)throw new Error('Saved capture unavailable.');const data=await response.json();studioSaved=data.frames;$('#studioSource option[value=saved]').disabled=false;$('#studioSource').value='saved';stopStudioLive();updateStudio();showToast('Loaded a real capture recorded from your XM4');}catch(error){showToast(error.message,true);}
}
async function composeStudio(){
  if(studioBusy)return;
  const frames=studioFrames().slice(0,96).map(frame=>({id:frame.id,time:frame.time,direction:frame.direction,source:frame.source,raw:frame.raw}));
  if(!frames.length)return;
  const request={frames,preset:studioPreset,duration:Number($('#studioLength').value),tempo:Number($('#studioTempo').value),timing:$('#studioTiming').value};
  studioBusy=true;stopStudioLive();updateStudio();
  try{
    if(!token){const state=await (await fetch('/api/state')).json();token=state.token;}
    const response=await fetch('/api/sonify',{method:'POST',headers:{'Content-Type':'application/json','X-Hush-Token':token},body:JSON.stringify(request),signal:AbortSignal.timeout(45000)});
    const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.error||'Could not render this capture.');
    const audioResponse=await fetch(data.wav_url);if(!audioResponse.ok)throw new Error('The audio render expired. Compose again.');
    const blob=await audioResponse.blob();studioAudio.pause();
    if(studioWavUrl)URL.revokeObjectURL(studioWavUrl);
    studioWavUrl=URL.createObjectURL(blob);studioAudio.src=studioWavUrl;studioAudio.volume=studioLevel();studioRender=data;studioSelectedEvent=-1;
    $('#studioResult').hidden=false;$('#studioTrackTitle').textContent=studioTitles[data.score.preset];
    $('#studioTrackInfo').textContent=`${data.packet_count} real packets · ${data.score.events.length} sounds · ${data.score.duration} seconds · ${data.score.timing==='wire'?'original arrival timing':`${data.score.tempo} BPM`}${data.score.preset==='garden'?' / C major pentatonic':data.score.preset==='modem'?' / byte-driven FSK':' / percussive voices'}`;
    $('#studioDuration').textContent=studioClock(data.score.duration);$('#studioDownload').href=studioWavUrl;$('#studioDownload').download=`hush-${data.score.preset}-${data.score.duration}s.wav`;
    $('#studioScoreDownload').href=data.score_url;$('#studioScoreDownload').download=`hush-${data.score.preset}.score.json`;
    const seen=new Set(),entries=[];data.score.events.forEach((event,index)=>{if(seen.has(event.frame_id)||entries.length>=12)return;seen.add(event.frame_id);const button=document.createElement('button');button.className=event.direction.toLowerCase();button.dataset.event=index;button.textContent=`${event.direction} #${event.frame_id} · ${event.label}`;button.addEventListener('click',()=>studioSelectEvent(index));entries.push(button);});
    $('#studioNoteList').replaceChildren(...entries);if(data.score.events.length)studioSelectEvent(0);animateStudio();
    showToast('Your packet composition is ready. Press Play to listen.');
  }catch(error){showToast(error.message,true);}finally{studioBusy=false;updateStudio();}
}
function stopStudioLive(){
  if(studioLive){studioLive.context.close().catch(()=>{});studioLive=null;}
  $('#studioListenLive').textContent='Listen live';$('#studioListenLive').setAttribute('aria-pressed','false');$('#studioLiveLight').classList.remove('on');
}
async function startStudioLive(){
  if(studioLive){stopStudioLive();updateStudio();return;}
  try{
    const AudioContext=window.AudioContext||window.webkitAudioContext;if(!AudioContext)throw new Error('Live synthesis is unavailable in this browser. Render a WAV instead.');
    studioAudio.pause();const context=new AudioContext(),gain=context.createGain(),compressor=context.createDynamicsCompressor();
    gain.gain.value=studioLevel()*.22;compressor.threshold.value=-18;compressor.ratio.value=5;gain.connect(compressor);compressor.connect(context.destination);await context.resume();
    studioLive={context,gain,lastId:Math.max(0,...studioFrames().map(frame=>Number(frame.id)||0)),source:$('#studioSource').value};
    $('#studioListenLive').textContent='Stop live instrument';$('#studioListenLive').setAttribute('aria-pressed','true');updateStudio();animateStudio();
  }catch(error){showToast(error.message,true);}
}
async function playLivePacket(frame,offset){
  const live=studioLive;if(!live)return;
  try{
    const raw=new Uint8Array((frame.raw.match(/[0-9a-f]{2}/gi)||[]).map(value=>parseInt(value,16)));if(!raw.length)return;
    const hash=new Uint8Array(await crypto.subtle.digest('SHA-256',raw));if(studioLive!==live)return;
    const seed=((hash[0]*0x1000000)+(hash[1]<<16)+(hash[2]<<8)+hash[3])>>>0;
    const byte=parseInt(frame.payload?.split(' ')[0]||'00',16),degree=(byte+(seed&7))%5;
    const midi=(frame.direction==='TX'?48:60)+[0,2,4,7,9][degree],frequency=440*2**((midi-69)/12),now=live.context.currentTime+.035+offset;
    const envelope=live.context.createGain(),pan=live.context.createStereoPanner();pan.pan.value=frame.direction==='TX'?-.58:.58;envelope.connect(pan);pan.connect(live.gain);
    const oscillator=live.context.createOscillator();oscillator.type=studioPreset==='modem'?'triangle':'sine';
    const ack=frame.label==='ACK',duration=ack?.055:studioPreset==='garden'?.8:.2;
    oscillator.frequency.setValueAtTime(ack?2200:studioPreset==='drums'?(frame.direction==='TX'?130:650):studioPreset==='modem'?(byte&1?900:560):frequency,now);
    if(studioPreset==='drums'&&!ack)oscillator.frequency.exponentialRampToValueAtTime(frame.direction==='TX'?45:170,now+duration);
    envelope.gain.setValueAtTime(0,now);envelope.gain.linearRampToValueAtTime(ack?.08:.3,now+.004);envelope.gain.exponentialRampToValueAtTime(.0001,now+duration);
    oscillator.connect(envelope);oscillator.start(now);oscillator.stop(now+duration+.02);oscillator.onended=()=>{oscillator.disconnect();envelope.disconnect();pan.disconnect();};
  }catch(error){/* A stopped context can race an incoming poll. */}
}
function packetStudioIngest(data){
  updateStudio();
  if(!studioLive)return;
  const frames=(studioLive.source==='HCI'?data.hci.frames:data.wire.frames).filter(frame=>Number(frame.id)>studioLive.lastId).reverse();
  if(frames.length){studioLive.lastId=Math.max(...frames.map(frame=>Number(frame.id)));frames.slice(-16).forEach((frame,index)=>playLivePacket(frame,index*.035));}
}
function setStudioActive(active){
  if(!active){stopStudioLive();studioAudio.pause();cancelAnimationFrame(studioAnimation);}
  else {updateStudio();animateStudio();}
}
$$('[data-voice]').forEach(button=>button.addEventListener('click',()=>{studioPreset=button.dataset.voice;$$('[data-voice]').forEach(item=>{item.classList.toggle('selected',item===button);item.setAttribute('aria-pressed',String(item===button));});}));
$('#studioCompose').addEventListener('click',composeStudio);$('#studioUseSaved').addEventListener('click',loadSavedStudio);$('#studioListenLive').addEventListener('click',startStudioLive);
['studioSource','studioLength','studioTiming'].forEach(id=>$('#'+id).addEventListener('change',()=>{if(id==='studioSource')stopStudioLive();updateStudio();}));
$('#studioTempo').addEventListener('input',()=>{$('#studioTempoValue').textContent=$('#studioTempo').value;fillSlider($('#studioTempo'));});
$('#studioVolume').addEventListener('input',()=>{const level=studioLevel();$('#studioVolumeValue').textContent=`${$('#studioVolume').value}%`;studioAudio.volume=level;if(studioLive)studioLive.gain.gain.setTargetAtTime(level*.22,studioLive.context.currentTime,.02);fillSlider($('#studioVolume'));});
$('#studioImport').addEventListener('change',async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>1048576)throw new Error('Choose a capture JSON smaller than 1 MiB.');const data=JSON.parse(await file.text()),frames=Array.isArray(data)?data:data.packets||data.frames;if(!Array.isArray(frames)||!frames.length)throw new Error('No packet frames in that file.');if(frames.slice(0,96).some(frame=>!frame||typeof frame.raw!=='string'||!frame.raw.trim()||frame.raw.length>12288||!/^[0-9a-f\s]+$/i.test(frame.raw)||!['TX','RX'].includes(frame.direction)||(frame.time!=null&&!Number.isFinite(frame.time))))throw new Error('Expected packet objects with hex bytes, TX/RX direction, and numeric timestamps.');studioImported=frames.slice(0,96);$('#studioSource option[value=imported]').disabled=false;$('#studioSource').value='imported';stopStudioLive();updateStudio();showToast(`Loaded ${studioImported.length} captured packets`);}catch(error){showToast(error.message,true);}finally{event.target.value='';}});
$('#studioPlay').addEventListener('click',async()=>{if(!studioRender)return;stopStudioLive();try{studioAudio.paused?await studioAudio.play():studioAudio.pause();}catch(error){showToast('Use the audio player below to start playback.',true);}});
studioAudio.addEventListener('play',()=>{stopStudioLive();$('#studioPlay').textContent='Ⅱ';$('#studioPlay').setAttribute('aria-label','Pause composition');animateStudio();});
studioAudio.addEventListener('pause',()=>{$('#studioPlay').textContent='▶';$('#studioPlay').setAttribute('aria-label','Play composition');animateStudio();});
studioAudio.addEventListener('ended',()=>{$('#studioPlay').textContent='▶';$('#studioPlay').setAttribute('aria-label','Play composition');animateStudio();});
studioAudio.addEventListener('seeked',animateStudio);
$('#studioScore').addEventListener('click',event=>{if(!studioRender)return;const bounds=event.currentTarget.getBoundingClientRect(),time=Math.max(0,(event.clientX-bounds.left-30)/(bounds.width-38))*studioRender.score.duration;let best=0;studioRender.score.events.forEach((item,i)=>{if(Math.abs(item.time-time)<Math.abs(studioRender.score.events[best].time-time))best=i;});studioSelectEvent(best);});
window.addEventListener('resize',()=>{if(!$('#studio').hidden){drawStudioConstellation();drawStudioWave();drawStudioScore();}});
window.addEventListener('pagehide',()=>{stopStudioLive();studioAudio.pause();if(studioWavUrl)URL.revokeObjectURL(studioWavUrl);});
fillSlider($('#studioTempo'));fillSlider($('#studioVolume'));updateStudio();
