const state = { data: null, visible: new Set(['executed', 'lds', 'rdo']) };
const colors = { executed:'#f2f7fa', lds:'#35d6b5', rdo:'#ffb55f', daily:'#55a7ff', weekly:'#8f83ff' };
const labels = { executed:'Ejecutado', lds:'Predicción LDS', rdo:'Reprogramación', daily:'Prog. diaria', weekly:'Prog. semanal' };
const $ = (id) => document.getElementById(id);
const nf = new Intl.NumberFormat('es-PE', { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat('es-PE', { minimumFractionDigits: 1, maximumFractionDigits: 1 });

function tickClock(){
  const now = new Date();
  $('clock').textContent = now.toLocaleTimeString('es-PE', {hour12:false});
  $('todayLabel').textContent = now.toLocaleDateString('es-PE', {weekday:'short', day:'2-digit', month:'short'}).replace('.', '');
}
setInterval(tickClock, 1000); tickClock();

function timeLabel(iso){ return iso ? new Date(iso).toLocaleTimeString('es-PE',{hour:'2-digit',minute:'2-digit',hour12:false}) : '—'; }
function localIsoTime(iso){ return iso?.slice(11,16) || '—'; }
function value(v){ return Number.isFinite(v) ? nf.format(v) : '—'; }

async function load({refresh=false}={}){
  const button = $('refreshButton');
  button.disabled = true; button.classList.add('loading');
  setConnection('loading');
  try {
    if(refresh){
      const res = await fetch('/api/refresh', {method:'POST'});
      if(!res.ok) throw new Error('No se pudo actualizar COES');
    }
    const res = await fetch('/api/dashboard', {cache:'no-store'});
    if(!res.ok) throw new Error('No se pudo leer el panel');
    state.data = await res.json();
    render(state.data);
    setConnection('online');
  } catch (error){
    console.error(error); setConnection('error');
    $('chartLoading').innerHTML = '<span></span>No se pudo actualizar. Se conservará la última vista disponible.';
  } finally {
    button.disabled = false; button.classList.remove('loading');
  }
}

function setConnection(mode){
  const el=$('liveState'); el.className='live-state'+(mode==='online'?' online':mode==='error'?' error':'');
  el.querySelector('strong').textContent = mode==='online'?'En línea':mode==='error'?'Sin conexión':'Actualizando';
}

function render(data){
  $('chartLoading').style.display='none';
  $('currentDemand').textContent=value(data.summary.current?.value);
  $('currentDemandMeta').textContent=data.summary.current ? `${localIsoTime(data.summary.current.time)} · último intervalo COES` : 'Sin dato ejecutado para hoy';
  $('peakForecast').textContent=value(data.summary.peak24?.value);
  $('peakForecastMeta').textContent=data.summary.peak24 ? `${localIsoTime(data.summary.peak24.time)} · predicción LDS` : 'Sin horizonte futuro disponible';
  $('modelMae').textContent=value(data.summary.modelMae);
  $('modelMaeMeta').textContent=`${data.summary.modelSamples || 0} casos · backtest temporal de 30 días`;
  $('revisionCount').textContent=nf.format(data.summary.revisionCount || 0);
  $('revisionMeta').textContent=data.summary.revisionCount ? 'Valores modificados desde la primera captura' : 'Sin cambios desde la primera captura';
  $('coverageLabel').textContent=`Cobertura ${data.dateLabel} · ${data.points.length} intervalos`;
  $('freshnessLabel').textContent=`Actualizado ${timeLabel(data.generatedAt)}`;
  $('executedIntervals').textContent=`${data.summary.executedIntervals} / 48`;
  $('lastObservation').textContent=localIsoTime(data.summary.current?.time);
  $('monitorStatus').textContent=data.summary.revisionCount ? `${data.summary.revisionCount} cambios hoy` : 'Sin cambios detectados';
  $('dataNotice').textContent=data.model?.trainedThrough ? `Modelo reentrenado con ${nf.format(data.model.trainingRows)} intervalos, incluido todo lo ejecutado hasta ${localIsoTime(data.model.trainedThrough)}. Las horas futuras no entran al entrenamiento.` : 'El modelo histórico todavía no está disponible.';
  renderHorizons(data.horizons); renderWeights(data.weights); renderRevisions(data.revisions); renderChart(); renderSpark();
}

function renderHorizons(horizons){
  $('horizonCards').innerHTML=horizons.map(h=>{
    const trend=h.trend>20?'Al alza':h.trend<-20?'A la baja':'Estable';
    const klass=h.trend>20?'trend-up':h.trend<-20?'trend-down':'';
    const coverage=h.complete?'':` · cobertura ${h.intervals}/${h.expected}`;
    return `<div class="horizon-item"><div class="horizon-top"><span>Próximas ${h.hours} horas</span><strong>${value(h.average)}<small>MW prom.</small></strong></div><div class="horizon-stats"><span>Pico ${value(h.max)} MW · ${localIsoTime(h.peakTime)}${coverage}</span><span class="${klass}">${trend}</span></div></div>`;
  }).join('');
}

function renderWeights(weights){
  const meta=[['historical','Modelo histórico independiente','var(--mint)'],['rdo','Reprogramación corregida por LDS','var(--amber)'],['daily','Programación diaria','var(--blue)']];
  $('weightBars').innerHTML=meta.map(([key,label,color])=>`<div class="weight-row"><div class="weight-label"><span>${label}</span><strong>${Math.round((weights[key]||0)*100)}%</strong></div><div class="weight-track"><span style="--bar:${color};width:${(weights[key]||0)*100}%"></span></div></div>`).join('');
}

function renderRevisions(rows){
  $('revisionRows').innerHTML=rows.length?rows.map(r=>{
    const d=r.diff>0?'delta-pos':r.diff<0?'delta-neg':'';
    return `<tr><td>${timeLabel(r.observedAt)}</td><td><strong>${localIsoTime(r.targetTime)}</strong></td><td>${r.label}</td><td>${decimal.format(r.oldValue)} MW</td><td>${decimal.format(r.newValue)} MW</td><td class="${d}">${r.diff>0?'+':''}${decimal.format(r.diff)} MW</td></tr>`;
  }).join(''):'<tr><td colspan="6" class="empty">Aún no se detectaron modificaciones. El monitor conservará aquí cada cambio.</td></tr>';
}

function renderSpark(){
  const vals=(state.data?.points||[]).map(p=>p.executed).filter(Number.isFinite).slice(-16);
  if(vals.length<2){$('currentSpark').innerHTML='';return;}
  const min=Math.min(...vals), max=Math.max(...vals), range=max-min||1;
  const pts=vals.map((v,i)=>`${(i/(vals.length-1)*100).toFixed(1)},${(58-(v-min)/range*48).toFixed(1)}`).join(' ');
  $('currentSpark').innerHTML=`<svg viewBox="0 0 100 62" preserveAspectRatio="none"><defs><linearGradient id="sg" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#35d6b5" stop-opacity=".28"/><stop offset="1" stop-color="#35d6b5" stop-opacity="0"/></linearGradient></defs><polygon points="0,62 ${pts} 100,62" fill="url(#sg)"/><polyline points="${pts}" fill="none" stroke="#35d6b5" stroke-width="1.5"/></svg>`;
}

function renderChart(){
  const svg=$('demandChart'), wrap=$('chartWrap'), data=state.data.points;
  const W=1100,H=470,m={l:66,r:22,t:28,b:48},iw=W-m.l-m.r,ih=H-m.t-m.b;
  const seriesKeys=['executed','lds','rdo','daily','weekly'].filter(k=>state.visible.has(k));
  const all=data.flatMap(p=>seriesKeys.map(k=>p[k])).filter(Number.isFinite);
  if(!all.length){svg.innerHTML='';return;}
  let ymin=Math.floor((Math.min(...all)-120)/250)*250, ymax=Math.ceil((Math.max(...all)+120)/250)*250;
  const x=i=>m.l+i/(data.length-1)*iw, y=v=>m.t+(ymax-v)/(ymax-ymin)*ih;
  let html='';
  for(let i=0;i<=5;i++){const v=ymax-i*(ymax-ymin)/5, yy=y(v);html+=`<line class="grid-line" x1="${m.l}" y1="${yy}" x2="${W-m.r}" y2="${yy}"/><text class="axis-text" x="${m.l-12}" y="${yy+4}" text-anchor="end">${nf.format(v)}</text>`;}
  data.forEach((p,i)=>{if(i%6===0){html+=`<text class="axis-text" x="${x(i)}" y="${H-18}" text-anchor="middle">${localIsoTime(p.time)}</text>`;}});
  const lower=data.map((p,i)=>Number.isFinite(p.lower)?`${x(i)},${y(p.lower)}`:null).filter(Boolean);
  const upper=data.map((p,i)=>Number.isFinite(p.upper)?`${x(i)},${y(p.upper)}`:null).filter(Boolean).reverse();
  if(state.visible.has('lds')&&lower.length) html+=`<polygon class="confidence-band" points="${[...lower,...upper].join(' ')}"/>`;
  const pathFor=(key)=>{let d='',open=false;data.forEach((p,i)=>{const v=p[key];if(Number.isFinite(v)){d+=`${open?'L':'M'}${x(i).toFixed(2)},${y(v).toFixed(2)} `;open=true}else open=false;});return d;};
  const widths={executed:2.7,lds:2.7,rdo:1.7,daily:1.4,weekly:1.25};
  for(const key of ['weekly','daily','rdo','lds','executed']) if(state.visible.has(key)) html+=`<path class="series-path" d="${pathFor(key)}" stroke="${colors[key]}" stroke-width="${widths[key]}" ${['daily','weekly'].includes(key)?'stroke-dasharray="5 5"':''}/>`;
  const currentIndex=data.map(p=>p.executed).findLastIndex(Number.isFinite);
  if(currentIndex>=0&&currentIndex<data.length-1){const xx=x(currentIndex);html+=`<line class="future-divider" x1="${xx}" y1="${m.t}" x2="${xx}" y2="${m.t+ih}"/><text class="future-label" x="${xx+8}" y="${m.t+13}">PRONÓSTICO</text>`;}
  html+=`<g id="hoverGroup" visibility="hidden"><line class="hover-line" y1="${m.t}" y2="${m.t+ih}"/><g id="hoverDots"></g></g><rect id="chartHit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/>`;
  svg.innerHTML=html;
  const hit=svg.querySelector('#chartHit'), hover=svg.querySelector('#hoverGroup'), dots=svg.querySelector('#hoverDots'), tip=$('chartTooltip');
  hit.addEventListener('pointermove',e=>{const rect=svg.getBoundingClientRect();const sx=(e.clientX-rect.left)/rect.width*W;const i=Math.max(0,Math.min(data.length-1,Math.round((sx-m.l)/iw*(data.length-1))));const xx=x(i),p=data[i];hover.setAttribute('visibility','visible');hover.querySelector('line').setAttribute('x1',xx);hover.querySelector('line').setAttribute('x2',xx);dots.innerHTML=seriesKeys.filter(k=>Number.isFinite(p[k])).map(k=>`<circle class="hover-dot" cx="${xx}" cy="${y(p[k])}" r="4" fill="${colors[k]}"/>`).join('');tip.hidden=false;tip.innerHTML=`<span class="tooltip-time">${localIsoTime(p.time)}</span>${seriesKeys.filter(k=>Number.isFinite(p[k])).map(k=>`<div class="tooltip-row"><span>${labels[k]}</span><strong>${decimal.format(p[k])} MW</strong></div>`).join('')}`;const tx=Math.min(wrap.clientWidth-205,Math.max(12,e.clientX-wrap.getBoundingClientRect().left+14));tip.style.left=`${tx}px`;tip.style.top=`${Math.max(12,e.clientY-wrap.getBoundingClientRect().top-30)}px`;});
  hit.addEventListener('pointerleave',()=>{hover.setAttribute('visibility','hidden');tip.hidden=true;});
}

document.querySelectorAll('.legend-chip').forEach(button=>button.addEventListener('click',()=>{const key=button.dataset.series;if(state.visible.has(key))state.visible.delete(key);else state.visible.add(key);button.classList.toggle('active');renderChart();}));
$('refreshButton').addEventListener('click',()=>load({refresh:true}));
window.addEventListener('resize',()=>state.data&&renderChart());
load(); setInterval(()=>load(), 60_000);
