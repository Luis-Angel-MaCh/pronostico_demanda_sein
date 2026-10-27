import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { extname, join, normalize, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { DatabaseSync } from 'node:sqlite';

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const publicDir = join(projectRoot, 'dashboard');
const dbPath = join(projectRoot, 'data', 'monitor', 'coes_versiones.sqlite');
const modelPath = join(projectRoot, 'data', 'modelo', 'pronostico_live.json');
const modelScript = join(projectRoot, 'scripts', 'actualizar_pronostico_lds.py');
const db = new DatabaseSync(dbPath);
const PORT = Number(process.env.PORT || 5173);
const TZ = 'America/Lima';
const portalUrl = 'https://www.coes.org.pe/Portal/portalinformacion/Demanda';
const apiUrl = 'https://appserver.coes.org.pe/waMediciones/api/Mediciones';
const apiSeries = new Map([[3,'prog_semanal_api'],[4,'prog_diaria_api'],[5,'reprogramacion_api']]);
let refreshPromise = null;
let liveModel = null;
const execFileAsync = promisify(execFile);
const localPython = join(projectRoot, '.venv', 'Scripts', 'python.exe');
const pythonPath = process.env.LDS_PYTHON || (existsSync(localPython) ? localPython : 'python');

async function loadLiveModel(){
  try { liveModel=JSON.parse(await readFile(modelPath,'utf8')); } catch { liveModel=null; }
  return liveModel;
}
await loadLiveModel();

db.exec(`
  PRAGMA journal_mode=WAL;
  CREATE TABLE IF NOT EXISTS estado_actual(target_time TEXT NOT NULL,serie TEXT NOT NULL,value REAL NOT NULL,observed_at TEXT NOT NULL,PRIMARY KEY(target_time,serie));
  CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT,observed_at TEXT NOT NULL,target_time TEXT NOT NULL,serie TEXT NOT NULL,value REAL NOT NULL);
  CREATE INDEX IF NOT EXISTS ix_snapshots_target ON snapshots(target_time,serie,observed_at);
  CREATE TABLE IF NOT EXISTS cambios(id INTEGER PRIMARY KEY AUTOINCREMENT,observed_at TEXT NOT NULL,target_time TEXT NOT NULL,serie TEXT NOT NULL,event_type TEXT NOT NULL,old_value REAL,new_value REAL NOT NULL,diff_mw REAL);
  CREATE INDEX IF NOT EXISTS idx_cambios_observed_event ON cambios(observed_at,event_type);
  CREATE TABLE IF NOT EXISTS pronosticos_emitidos(issued_at TEXT NOT NULL,target_time TEXT NOT NULL,horizon_steps INTEGER NOT NULL,lds REAL NOT NULL,ml REAL,rdo REAL,daily REAL,PRIMARY KEY(issued_at,target_time));
  CREATE INDEX IF NOT EXISTS ix_pronosticos_target ON pronosticos_emitidos(target_time,issued_at);
  PRAGMA optimize;
`);

function localParts(d=new Date()){
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:TZ,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23',timeZoneName:'longOffset'}).formatToParts(d).map(p=>[p.type,p.value]));
  return {date:`${parts.year}-${parts.month}-${parts.day}`, iso:`${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}${parts.timeZoneName.replace('GMT','')}`};
}
function addDays(dateText,days){const d=new Date(`${dateText}T12:00:00Z`);d.setUTCDate(d.getUTCDate()+days);return d.toISOString().slice(0,10);}
function portalDate(d){const [y,m,day]=d.split('-');return `${day}/${m}/${y}`;}

async function jsonFetch(url,options={}){
  const res=await fetch(url,{...options,headers:{'user-agent':'LDS-Dashboard/1.0',...(options.headers||{})},signal:AbortSignal.timeout(60_000)});
  if(!res.ok) throw new Error(`${res.status} ${url}`);
  return res.json();
}
async function fetchPortal(start,end){
  const body=new URLSearchParams({fechaInicial:portalDate(start),fechaFinal:portalDate(end)});
  const json=await jsonFetch(portalUrl,{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body});
  const mapping={ValorEjecutado:'ejecutado_portal',ValorProgramacionDiaria:'prog_diaria_portal',ValorProgramacionSemanal:'prog_semanal_portal'};
  return (json.Data||[]).flatMap(item=>Object.entries(mapping).filter(([field])=>item[field]!=null).map(([field,serie])=>({target:item.Fecha.replaceAll('/','-').replace(' ','T'),serie,value:Number(item[field])})));
}
async function fetchCurve(code,start,end){
  const url=new URL(apiUrl);url.search=new URLSearchParams({lectcodi:String(code),fechaIni:start,fechaFin:end});
  const json=await jsonFetch(url);
  const sums=new Map();
  for(const row of json){const day=row.Medifecha.slice(0,10);for(let i=1;i<=48;i++){const value=row[`h${i}`];if(value==null)continue;const targetDate=i===48?addDays(day,1):day;const minutes=(i%48)*30;const hh=String(Math.floor(minutes/60)).padStart(2,'0'),mm=String(minutes%60).padStart(2,'0');const key=`${targetDate}T${hh}:${mm}`;sums.set(key,(sums.get(key)||0)+Number(value));}}
  return [...sums].map(([target,value])=>({target,serie:apiSeries.get(code),value}));
}
function store(rows,observedAt){
  const select=db.prepare('SELECT value,observed_at FROM estado_actual WHERE target_time=? AND serie=?');
  const snap=db.prepare('INSERT INTO snapshots(observed_at,target_time,serie,value) VALUES(?,?,?,?)');
  const change=db.prepare('INSERT INTO cambios(observed_at,target_time,serie,event_type,old_value,new_value,diff_mw) VALUES(?,?,?,?,?,?,?)');
  const upsert=db.prepare('INSERT INTO estado_actual(target_time,serie,value,observed_at) VALUES(?,?,?,?) ON CONFLICT(target_time,serie) DO UPDATE SET value=excluded.value,observed_at=excluded.observed_at');
  db.exec('BEGIN');let inserts=0,updates=0;
  try {for(const row of rows){const previous=select.get(row.target,row.serie);const old=previous?.value;if(old!=null&&Math.abs(old-row.value)<=0.0005){const needsConfirmation=row.serie==='ejecutado_portal'&&previous.observed_at.slice(0,16)<row.target&&observedAt.slice(0,16)>=row.target;if(needsConfirmation){snap.run(observedAt,row.target,row.serie,row.value);upsert.run(row.target,row.serie,row.value,observedAt);}continue;}const type=old==null?'insert':'update';snap.run(observedAt,row.target,row.serie,row.value);change.run(observedAt,row.target,row.serie,type,old??null,row.value,old==null?null:row.value-old);upsert.run(row.target,row.serie,row.value,observedAt);type==='insert'?inserts++:updates++;}db.exec('COMMIT');}catch(e){db.exec('ROLLBACK');throw e;}
  return {inserts,updates};
}
async function refresh(){
  if(refreshPromise)return refreshPromise;
  refreshPromise=(async()=>{const now=localParts(),start=addDays(now.date,-8),split=addDays(start,6),resume=addDays(split,1),futureEnd=addDays(now.date,2);const curveRequests=[...apiSeries.keys()].flatMap(c=>[fetchCurve(c,start,split),fetchCurve(c,resume,futureEnd)]);const results=await Promise.all([fetchPortal(start,futureEnd),...curveRequests]);const executedCutoff=now.iso.slice(0,16);const rows=results.flat().filter(r=>r.serie!=='ejecutado_portal'||r.target<=executedCutoff);const stored=store(rows,now.iso);const trained=await execFileAsync(pythonPath,[modelScript],{cwd:projectRoot,timeout:120_000,maxBuffer:1024*1024});await loadLiveModel();const dashboard=buildDashboard(now.date);archiveForecasts(dashboard,now.iso);return {...stored,consulted:rows.length,observedAt:now.iso,model:JSON.parse(trained.stdout)};})().finally(()=>refreshPromise=null);
  return refreshPromise;
}

function stats(values){const v=values.filter(Number.isFinite);if(!v.length)return {n:0,mae:null,bias:0};return {n:v.length,mae:v.reduce((a,b)=>a+Math.abs(b),0)/v.length,bias:v.reduce((a,b)=>a+b,0)/v.length};}
function issuedPerformance(){
  const rows=db.prepare(`WITH ranked AS (
    SELECT p.*,e.value actual,ROW_NUMBER() OVER(PARTITION BY p.target_time ORDER BY p.issued_at DESC) rn
    FROM pronosticos_emitidos p JOIN estado_actual e ON e.target_time=p.target_time AND e.serie='ejecutado_portal'
    WHERE substr(p.issued_at,1,16)<p.target_time AND substr(e.observed_at,1,16)>=e.target_time
  ) SELECT actual,ml,rdo,daily FROM ranked WHERE rn=1 ORDER BY target_time DESC LIMIT 96`).all();
  const result={};
  for(const source of ['ml','rdo','daily']){const valid=rows.filter(r=>Number.isFinite(r[source]));const errors=valid.map(r=>r.actual-r[source]);const base=stats(errors);const corrected=base.n?valid.reduce((sum,r)=>sum+Math.abs(r.actual-(r[source]+base.bias)),0)/base.n:null;result[source]={...base,correctedMae:corrected};}
  return result;
}
function attachArchivedForecasts(points,date){const rows=db.prepare(`WITH ranked AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY target_time ORDER BY issued_at DESC) rn FROM pronosticos_emitidos WHERE substr(target_time,1,10)=? AND substr(issued_at,1,16)<target_time) SELECT target_time,lds,rdo,daily FROM ranked WHERE rn=1`).all(date);const byTime=new Map(rows.map(r=>[r.target_time,r]));for(const p of points){if(!Number.isFinite(p.executed))continue;const archived=byTime.get(p.time);if(!archived)continue;p.lds=archived.lds;if(Number.isFinite(archived.rdo))p.rdo=archived.rdo;if(Number.isFinite(archived.daily))p.daily=archived.daily;}}
function blendForecasts(points){
  const performance=issuedPerformance();
  let sums={historical:0,rdo:0,daily:0},count=0;
  for(const p of points){if(Number.isFinite(p.executed))continue;const horizon=p.horizonSteps||12;const nearest=[12,24,48].reduce((a,b)=>Math.abs(b-horizon)<Math.abs(a-horizon)?b:a);const priors={historical:liveModel?.validation?.[String(nearest)]?.maeModel??95,rdo:79.41,daily:95.25};const available={historical:p.ml,rdo:Number.isFinite(p.rdoAdvanced)?p.rdoAdvanced:p.rdo,daily:p.daily};const aliases={historical:'ml',rdo:'rdo',daily:'daily'};const keys=Object.keys(available).filter(k=>Number.isFinite(available[k]));if(!keys.length)continue;const score=Object.fromEntries(keys.map(k=>{const perf=performance[aliases[k]];const observed=perf?.n>=12?(k==='rdo'?perf.mae:(perf.correctedMae??perf.mae)):priors[k];const n=Math.min(perf?.n||0,48);return [k,(observed*n+priors[k]*24)/(n+24)];}));const champion=keys.reduce((best,k)=>score[k]<score[best]?k:best,keys[0]);const perf=performance[aliases[champion]];const correction=champion!=='rdo'&&perf?.n>=24&&perf.correctedMae<perf.mae?Math.max(-80,Math.min(80,perf.bias)):0;p.lds=available[champion]+correction;p.champion=champion;p.lower=Number.isFinite(p.modelLower)?p.lds-(p.ml-p.modelLower):null;p.upper=Number.isFinite(p.modelUpper)?p.lds+(p.modelUpper-p.ml):null;sums[champion]++;count++;}
  return {historical:count?sums.historical/count:1,rdo:count?sums.rdo/count:0,daily:count?sums.daily/count:0};
}
function archiveForecasts(data,issuedAt){const insert=db.prepare('INSERT OR IGNORE INTO pronosticos_emitidos(issued_at,target_time,horizon_steps,lds,ml,rdo,daily) VALUES(?,?,?,?,?,?,?)');const current=data.summary.current?.time||issuedAt.slice(0,16);db.exec('BEGIN');try{for(const p of data._allPoints||data.points){if(p.time<=current||!Number.isFinite(p.lds))continue;insert.run(issuedAt,p.time,p.horizonSteps||1,p.lds,Number.isFinite(p.ml)?p.ml:null,Number.isFinite(p.rdo)?p.rdo:null,Number.isFinite(p.daily)?p.daily:null);}db.exec('COMMIT');}catch(e){db.exec('ROLLBACK');throw e;}}
function buildDashboard(date){
  const next=addDays(date,1),afterNext=addDays(date,2),nowMinute=localParts().iso.slice(0,16);const rows=db.prepare('SELECT target_time,serie,value,observed_at FROM estado_actual WHERE target_time>? AND target_time<=? ORDER BY target_time').all(`${date}T00:00`,`${afterNext}T00:00`);const map=new Map();for(const r of rows){if(!map.has(r.target_time))map.set(r.target_time,{time:r.target_time});const p=map.get(r.target_time);if(r.serie==='ejecutado_portal'&&r.target_time<=nowMinute&&r.observed_at.slice(0,16)>=r.target_time)p.executed=r.value;else if(r.serie==='reprogramacion_api')p.rdo=r.value;else if(r.serie==='prog_diaria_portal')p.daily=r.value;else if(r.serie==='prog_semanal_portal')p.weekly=r.value;}
  for(const f of liveModel?.forecast||[]){if(!map.has(f.time))map.set(f.time,{time:f.time});Object.assign(map.get(f.time),{ml:f.prediction,rdoCalibrated:f.rdoCalibrated,rdoAdvanced:f.rdoAdvanced,modelLower:f.lower,modelUpper:f.upper,horizonSteps:f.horizonSteps});}
  const allPoints=[...map.values()].sort((a,b)=>a.time.localeCompare(b.time));attachArchivedForecasts(allPoints,date);const weights=blendForecasts(allPoints);const currentIndex=allPoints.findLastIndex(p=>Number.isFinite(p.executed));const current=currentIndex>=0?{time:allPoints[currentIndex].time,value:allPoints[currentIndex].executed}:null;const future=allPoints.slice(currentIndex+1).filter(p=>Number.isFinite(p.lds));const points=allPoints.filter(p=>p.time<=`${next}T00:00`);
  const horizons=[6,12,24].map(hours=>{const expected=hours*2,sample=future.slice(0,expected),vals=sample.map(p=>p.lds).filter(Number.isFinite),max=vals.length?Math.max(...vals):null,peak=sample.find(p=>p.lds===max);return {hours,intervals:vals.length,expected,complete:vals.length===expected,average:vals.length?vals.reduce((a,b)=>a+b,0)/vals.length:null,max,peakTime:peak?.time||null,trend:vals.length>1?vals.at(-1)-vals[0]:0};});
  const revisions=db.prepare("SELECT observed_at,target_time,serie,old_value,new_value,diff_mw FROM cambios WHERE substr(observed_at,1,10)=? AND event_type='update' ORDER BY observed_at DESC LIMIT 12").all(date).map(r=>({observedAt:r.observed_at,targetTime:r.target_time,label:({ejecutado_portal:'Ejecutado',prog_diaria_portal:'Prog. diaria',prog_semanal_portal:'Prog. semanal',reprogramacion_api:'Reprogramación',prog_diaria_api:'Diaria API',prog_semanal_api:'Semanal API'})[r.serie]||r.serie,oldValue:r.old_value,newValue:r.new_value,diff:r.diff_mw}));
  const validation=liveModel?.validation?.['12'],rdoMae=79.40699225429016,rdoWins=rdoMae<=(validation?.maeModel??Infinity);const activeMae=rdoWins?rdoMae:(validation?.maeModel??null),activeSamples=rdoWins?1282:(validation?.samples??0);const peak24=horizons[2]?.max!=null?{value:horizons[2].max,time:horizons[2].peakTime}:null;const generated=localParts().iso;
  const result={generatedAt:generated,date,dateLabel:new Intl.DateTimeFormat('es-PE',{timeZone:TZ,weekday:'long',day:'numeric',month:'long',year:'numeric'}).format(new Date(`${date}T12:00:00-05:00`)),points,weights,horizons,revisions,model:{name:liveModel?.model||'No disponible',trainedThrough:liveModel?.trainedThrough||null,trainingRows:liveModel?.trainingRows||0},summary:{current,peak24,modelMae:Number.isFinite(activeMae)?activeMae:null,modelSamples:activeSamples,revisionCount:db.prepare("SELECT count(*) n FROM cambios WHERE substr(observed_at,1,10)=? AND event_type='update'").get(date).n,executedIntervals:points.filter(p=>Number.isFinite(p.executed)).length}};Object.defineProperty(result,'_allPoints',{value:allPoints,enumerable:false});return result;
}

const mime={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.svg':'image/svg+xml'};
const server=http.createServer(async(req,res)=>{
  try{
    const url=new URL(req.url,'http://localhost');
    if(url.pathname==='/api/dashboard'){const data=buildDashboard(localParts().date);res.writeHead(200,{'content-type':'application/json; charset=utf-8','cache-control':'no-store'});return res.end(JSON.stringify(data));}
    if(url.pathname==='/api/refresh'&&req.method==='POST'){const result=await refresh();res.writeHead(200,{'content-type':'application/json; charset=utf-8','cache-control':'no-store'});return res.end(JSON.stringify(result));}
    const relative=url.pathname==='/'?'index.html':url.pathname.slice(1);const safe=normalize(relative).replace(/^(\.\.[/\\])+/, '');const path=join(publicDir,safe);if(!path.startsWith(publicDir))throw new Error('Ruta inválida');const body=await readFile(path);res.writeHead(200,{'content-type':mime[extname(path)]||'application/octet-stream','cache-control':'no-cache'});res.end(body);
  }catch(error){res.writeHead(error.code==='ENOENT'?404:500,{'content-type':'application/json; charset=utf-8'});res.end(JSON.stringify({error:error.message}));}
});
server.listen(PORT,'127.0.0.1',async()=>{console.log(`Local: http://localhost:${PORT}/`);try{console.log('Primera actualización',await refresh());}catch(e){console.error('COES no respondió:',e.message);}setInterval(()=>refresh().catch(e=>console.error('Actualización fallida:',e.message)),5*60_000).unref();});
