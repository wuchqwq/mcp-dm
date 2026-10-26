// Optional local, read-only 3Dmol.js presentation of a fixed ASE snapshot.
// No structure engine, remote model download or scientific-coordinate mutation.
// Documented component APIs: https://3dmol.org/doc/GLViewer.html and
// https://3dmol.org/doc/GLModel.html. The optional package is BSD-3-Clause.
import http from 'node:http';
import {randomBytes,timingSafeEqual,createHash} from 'node:crypto';
import {readFileSync,lstatSync,realpathSync,openSync,writeFileSync,fsyncSync,closeSync,linkSync,unlinkSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

export const STRUCTURE_VIEWER_VERSION='2.5.5';
const elements=new Set(('H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og').split(' '));
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const finite=value=>typeof value==='number'&&Number.isFinite(value)&&Math.abs(value)<=1e6;
const own=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).every(k=>keys.includes(k));
function require(value,message){if(!value)throw new Error(message);}
function volume(c){return c[0][0]*(c[1][1]*c[2][2]-c[1][2]*c[2][1])-c[0][1]*(c[1][0]*c[2][2]-c[1][2]*c[2][0])+c[0][2]*(c[1][0]*c[2][1]-c[1][1]*c[2][0]);}
export function validateStructureSnapshot(value){
 require(own(value,['object_id','symbols','positions_angstrom','cell_angstrom','pbc','occupancy']),'Unexpected structure snapshot fields');
 require(typeof value.object_id==='string'&&/^[a-f0-9]{32}$/.test(value.object_id),'An explicit saved structure object_id is required');
 require(Array.isArray(value.symbols)&&value.symbols.length>=1&&value.symbols.length<=4096&&value.symbols.every(s=>typeof s==='string'&&elements.has(s)),'Need 1..4096 valid element symbols');
 require(Array.isArray(value.positions_angstrom)&&value.positions_angstrom.length===value.symbols.length&&value.positions_angstrom.every(p=>Array.isArray(p)&&p.length===3&&p.every(finite)),'Finite bounded Cartesian positions in angstrom required');
 require(Array.isArray(value.cell_angstrom)&&value.cell_angstrom.length===3&&value.cell_angstrom.every(p=>Array.isArray(p)&&p.length===3&&p.every(finite)),'Three finite bounded cell vectors in angstrom required');
 require(Array.isArray(value.pbc)&&value.pbc.length===3&&value.pbc.every(v=>typeof v==='boolean'),'Three explicit periodic boundary flags required');
 const determinant=volume(value.cell_angstrom),hasCell=Number.isFinite(determinant)&&determinant!==0;
 require(!value.pbc.some(Boolean)||hasCell,'Periodic snapshot needs an explicit full-rank cell');
 // Copy only typed scientific data. Never interpolate it into HTML or script.
 // Occupancy metadata stays in the ASE scientific object; these presentation
 // spheres do not encode partial occupancy or infer chemistry/bonds.
 const copy=JSON.parse(JSON.stringify({object_id:value.object_id,symbols:value.symbols,positions_angstrom:value.positions_angstrom,cell_angstrom:value.cell_angstrom,pbc:value.pbc}));
 return {...copy,coordinate_unit:'angstrom',cell_vectors:'rows in the same Cartesian frame as atom positions',cell_drawn:hasCell,atom_count:copy.symbols.length};
}
function ordinary(file,maxBytes){
 require(typeof file==='string'&&path.isAbsolute(file),'An absolute configured local file is required');
 const stat=lstatSync(file);require(stat.isFile()&&!stat.isSymbolicLink()&&stat.size>0&&stat.size<=maxBytes,'Expected a bounded ordinary local file');
 return readFileSync(realpathSync(file));
}
export function read3DmolAsset(assetPath){
 require(typeof assetPath==='string'&&path.isAbsolute(assetPath)&&path.basename(assetPath)==='3Dmol-min.js','Configure the independent 3dmol/build/3Dmol-min.js dependency');
 const bytes=ordinary(assetPath,8*1024*1024),directory=path.dirname(path.dirname(assetPath)),pkg=JSON.parse(ordinary(path.join(directory,'package.json'),64*1024));
 require(path.basename(path.dirname(assetPath))==='build'&&pkg.name==='3dmol'&&pkg.version===STRUCTURE_VIEWER_VERSION&&pkg.license==='BSD-3-Clause','Expected pinned BSD-3-Clause 3dmol@'+STRUCTURE_VIEWER_VERSION);
 const license=ordinary(path.join(directory,'LICENSE'),64*1024);
 return {bytes,license,sha256:sha(bytes),name:'3Dmol.js',version:pkg.version,license_id:pkg.license};
}
const html='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>mcp-dm · ASE 结构</title><link rel="stylesheet" href="/viewer.css"></head><body><header><strong>ASE 结构快照 · 3Dmol.js</strong><button id="reset">重置相机</button><span id="summary"></span></header><p>拖动旋转，滚轮缩放。只改变相机，不修改原子、晶胞或晶向；未推断化学键，也不是电子衍射模拟。</p><div id="viewer" aria-label="只读三维原子结构"></div><p id="message" role="status">正在加载本地 3Dmol.js…</p><details><summary>来源与相机状态</summary><pre id="viewer-status"></pre><pre id="camera-state"></pre><a href="/LICENSE-3Dmol.txt">3Dmol.js · BSD-3-Clause</a></details><script src="/3Dmol-min.js"></script><script type="module" src="/viewer.mjs"></script></body></html>';
const css=':root{font-family:system-ui,sans-serif;background:#f4f5f6;color:#202a33}body{margin:0;padding:12px}header{display:flex;align-items:center;gap:16px;flex-wrap:wrap}button{padding:7px 12px;cursor:pointer}p,summary{font-size:13px}#viewer{position:relative;height:calc(100vh - 190px);min-height:320px;width:100%;background:white}pre{font-size:11px;white-space:pre-wrap;overflow-wrap:anywhere}#message{color:#34596b}';
const script=`const $=id=>document.getElementById(id),key='mcp-dm-structure-view-token',hash=location.hash.slice(1);
if(hash){sessionStorage.setItem(key,hash);history.replaceState(null,'',location.pathname);}const token=sessionStorage.getItem(key);
try{
 const response=await fetch('/api/structure',{headers:{'X-Viewer-Token':token}}),data=await response.json();if(!response.ok)throw new Error(data.error??'读取结构失败');
 if(!globalThis.$3Dmol?.createViewer)throw new Error('本地 3Dmol.js 未就绪；不将二维投影冒充三维显示');
 const structure=data.structure,viewer=$3Dmol.createViewer('viewer',{backgroundColor:'white'}),model=viewer.addModel();
 model.addAtoms(structure.symbols.map((elem,i)=>({elem,x:structure.positions_angstrom[i][0],y:structure.positions_angstrom[i][1],z:structure.positions_angstrom[i][2],serial:i+1,bonds:[],bondOrder:[]})));
 viewer.setStyle({},{sphere:{scale:.35}});
 if(structure.cell_drawn){const [a,b,c]=structure.cell_angstrom;model.setCrystMatrix(new $3Dmol.Matrix3(a[0],b[0],c[0],a[1],b[1],c[1],a[2],b[2],c[2]));viewer.addUnitCell(model,{box:{color:'#65747d'},alabel:'a',blabel:'b',clabel:'c'});}
 viewer.zoomTo();viewer.render();const initial=viewer.getView();
 const camera=()=>{$('camera-state').textContent=JSON.stringify({camera_only:true,translation_zoom_quaternion:viewer.getView(),scientific_coordinates_changed:false});};viewer.setViewChangeCallback(camera);camera();
 $('reset').onclick=()=>{viewer.setView(initial);viewer.render();camera();};window.addEventListener('resize',()=>{viewer.resize();viewer.render();});
 $('summary').textContent=structure.atom_count+' 个原子 · Å · '+(structure.cell_drawn?'有晶胞':'无三维晶胞');
 $('viewer-status').textContent=JSON.stringify({state:'rendered',renderer:data.renderer,object_id:structure.object_id,atom_count:structure.atom_count,cell_drawn:structure.cell_drawn,pbc:structure.pbc,snapshot_sha256:data.snapshot_sha256,camera_only:true,scientific_coordinates_changed:false});
 $('message').textContent='只读三维显示已就绪。相机旋转不代表已把结构按某个晶带轴定向。';
}catch(error){$('message').textContent=error.message;$('viewer-status').textContent=JSON.stringify({state:'not_rendered',interactive_3d:false,error:error.message});}`;

export async function createStructureViewer({structure,assetPath,port=0}={}){
 const snapshot=validateStructureSnapshot(structure),asset=read3DmolAsset(assetPath);
 require(Number.isInteger(port)&&port>=0&&port<=65535,'Invalid loopback port');
 const token=randomBytes(24).toString('hex'),snapshotBytes=Buffer.from(JSON.stringify(snapshot)),snapshotHash=sha(snapshotBytes);
 const renderer={name:asset.name,version:asset.version,license:asset.license_id,asset_sha256:asset.sha256,mode:'local WebGL, camera only; no model edits'};
 const server=http.createServer((req,res)=>{
  res.setHeader('X-Content-Type-Options','nosniff');res.setHeader('Referrer-Policy','no-referrer');res.setHeader('Cache-Control','no-store');res.setHeader('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'");
  try{
   const origin='http://127.0.0.1:'+server.address().port;
   if(req.headers.host!=='127.0.0.1:'+server.address().port){res.statusCode=403;throw new Error('Invalid Host');}
   if(req.headers.origin&&req.headers.origin!==origin){res.statusCode=403;throw new Error('Cross-origin request refused');}
   const url=new URL(req.url,origin);if(req.method!=='GET'){res.statusCode=405;throw new Error('Read-only viewer');}
   const files=new Map([['/',[html,'text/html; charset=utf-8']],['/viewer.css',[css,'text/css; charset=utf-8']],['/viewer.mjs',[script,'text/javascript; charset=utf-8']],['/3Dmol-min.js',[asset.bytes,'text/javascript; charset=utf-8']],['/LICENSE-3Dmol.txt',[asset.license,'text/plain; charset=utf-8']]]);
   if(files.has(url.pathname)){const [bytes,type]=files.get(url.pathname);res.setHeader('Content-Type',type);res.end(bytes);return;}
   if(url.pathname!=='/api/structure'||url.search){res.statusCode=404;throw new Error('Not found');}
   const supplied=req.headers['x-viewer-token'];if(typeof supplied!=='string'||Buffer.byteLength(supplied)!==Buffer.byteLength(token)||!timingSafeEqual(Buffer.from(supplied),Buffer.from(token))){res.statusCode=403;throw new Error('Viewer token required');}
   res.setHeader('Content-Type','application/json');res.end(JSON.stringify({schema_version:1,structure:snapshot,snapshot_sha256:snapshotHash,renderer,read_only:true}));
  }catch(error){if(res.statusCode===200)res.statusCode=400;res.setHeader('Content-Type','application/json');res.end(JSON.stringify({error:error.message}));}
 });
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,'127.0.0.1',resolve);});
 return {url:'http://127.0.0.1:'+server.address().port+'/#'+token,token,server,renderer,object_id:snapshot.object_id,snapshot_sha256:snapshotHash,async close(){await new Promise(resolve=>server.close(resolve));}};
}
function writeNew(file,value){require(typeof file==='string'&&path.isAbsolute(file),'New absolute connection path required');const temp=file+'.'+randomBytes(8).toString('hex')+'.tmp',fd=openSync(temp,'wx');try{writeFileSync(fd,JSON.stringify(value));fsyncSync(fd);}finally{closeSync(fd);}try{linkSync(temp,file);}finally{unlinkSync(temp);}}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const args={};for(let i=2;i<process.argv.length;i+=2){const key=process.argv[i],value=process.argv[i+1];require(['--snapshot','--asset','--connection-file','--port'].includes(key)&&value&&!Object.hasOwn(args,key),'Usage: --snapshot ABS_JSON --asset ABS_3DMOL_BUNDLE --connection-file ABS_NEW_JSON [--port 0]');args[key]=value;}
 const structure=JSON.parse(ordinary(args['--snapshot'],2*1024*1024));let viewer;
 try{viewer=await createStructureViewer({structure,assetPath:args['--asset'],port:Number(args['--port']??0)});writeNew(args['--connection-file'],{schema_version:1,port:viewer.server.address().port,token:viewer.token,pid:process.pid,object_id:viewer.object_id,snapshot_sha256:viewer.snapshot_sha256,renderer:viewer.renderer});}
 catch(error){if(viewer)await viewer.close();throw error;}
 process.stdout.write(JSON.stringify({url:viewer.url,object_id:viewer.object_id,renderer:viewer.renderer})+'\n');let closing=false;const close=async()=>{if(!closing){closing=true;await viewer.close();}};process.on('SIGINT',close);process.on('SIGTERM',close);
}
