/* Hush — AGPL-3.0-or-later. No external requests or dependencies. */
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
let snapshot = null, token = '', busy = false, eqDirty = false, toastTimer;
const fields = {'focus-on-voice':'focus_on_voice','speak-to-chat':'speak_to_chat','dsee':'dsee','pause-when-taken-off':'pause_when_taken_off','voice-notifications':'voice_notifications'};
const features = {'speak-to-chat':'speak-to-chat','dsee':'dsee','pause-when-taken-off':'pause-when-taken-off','voice-notifications':'voice-notifications'};
const modeContent = {
  'noise-cancelling': ['QUIET, ON YOUR TERMS', 'Find your\nquiet place.', 'Let the background fade. Keep your attention on the things that matter.', 'Noise cancelling is on'],
  'ambient-sound': ['A LITTLE MORE WORLD', 'Stay in\nthe moment.', 'Your music, with room for the world around you. Choose how much comes through.', 'Ambient sound is on'],
  'off': ['SIMPLY YOUR SOUND', 'Nothing\nin between.', 'Sound control is off. Settle into the natural sound of your headphones.', 'Sound control is off'],
  'wind-noise-reduction': ['A BREATH OF FRESH AIR', 'Let the\nwind pass.', 'Your headset is using wind noise reduction. Change modes whenever you like.', 'Wind noise reduction is on']
};
function showToast(message, error=false) {
  clearTimeout(toastTimer);
  const el = $('#toast'); el.textContent = message; el.classList.toggle('error',error); el.hidden = false;
  toastTimer = setTimeout(() => {el.hidden=true;},error ? 9000 : 4000);
}
function openTab(name) {
  $$('.tab-panel').forEach(el => {el.hidden = el.id !== name;});
  $$('.nav').forEach(el => {const active=el.dataset.tab===name;el.classList.toggle('active',active);if(active)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
  $('#pageTitle').textContent = {control:'Less noise. More you.',equalizer:'Good sound is personal.',activity:'The quiet has a story.',lab:'A curious little machine.',nerd:'The numbers behind the sound.',studio:'Your audio, straight from the packets.'}[name];
  if(name==='lab')loadLab();
  if(name==='nerd'&&typeof renderNerd==='function')renderNerd();
  if(typeof setStudioActive==='function')setStudioActive(name==='studio');
  if(name==='studio'&&typeof refreshTape==='function')refreshTape();
  if(name!=='studio'&&typeof tapeAudio!=='undefined')tapeAudio.pause();
}
$$('[data-tab]').forEach(el=>el.addEventListener('click',()=>openTab(el.dataset.tab)));
$$('[data-open-tab]').forEach(el=>el.addEventListener('click',()=>openTab(el.dataset.openTab)));
function fillSlider(el) {el.style.setProperty('--fill',`${100*(Number(el.value)-Number(el.min))/(Number(el.max)-Number(el.min))}%`);}
const bandLabels = ['Clear Bass','400 Hz','1 kHz','2.5 kHz','6.3 kHz','16 kHz'];
bandLabels.forEach((label,i)=>{
  const div=document.createElement('div');div.className='eq-band';
  const output=document.createElement('output');output.id=`eqValue${i}`;output.textContent='—';
  const input=document.createElement('input');Object.assign(input,{type:'range',min:'-10',max:'10',step:'1',value:'0',id:`eqBand${i}`,disabled:true});input.setAttribute('aria-label',label);input.setAttribute('aria-orientation','vertical');
  const caption=document.createElement('label');caption.htmlFor=input.id;caption.textContent=label;
  const small=document.createElement('small');small.textContent=i===0?'BASS':'dB';
  input.addEventListener('input',()=>{eqDirty=true;output.textContent=Number(input.value)>0?`+${input.value}`:input.value;$('#eqHelp').textContent='Custom mix ready. Apply to save on your XM4.';renderEnabled();});
  div.append(output,input,caption,small);$('#eqBands').append(div);
});
function renderEnabled() {
  const state=snapshot?.state||{}, connected=Boolean(state.connected)&&snapshot?.phase==='connected', enabled=connected&&!busy;
  $$('[data-mode],[data-scene]').forEach(el=>{el.disabled=!enabled||state.nc_mode==null;});
  $$('.toggle').forEach(el=>{const key=el.dataset.setting;el.disabled=!enabled||state[fields[key]]==null||(features[key]&&!(state.features||[]).includes(features[key]))||(key==='focus-on-voice'&&state.nc_mode!=='ambient-sound');});
  $('#ambient').disabled=!enabled||state.nc_mode!=='ambient-sound';
  $('#eqPreset').disabled=!enabled||state.eq_preset==null;
  $$('.eq-band input').forEach(el=>{el.disabled=!enabled||state.eq_bands==null;});
  $('#applyEq').disabled=!enabled||!eqDirty;
  $('#applyParadeEq').disabled=!enabled||state.eq_bands==null;
  $('#restoreMusicEq').disabled=!enabled||!snapshot?.eq_restore_available;
  $('#refresh').disabled=busy;
  $('#reconnect').disabled=busy;
  document.body.classList.toggle('busy',busy);
}
function clockLabel(seconds) {return new Date(seconds*1000).toLocaleTimeString([], {hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});}
function renderLogs(data) {
  const events=data.events.map(item=>{const row=document.createElement('div');row.className=`event ${item.kind}`;const time=document.createElement('time');time.textContent=clockLabel(item.time);const message=document.createElement('span');message.textContent=item.message;row.append(time,message);return row;});
  if(!events.length){const el=document.createElement('p');el.className='section-description';el.textContent='Connection events and your changes will appear here.';events.push(el);}
  $('#eventList').replaceChildren(...events);
  const packets=data.packets.map(item=>{const row=document.createElement('div');row.className='packet';const time=document.createElement('time');time.textContent=clockLabel(item.time);const dir=document.createElement('span');dir.className=item.direction.toLowerCase();dir.textContent=item.direction;const code=document.createElement('code');code.textContent=`${item.type} · ${item.payload}`;row.append(time,dir,code);return row;});
  $('#packetList').replaceChildren(...packets);
}
function render(data) {
  snapshot=data;
  const s=data.state, connected=s.connected&&data.phase==='connected';
  $('#statusDot').classList.toggle('connected',connected);
  $('#connectionText').textContent=connected?'XM4 connected':({discovering:'Finding your XM4',connecting:'Connecting to XM4',disconnected:'Headphones offline'}[data.phase]||'Checking connection');
  $('#connectionError').hidden=connected||!s.error;
  $('#errorText').textContent=s.error||'';
  $('#firmwareLabel').textContent=s.firmware?`Firmware ${s.firmware} · ${connected?'Connected':'Offline'}`:'Sony headphones';
  $('#deviceName').textContent=s.name||'WH-1000XM4';
  $('#batteryNumber').textContent=s.battery??'—';
  $('#batteryMood').textContent=s.battery==null?'Waiting for device':s.charging?'Charging':s.battery>=70?'Plenty of headspace':s.battery>=30?'Keep the good going':'Time for a recharge';
  $('#chargingText').textContent=connected?'HEADSET BATTERY':'LAST KNOWN BATTERY';
  $('#batteryBars').replaceChildren(...Array.from({length:10},(_,i)=>{const el=document.createElement('i');el.className=(s.battery??0)>i*10?'filled':'';return el;}));
  $('#codecValue').textContent=s.codec||'—';$('#firmwareValue').textContent=s.firmware||'—';$('#linkValue').textContent=connected?'RFCOMM / MDR v1':'Offline';
  const content=modeContent[s.nc_mode];
  if(content){$('#modeTag').textContent=content[0];$('#heroTitle').textContent=content[1];$('#heroTitle').style.whiteSpace='pre-line';$('#heroDescription').textContent=content[2];$('#heroState').textContent=connected?content[3]:'Last known headset setting';}
  $$('[data-mode]').forEach(el=>{const selected=el.dataset.mode===s.nc_mode;el.classList.toggle('selected',selected);el.setAttribute('aria-pressed',String(selected));});
  if(document.activeElement!==$('#ambient')) {$('#ambient').value=Math.max(1,s.ambient_level??12);fillSlider($('#ambient'));$('#ambientValue').textContent=s.nc_mode==='ambient-sound'?(s.ambient_level??'—'):'—';}
  $('#ambientSection').classList.toggle('inactive',s.nc_mode!=='ambient-sound');
  $$('.toggle').forEach(el=>el.setAttribute('aria-checked',String(s[fields[el.dataset.setting]]===true)));
  if(!eqDirty) {
    if(s.eq_preset)$('#eqPreset').value=s.eq_preset;
    [s.eq_bass,...(s.eq_bands||[null,null,null,null,null])].forEach((value,i)=>{if(value!=null){$(`#eqBand${i}`).value=value;$(`#eqValue${i}`).textContent=value>0?`+${value}`:String(value);}});
  }
  $('#eqCurrent').textContent=(s.eq_preset||'Reading EQ').replaceAll('-',' ').toUpperCase();
  const parade=s.eq_bass===2&&JSON.stringify(s.eq_bands)===JSON.stringify([-2,1,2,2,1]);
  $('#applyParadeEq').textContent=parade?'Parade Hall is active':'Apply Parade Hall';
  $('#applyParadeEq').setAttribute('aria-pressed',String(parade));
  if(parade)$('#eqCurrent').textContent='PARADE HALL';
  $('#syncText').textContent=connected?'SYNCED WITH YOUR HEADPHONES':data.phase==='connecting'?'CONNECTING TO HEADPHONES':'WAITING FOR HEADPHONES';
  renderEnabled();renderLogs(data);
}
async function command(job,success) {
  if(busy)return false;
  busy=true;renderEnabled();
  try{
    const response=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json','X-Hush-Token':token},body:JSON.stringify(job),signal:AbortSignal.timeout(45000)});
    const data=await response.json();
    if(data.state)render(data);
    if(!response.ok||!data.ok)throw new Error(data.error||'The headset did not confirm the change.');
    showToast(success||'Confirmed by your XM4');return true;
  }catch(error){showToast(error.message,true);return false;}
  finally{busy=false;renderEnabled();}
}
$$('[data-mode]').forEach(el=>el.addEventListener('click',()=>command({action:'set',key:'nc',value:el.dataset.mode},`${{ 'noise-cancelling':'Noise cancelling','ambient-sound':'Ambient sound','off':'Sound control off'}[el.dataset.mode]} · confirmed`)));
$$('[data-scene]').forEach(el=>el.addEventListener('click',()=>command({action:'scene',scene:el.dataset.scene},`${el.querySelector('strong').textContent} · confirmed by your XM4`)));
$$('.toggle').forEach(el=>el.addEventListener('click',()=>command({action:'set',key:el.dataset.setting,value:el.getAttribute('aria-checked')!=='true'})));
$('#ambient').addEventListener('input',()=>{$('#ambientValue').textContent=$('#ambient').value;fillSlider($('#ambient'));});
$('#ambient').addEventListener('change',()=>command({action:'set',key:'ambient-level',value:Number($('#ambient').value)},'Ambient level confirmed'));
$('#eqPreset').addEventListener('change',async()=>{eqDirty=false;await command({action:'set',key:'eq',value:$('#eqPreset').value},'Sony EQ preset confirmed');});
$('#applyEq').addEventListener('click',async()=>{const values=$$('.eq-band input').map(el=>Number(el.value));const ok=await command({action:'set',key:'eq-bands',value:values.join(',')},'Your custom mix is saved on the XM4');if(ok){eqDirty=false;$('#eqHelp').textContent='Your mix is saved on the headphones.';render(snapshot);}});
$('#applyParadeEq').addEventListener('click',async()=>{eqDirty=false;await command({action:'music-eq',preset:'parade-hall'},'Parade Hall EQ · confirmed by your XM4');});
$('#restoreMusicEq').addEventListener('click',async()=>{eqDirty=false;await command({action:'restore-music-eq'},'Your previous EQ is restored');});
$('#refresh').addEventListener('click',()=>command({action:'refresh'},'Headset settings refreshed'));
$('#reconnect').addEventListener('click',()=>command({action:'reconnect'},'Connected to your XM4'));
document.addEventListener('keydown',event=>{if(event.ctrlKey||event.altKey||event.metaKey||['INPUT','SELECT','TEXTAREA','BUTTON'].includes(event.target.tagName))return;const mode={'1':'noise-cancelling','2':'ambient-sound','3':'off'}[event.key];if(mode&&!busy&&snapshot?.state.connected)command({action:'set',key:'nc',value:mode});});
async function poll(){try{const response=await fetch('/api/state',{signal:AbortSignal.timeout(5000)});if(!response.ok)throw new Error('Server unavailable');const data=await response.json();token=data.token;render(data);}catch(error){$('#connectionText').textContent='Local app is offline';$('#statusDot').classList.remove('connected');if(snapshot){snapshot.state.connected=false;renderEnabled();}$('#connectionError').hidden=false;$('#errorText').textContent='Hush is not running. Start launch.sh in the app folder, then reload.';}finally{setTimeout(poll,1300);}}
poll();

async function loadLab() {
  try {
    const response=await fetch('/api/lab');
    if(!response.ok)throw new Error('Lab report unavailable. Restart Hush to load the updated app.');
    const data=await response.json(), inventory=data.inventory||{}, nvdm=data.nvdm||{};
    $('#labKeys').textContent=inventory.active_keys??'—';
    $('#labFirmware').textContent=data.firmware?.installed||snapshot?.state.firmware||'unknown';
    $('#backupTag').textContent=nvdm.backup_bytes?'BACKUP VERIFIED':nvdm.status?.toUpperCase()||'NOT TESTED';
    $('#backupSize').textContent=nvdm.backup_bytes?nvdm.backup_bytes/1024:'—';
    $('#backupDetail').textContent=nvdm.backup_bytes?'A private copy of your settings and calibration store was read over Bluetooth. The saved file has a SHA-256 sidecar.':nvdm.detail||'Run probe.py to create a diagnostic report.';
    $('#backupChecks').textContent=inventory.valid_blocks?`${inventory.valid_blocks} valid blocks · ${inventory.valid_records.toLocaleString()} valid records · ${inventory.invalid_records} invalid records`:'';
    const flash=data.firmware?.physical_flash_probe;
    $('#physicalFlashResult').textContent=flash?.status==='denied'?`Physical flash page zero refused the read request (status ${flash.return_code}). Logical NVDM is readable; a complete physical firmware dump remains unverified.`:flash?.status==='header-readable'?'Physical flash page zero answered, but a complete firmware dump is not verified.':'A complete physical firmware dump has not been tested.';
    $('#serviceList').replaceChildren(...data.services.map(service=>{const row=document.createElement('div');row.className='service-row';const text=document.createElement('div');const name=document.createElement('strong');name.textContent=service.name;const uuid=document.createElement('code');uuid.textContent=service.uuid;const channel=document.createElement('span');channel.className='channel';channel.textContent=service.channel?`CH ${service.channel}`:'—';text.append(name,uuid);row.append(text,channel);return row;}));
    const interesting=['optimizer_coeff','nc_is_optimized','nc_atm_value','touch_panel_disabled','test_forced_touch_sensor','codec_ldac','codec_aptx','sound_position','test_nc_disable','test_vp_disable','power_saving','voice_language','multi_device','boot_option'];
    $('#labNames').replaceChildren(...interesting.filter(name=>(inventory.config_names||[]).includes(name)).map(name=>{const code=document.createElement('code');code.textContent=`config/${name}`;return code;}));
  } catch(error){showToast(error.message,true);}
}
