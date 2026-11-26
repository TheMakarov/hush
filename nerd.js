/* Exact packet inspection and honest radio/audio metrics. AGPL-3.0-or-later. */
let nerdData=null, packetsPaused=false, pausedFrames=[], packetFilter='ALL', packetAfter={MDR:0,HCI:0}, selectedPacket=null;
function metric(id,value,digits=1) {$(id).textContent=value==null?'—':typeof value==='number'?value.toFixed(digits):String(value);}
function milliseconds(value){return value==null?'—':`${value.toFixed(1)} ms`;}
function currentCapture(){return $('#packetSource').value==='HCI'?nerdData?.hci:nerdData?.wire;}
function captureFrames(){return packetsPaused?pausedFrames:(currentCapture()?.frames||[]);}
function filteredFrames(){const source=$('#packetSource').value,query=$('#packetSearch').value.trim().toUpperCase();return captureFrames().filter(frame=>frame.id>packetAfter[source]&&(packetFilter==='ALL'||(packetFilter==='ACK'?frame.label==='ACK':frame.direction===packetFilter))&&(!query||`${frame.label} ${frame.raw} ${frame.type||''}`.toUpperCase().includes(query)));}
function drawTraffic(rates){
  const canvas=$('#trafficChart'),width=canvas.clientWidth,height=145,scale=window.devicePixelRatio||1;
  if(!width)return;canvas.width=width*scale;canvas.height=height*scale;
  const context=canvas.getContext('2d');context.scale(scale,scale);context.clearRect(0,0,width,height);
  const max=Math.max(16,...rates.map(bucket=>Math.max(bucket.tx_bytes,bucket.rx_bytes)));
  context.strokeStyle='#303c29';context.lineWidth=1;
  [15,70,125].forEach(y=>{context.beginPath();context.moveTo(0,y);context.lineTo(width,y);context.stroke();});
  [['tx_bytes','#cef78a'],['rx_bytes','#8cbfe8']].forEach(([key,color])=>{context.strokeStyle=color;context.lineWidth=2;context.beginPath();rates.forEach((bucket,i)=>{const x=width*i/Math.max(1,rates.length-1),y=125-105*bucket[key]/max;i?context.lineTo(x,y):context.moveTo(x,y);});context.stroke();});
  context.fillStyle='#819374';context.font='11px monospace';context.fillText(`${max.toLocaleString()} B/s`,6,12);context.fillText('60s ago',0,142);context.fillText('now',width-24,142);
}
function showFrame(frame){
  selectedPacket={id:frame.id,source:frame.source};
  $('#frameDetailTitle').textContent=`${frame.direction} · ${frame.label} · ${frame.size} bytes${frame.seq!=null?` · sequence ${frame.seq}`:''}`;
  const bytes=frame.raw.split(' '),lines=[];
  for(let i=0;i<bytes.length;i+=16){const part=bytes.slice(i,i+16);const text=part.map(value=>{const code=parseInt(value,16);return code>=32&&code<=126?String.fromCharCode(code):'.';}).join('');lines.push(`${i.toString(16).padStart(4,'0')}  ${part.join(' ').padEnd(47,' ')}  ${text}`);}
  $('#frameHex').textContent=lines.join('\n');
  $$('#captureRows tr').forEach(row=>row.classList.toggle('selected',row.dataset.id===String(frame.id)));
}
function renderCapture(){
  if(!nerdData)return;
  const source=$('#packetSource').value,frames=filteredFrames(),wrap=$('.capture-table-wrap'),scroll=wrap.scrollTop;
  $('#hciPermission').hidden=source!=='HCI'||nerdData.hci.active;
  $('#hciStatus').textContent=nerdData.hci.last?'The optional capture helper is offline. Restart it to resume full HCI traffic.':'The regular user cannot open the HCI monitor channel on this machine. No system capability has been changed.';
  const address=nerdData.state.address||'HEADSET_ADDRESS';
  $('#hciCommand').textContent=`sudo /usr/bin/python3 '${nerdData.capture_socket.replace('/.runtime/hci-feed.sock','/hci_capture.py')}' --address ${address}`;
  const rows=frames.map(frame=>{
    const tr=document.createElement('tr');tr.dataset.id=frame.id;tr.classList.toggle('selected',selectedPacket?.id===frame.id&&selectedPacket?.source===source);
    const values=[new Date(frame.time*1000).toLocaleTimeString([],{hour12:false})+`.${Math.floor(frame.time*1000%1000).toString().padStart(3,'0')}`,frame.direction,frame.seq??(frame.handle!=null?`0x${frame.handle.toString(16)}`:'—'),frame.size,frame.label,source==='MDR'?(frame.valid?'OK':'BAD'):'HCI'];
    values.forEach((value,i)=>{const td=document.createElement('td');if(i===4){const button=document.createElement('button');button.textContent=value;button.addEventListener('click',()=>showFrame(frame));td.append(button);}else td.textContent=value;if(i===1)td.className=frame.direction.toLowerCase();tr.append(td);});
    return tr;
  });
  if(!rows.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=6;td.textContent=source==='HCI'?'Waiting for packets from the optional HCI helper.':'No frames match. Live headset replies will appear here.';tr.append(td);rows.push(tr);}
  $('#captureRows').replaceChildren(...rows);wrap.scrollTop=scroll;
  $('#captureCount').textContent=`${frames.length} visible${packetsPaused?' · view paused':''}`;
  if(!selectedPacket&&frames.length)showFrame(frames[0]);
}
function renderNerd(){
  if(!nerdData||$('#nerd').hidden)return;
  const {wire,telemetry,hci,state}=nerdData,audio=telemetry.audio,radio=telemetry.radio;
  $('#nerdLive').textContent=state.connected?'LIVE / 2 S HEARTBEAT':'HEADSET OFFLINE';
  metric('#rttMedian',state.connected?wire.ack_median_ms:null);$('#rttLast').textContent=milliseconds(wire.ack_last_ms);$('#rttP95').textContent=milliseconds(wire.ack_p95_ms);
  metric('#audioLatency',audio.reported_latency_ms);$('#latencyState').textContent=`PipeWire estimate · ${audio.sink_state?.toLowerCase()||'unavailable'}${audio.sink_state==='SUSPENDED'?' (idle report)':''}`;
  metric('#rssiMargin',radio.rssi_margin_db,0);metric('#txPower',radio.tx_power_dbm,0);
  $('#rssiDescription').textContent=radio.rssi_margin_db==null?radio.error||'Unavailable':radio.rssi_margin_db===0?'Within controller’s target range':radio.rssi_margin_db<0?'Below controller’s target range':'Above controller’s target range';
  $('#radioTransport').textContent=radio.transport||'Radio telemetry unavailable';
  $('#nerdCodec').textContent=`${(audio.codec||state.codec||'—').toUpperCase()} / ${audio.call_mode?'HFP/HSP':audio.profile?.startsWith('a2dp')?'A2DP':audio.profile||'—'}`;
  const priority={'sound-quality':'Sound quality · HD audio permitted','stable-connection':'Stable connection · HD audio restricted'}[state.quality_priority];
  $('#nerdPriority').textContent=priority||'Not reported by headset';$('#priorityTag').textContent=state.quality_priority==='sound-quality'?'QUALITY PRIORITY':state.quality_priority==='stable-connection'?'STABILITY PRIORITY':'PREFERENCE UNKNOWN';
  $('#nerdFormat').textContent=audio.format||'—';metric('#linkQuality',radio.link_quality==null?null:`${radio.link_quality} / 255`);metric('#afhChannels',radio.afh_channels==null?null:`${radio.afh_channels} / 79`);
  $('#linkSecurity').textContent=radio.available?`${radio.encrypted?'Yes':'No'} / ${radio.authenticated?'Yes':'No'}`:'—';$('#linkTimeout').textContent=radio.supervision_ms==null?'—':`${(radio.supervision_ms/1000).toFixed(1)} s`;
  $('#connectionCounts').textContent=`${nerdData.connections} / ${wire.ack_timeouts}`;
  const source=$('#packetSource').value,capture=source==='HCI'?hci:wire,rates=capture.rates||[],recent=rates.slice(-4,-1);
  const total=key=>recent.reduce((sum,bucket)=>sum+bucket[key],0)/Math.max(1,recent.length);
  metric('#txRate',total('tx_bytes'),0);metric('#rxRate',total('rx_bytes'),0);metric('#packetRate',total('tx_packets')+total('rx_packets'),1);
  $('#trafficScope').textContent=source==='HCI'?'HCI ACL/SCO / LAST 60 S':'SONY CONTROL / LAST 60 S';
  $('#wireTotals').textContent=source==='MDR'?`${wire.tx_frames+wire.rx_frames} frames · ${(wire.tx_bytes+wire.rx_bytes).toLocaleString()} B · ${wire.invalid_frames} invalid`:`${hci.active?'HCI helper live':'HCI helper offline'} · headset only`;
  drawTraffic(rates);renderCapture();
  $('#discordTitle').textContent=audio.call_mode?'The call profile is active right now.':'Stereo music and the XM4 mic use different profiles.';
  const recorders=(audio.active_recorders||[]).filter(item=>!item.corked);
  $('#discordStatus').textContent=`Current profile: ${audio.profile||'unavailable'}. Auto-switch to headset: ${audio.autoswitch==null?'unknown':audio.autoswitch?'enabled':'disabled'}. ${recorders.length?`Recording: ${recorders.map(item=>`${item.application} via ${item.source}`).join('; ')}.`:'No active recording streams at this sample.'}`;
  $('#alternateMics').textContent=(audio.alternate_inputs||[]).length?`Separate inputs currently exposed: ${audio.alternate_inputs.join(', ')}.`:'No separate microphone input is currently exposed by the audio server. Connect one, or enable its input/duplex profile in system sound settings, then select it in Discord.';
}
async function pollNerd(){
  try{
    const response=await fetch('/api/nerd',{signal:AbortSignal.timeout(5000)});if(!response.ok)throw new Error('Metrics unavailable');
    nerdData=await response.json();$('#callWarning').hidden=!nerdData.telemetry.audio.call_mode;renderNerd();
    if(typeof packetStudioIngest==='function')packetStudioIngest(nerdData);
  }catch(error){if(!$('#nerd').hidden)$('#nerdLive').textContent='LOCAL METRICS OFFLINE';}
  finally{setTimeout(pollNerd,2000);}
}
$('#pausePackets').addEventListener('click',()=>{packetsPaused=!packetsPaused;if(packetsPaused)pausedFrames=[...(currentCapture()?.frames||[])];$('#pausePackets').textContent=packetsPaused?'Resume view':'Pause view';$('#pausePackets').setAttribute('aria-pressed',String(packetsPaused));renderCapture();});
$('#clearPackets').addEventListener('click',()=>{const frames=currentCapture()?.frames||[];packetAfter[$('#packetSource').value]=frames[0]?.id||0;selectedPacket=null;$('#frameHex').textContent='View cleared. Capture and counters continue.';renderCapture();});
$('#packetSource').addEventListener('change',()=>{packetsPaused=false;selectedPacket=null;$('#pausePackets').textContent='Pause view';$('#pausePackets').setAttribute('aria-pressed','false');$('#frameHex').textContent='Select a captured frame.';renderNerd();});
$$('[data-packet-filter]').forEach(button=>button.addEventListener('click',()=>{packetFilter=button.dataset.packetFilter;$$('[data-packet-filter]').forEach(item=>item.classList.toggle('active',item===button));renderCapture();}));
$('#packetSearch').addEventListener('input',renderCapture);
$('#exportPackets').addEventListener('click',()=>{const source=$('#packetSource').value,data={source,exported_at:new Date().toISOString(),scope:source==='MDR'?'Exact bytes at the app RFCOMM socket, reassembled into Sony frames.':'Headset-only ACL/SCO packets from the HCI monitor. Host/controller capture; no RF retransmission visibility.',packets:filteredFrames()};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=`hush-${source.toLowerCase()}-${Date.now()}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('#copyHciCommand').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('#hciCommand').textContent);showToast('Passive capture command copied');}catch(error){showToast('Select and copy the command from the panel.',true);}});
window.addEventListener('resize',()=>{if(nerdData)renderNerd();});
pollNerd();
