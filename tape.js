/* Actual SBC packet audio recorder. AGPL-3.0-or-later. */
let tapeData=null,tapeLoaded=null,tapeEffect='original',tapeBlobUrl=null,tapeBusy=false,tapePolling=false;
const tapeAudio=$('#tapeAudio');tapeAudio.volume=.3;
function drawTapeWave(){
  if(!tapeData?.peaks||$('#studio').hidden)return;
  const surface=studioSurface($('#tapeWave'),100);if(!surface)return;
  const {context:c,width:w}=surface,peaks=tapeEffect==='reverse'?[...tapeData.peaks].reverse():tapeData.peaks;
  peaks.forEach((peak,i)=>{const x=i*w/peaks.length,height=Math.max(1,peak*45);c.fillStyle='#a6d5e8';c.fillRect(x,50-height,Math.max(1,w/peaks.length-1),2*height);});
}
function updateTape(){
  if(!tapeData)return;
  const phase=tapeData.phase,working=['recording','decoding'].includes(phase),audio=nerdData?.telemetry.audio||{},supported=['sbc','sbc_xq'].includes(audio.codec)&&!audio.call_mode;
  $('#tapeConnection').textContent=tapeData.hci_active?`HCI LIVE / ${(audio.codec||'SBC').toUpperCase()}`:'HCI HELPER OFFLINE';
  $('#tapeNeedHelper').hidden=tapeData.hci_active;
  $('#tapeRecord').disabled=tapeBusy||working||!tapeData.hci_active||!supported;
  $('#tapeStop').disabled=phase!=='recording'||tapeBusy;
  $('#tapeLength').disabled=working||tapeBusy;
  $('#tapePackets').textContent=tapeData.packet_count.toLocaleString();
  const receipt=tapeData.receipt;
  $('#tapeFrames').textContent=receipt?receipt.sbc_frames.toLocaleString():'—';
  $('#tapeFormat').textContent=receipt?`${receipt.sample_rate/1000} kHz / ${receipt.channels} ch`:'—';
  $('#tapeBitrate').textContent=receipt?`${receipt.encoded_bitrate_kbps.toFixed(0)} kb/s`:'—';
  $('#tapeGaps').textContent=receipt?receipt.rtp_capture_gaps:'—';
  $('#tapeStatus').textContent=phase==='recording'?`Recording actual packets · ${tapeData.remaining.toFixed(1)}s remaining`:
    phase==='decoding'?'Reassembling RTP and decoding the captured SBC stream…':phase==='ready'?`${receipt.duration.toFixed(2)} seconds of real decoded audio`:
    phase==='error'?tapeData.error:!tapeData.hci_active?'Start the HCI helper, then play audio on your XM4.':!supported?'Choose an A2DP SBC/SBC-XQ profile to record.':'Ready. Play a track, voice clip, or other audio through the XM4.';
  $('#tapeProgress').style.width=phase==='recording'?`${100*(1-tapeData.remaining/Number($('#tapeLength').value))}%`:phase==='ready'?'100%':'0%';
  if(receipt)$('#tapeProof').textContent=`Reconstructed from ${receipt.rtp_packets.toLocaleString()} media packets and ${receipt.sbc_frames.toLocaleString()} SBC frames. Encoded SHA-256: ${receipt.encoded_sha256.slice(0,24)}…${receipt.rtp_capture_gaps?' Capture gaps may cause discontinuities.':' No RTP sequence gaps in this capture.'}`;
  $('#tapeResult').hidden=phase!=='ready';drawTapeWave();
}
async function loadTapeAudio(effect='original'){
  if(!tapeData?.receipt)return;
  const key=tapeData.record_id;
  try{
    const response=await fetch(`/api/tape/${key}/${effect}.wav`);if(!response.ok)throw new Error('Recorded audio is unavailable. Record another clip.');
    const blob=await response.blob();tapeAudio.pause();if(tapeBlobUrl)URL.revokeObjectURL(tapeBlobUrl);
    tapeBlobUrl=URL.createObjectURL(blob);tapeAudio.src=tapeBlobUrl;tapeAudio.volume=studioLevel();tapeLoaded=key;tapeEffect=effect;
    $('#tapeWavDownload').href=tapeBlobUrl;$('#tapeWavDownload').download=`hush-real-packet-audio-${effect}.wav`;
    $('#tapeEncodedDownload').href=`/api/tape/${key}/encoded.sbc`;$('#tapeReceiptDownload').href=`/api/tape/${key}/receipt.json`;$('#tapeRawDownload').href=`/api/tape/${key}/packets.json`;
    $$('[data-tape-effect]').forEach(button=>{const active=button.dataset.tapeEffect===effect;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});drawTapeWave();
  }catch(error){showToast(error.message,true);}
}
async function refreshTape(){
  if(tapePolling)return;tapePolling=true;
  try{const response=await fetch('/api/tape/state',{signal:AbortSignal.timeout(5000)});if(!response.ok)return;tapeData=await response.json();updateTape();if(tapeData.phase==='ready'&&tapeData.record_id!==tapeLoaded)await loadTapeAudio('original');}
  catch(error){$('#tapeStatus').textContent='Local packet recorder is offline.';}
  finally{tapePolling=false;}
}
async function controlTape(action){
  if(tapeBusy)return;tapeBusy=true;updateTape();
  if(action==='start'){stopStudioLive();studioAudio.pause();tapeAudio.pause();}
  try{const response=await fetch(`/api/tape/${action}`,{method:'POST',headers:{'Content-Type':'application/json','X-Hush-Token':token},body:JSON.stringify({duration:Number($('#tapeLength').value)})});const result=await response.json();if(!response.ok||!result.ok)throw new Error(result.error||'Packet recording failed.');tapeData=result;updateTape();}
  catch(error){showToast(error.message,true);}finally{tapeBusy=false;updateTape();}
}
$('#tapeRecord').addEventListener('click',()=>controlTape('start'));$('#tapeStop').addEventListener('click',()=>controlTape('stop'));
$$('[data-tape-effect]').forEach(button=>button.addEventListener('click',()=>loadTapeAudio(button.dataset.tapeEffect)));
$('#studioVolume').addEventListener('input',()=>{tapeAudio.volume=studioLevel();});
tapeAudio.addEventListener('play',()=>{stopStudioLive();studioAudio.pause();});
studioAudio.addEventListener('play',()=>tapeAudio.pause());
window.addEventListener('resize',drawTapeWave);
window.addEventListener('pagehide',()=>{tapeAudio.pause();if(tapeBlobUrl)URL.revokeObjectURL(tapeBlobUrl);});
$('.studio-instrument-details').addEventListener('toggle',event=>{if(!event.currentTarget.open){stopStudioLive();studioAudio.pause();}else animateStudio();});
setInterval(()=>{if(!$('#studio').hidden||tapeData?.phase==='recording'||tapeData?.phase==='decoding')refreshTape();},700);
refreshTape();
