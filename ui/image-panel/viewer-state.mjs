// Browser-only viewport/draft helpers. These never change scientific coordinates.
import {transformCoordinates} from './coordinates.mjs';
const copy = value => value === undefined ? undefined : JSON.parse(JSON.stringify(value));
export function equalRecords(a,b){const canonical=v=>Array.isArray(v)?v.map(canonical):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])])):v;return JSON.stringify(canonical(a))===JSON.stringify(canonical(b));}
export function zoomAt(view, point, factor, {min=.1,max=16}={}) {
  if(![view.scale,...point,factor].every(Number.isFinite)||view.scale<=0||factor<=0)throw new Error('Invalid viewport');
  const scale=Math.max(min,Math.min(max,view.scale*factor)),ratio=scale/view.scale;
  return {scale,x:point[0]-(point[0]-view.x)*ratio,y:point[1]-(point[1]-view.y)*ratio};
}
export function panBy(view,dx,dy){return {...view,x:view.x+dx,y:view.y+dy};}
export function relatedViewport(view,previous,next,viewportSize){
  if(!previous||!next)return null;
  if(previous.frame_identity&&next.frame_identity&&previous.frame_identity.frame_object_id!==next.frame_identity.frame_object_id)return null;
  const old=previous.object??previous,current=next.object??next;
  if(old.scientific_grid_identity&&current.scientific_grid_identity&&!equalRecords(old.scientific_grid_identity,current.scientific_grid_identity))return null;
  const pairs=[];
  for(const a of old.panels??[])for(const b of current.panels??[]){
    if(a.source_object_id===b.source_object_id&&a.domain===b.domain&&JSON.stringify(a.fft_shape_yx)===JSON.stringify(b.fft_shape_yx))pairs.push([a,b]);
  }
  // Repeated-source comparison panels have no unique camera correspondence.
  if(pairs.length!==1)return null;
  const [a,b]=pairs[0],centre=viewportSize.map(v=>v/2),pixel=centre.map((v,i)=>(v-(i?view.y:view.x))/view.scale);
  try{
    const source=transformCoordinates(pixel,a),mapped=transformCoordinates(source,b,{inverse:true});
    const [left,top,right,bottom]=b.image_rect_xyxy;
    const sameRegion=JSON.stringify(a.fft_rect_xyxy??a.source_rect_xyxy)===JSON.stringify(b.fft_rect_xyxy??b.source_rect_xyxy);
    // A user may pan the image away from the viewport centre, or open the
    // inspector. The identical scientific region must keep that camera too.
    if(!sameRegion&&(mapped[0]<left||mapped[0]>right||mapped[1]<top||mapped[1]>bottom))return null;
    const probe=transformCoordinates(transformCoordinates([pixel[0]+1,pixel[1]+1],a),b,{inverse:true});
    const factors=probe.map((v,i)=>v-mapped[i]);
    if(factors.some(v=>!Number.isFinite(v)||v<=0)||Math.abs(factors[0]-factors[1])>1e-8*Math.max(...factors))return null;
    const scale=view.scale/factors[0];
    if(!Number.isFinite(scale)||scale<.1||scale>16)return null;
    return {scale,x:centre[0]-mapped[0]*scale,y:centre[1]-mapped[1]*scale};
  }catch{return null;}
}
export function imagePoint(view,point){return [(point[0]-view.x)/view.scale,(point[1]-view.y)/view.scale];}
export function segmentDistance(point,a,b){const dx=b[0]-a[0],dy=b[1]-a[1],den=dx*dx+dy*dy,t=den?Math.max(0,Math.min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/den)):0;return Math.hypot(point[0]-a[0]-t*dx,point[1]-a[1]-t*dy);}
export function hitMark(marks,point,{scale=1,radius=9}={}) {
  // Reverse paint order matches the visible topmost mark. Hidden/retracted
  // candidates cannot steal a click from evidence beneath them.
  for(const mark of [...marks].reverse()){
    if(mark.status==='retracted'||mark.visibility==='outside_view')continue;
    const c=mark.kind==='arrow'?(mark.arrow_render_coordinates??mark.coordinates):mark.coordinates;if(!Array.isArray(c)||c.length<2)continue;
    const pairs=[];for(let i=0;i<c.length;i+=2)pairs.push(c.slice(i,i+2));
    const r=radius/scale,dist=pairs.map(p=>Math.hypot(point[0]-p[0],point[1]-p[1]));
    if(Math.min(...dist)<=r)return {mark,handle:dist.indexOf(Math.min(...dist))};
    if(mark.kind==='rectangle'){
      const [x0,y0,x1,y1]=c,edges=[[[x0,y0],[x1,y0]],[[x1,y0],[x1,y1]],[[x1,y1],[x0,y1]],[[x0,y1],[x0,y0]]];
      if(edges.some(([a,b])=>segmentDistance(point,a,b)<=r))return {mark,handle:-1};
    }else if(pairs.length>1){for(let i=1;i<pairs.length;i++)if(segmentDistance(point,pairs[i-1],pairs[i])<=r)return {mark,handle:-1};if(mark.kind==='polygon'&&segmentDistance(point,pairs.at(-1),pairs[0])<=r)return {mark,handle:-1};}
  }
  return null;
}
export class DraftHistory {
  constructor(initial={},limit=40){this.current=copy(initial);this.undoStack=[];this.redoStack=[];this.limit=limit;this.revision=0;this.saved=JSON.stringify(initial);}
  get dirty(){return JSON.stringify(this.current)!==this.saved;}
  replace(next,{record=true}={}){if(JSON.stringify(next)===JSON.stringify(this.current))return false;if(record){this.undoStack.push(copy(this.current));if(this.undoStack.length>this.limit)this.undoStack.shift();this.redoStack=[];}this.current=copy(next);this.revision++;return true;}
  undo(){if(!this.undoStack.length)return false;this.redoStack.push(copy(this.current));this.current=this.undoStack.pop();this.revision++;return true;}
  redo(){if(!this.redoStack.length)return false;this.undoStack.push(copy(this.current));this.current=this.redoStack.pop();this.revision++;return true;}
  acknowledge(revision){if(this.revision!==revision)return false;this.saved=JSON.stringify(this.current);return true;}
  reset(next={}){this.current=copy(next);this.undoStack=[];this.redoStack=[];this.revision++;this.saved=JSON.stringify(next);}
}
export function internalMarkId(randomId){return 'mark-'+randomId().replaceAll('-','').slice(0,24);}
