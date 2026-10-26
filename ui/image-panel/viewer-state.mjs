// Browser-only viewport/draft helpers. These never change scientific coordinates.
const copy = value => value === undefined ? undefined : JSON.parse(JSON.stringify(value));
export function zoomAt(view, point, factor, {min=.1,max=16}={}) {
  if(![view.scale,...point,factor].every(Number.isFinite)||view.scale<=0||factor<=0)throw new Error('Invalid viewport');
  const scale=Math.max(min,Math.min(max,view.scale*factor)),ratio=scale/view.scale;
  return {scale,x:point[0]-(point[0]-view.x)*ratio,y:point[1]-(point[1]-view.y)*ratio};
}
export function panBy(view,dx,dy){return {...view,x:view.x+dx,y:view.y+dy};}
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
