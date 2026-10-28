// Mirrors the public panels centre/edge contract; never infers a new grid.
export function coordinateSpace(panel) {
  return ({frequency:'frequency_cycles_per_pixel',spatial_pixels:'source_pixels',source_array_indices:'source_array_indices'})[panel.domain];
}
export function transformCoordinates(values,panel,{edges=false,inverse=false}={}) {
  if(!Array.isArray(values)||values.length%2||!values.every(Number.isFinite))throw new Error('Finite xy pairs required');
  const [left,top,right,bottom]=panel.image_rect_xyxy;
  const frequency=panel.domain==='frequency';
  const [h,w]=frequency?panel.fft_shape_yx:[0,0];
  const [x0,y0,x1,y1]=frequency?(panel.fft_rect_xyxy??[0,0,w,h]):panel.source_rect_xyxy;
  const starts=[left,top],sizes=[right-left,bottom-top],source0=[x0,y0],extent=[x1-x0,y1-y0],grid=[w,h];
  if(!sizes.every(v=>Number.isFinite(v)&&v>0)||!extent.every(v=>Number.isFinite(v)&&v>0))throw new Error('Invalid panel extent');
  return values.map((value,i)=>{
    const axis=i%2,centre=(!edges||frequency)?.5:0,imageCentre=edges?0:.5;
    const offset=frequency?-Math.floor(grid[axis]/2):0;
    if(inverse){const local=frequency?value*grid[axis]-offset:value;return starts[axis]+(local-source0[axis]+centre)*sizes[axis]/extent[axis]-imageCentre;}
    const local=source0[axis]+(value-starts[axis]+imageCentre)*extent[axis]/sizes[axis]-centre;
    return frequency?(local+offset)/grid[axis]:local;
  });
}
export function panelAt(panels,x,y,{edges=false}={}) {
  const matches=panels.filter(p=>{const [l,t,r,b]=p.image_rect_xyxy;return x>=l&&y>=t&&x<=(edges?r:r-1)&&y<=(edges?b:b-1);});
  if(matches.length!==1)throw new Error('请在图像内部的单一数据区域选点或拖动，避开坐标轴和图外空白');
  return matches[0];
}
export function constrainSelectionDrag(panel,start,end,{kind,constrained=false}={}) {
  if(!constrained||!['rectangle','line','arrow'].includes(kind))return {start:[...start],end:[...end]};
  const edges=kind==='rectangle',frequency=panel.domain==='frequency',grid=frequency?[panel.fft_shape_yx[1],panel.fft_shape_yx[0]]:null;
  const toGrid=values=>transformCoordinates(values,panel,{edges}).map((v,i)=>frequency?v*grid[i%2]+Math.floor(grid[i%2]/2)+(edges?.5:0):v);
  const fromGrid=values=>transformCoordinates(values.map((v,i)=>frequency?(v-Math.floor(grid[i%2]/2)-(edges?.5:0))/grid[i%2]:v),panel,{edges,inverse:true});
  const [l,t,r,b]=panel.image_rect_xyxy,bounds=toGrid([l,t,r-(edges?0:1),b-(edges?0:1)]),origin=toGrid(start),cursor=toGrid(end);
  let first=[...origin],last=[...cursor];
  if(edges){
    // An explicitly constrained ROI uses integer source-pixel/FFT-bin edges,
    // so the processing rectangle is square after its normal edge conversion.
    first=origin.map((v,i)=>Math.max(Math.ceil(bounds[i]-1e-9),Math.min(Math.floor(bounds[i+2]+1e-9),Math.round(v))));
    const direction=cursor.map((v,i)=>v<origin[i]?-1:1);
    const requested=Math.round(Math.max(...cursor.map((v,i)=>Math.abs(v-first[i]))));
    const side=Math.max(0,Math.min(requested,...first.map((v,i)=>direction[i]>0?Math.floor(bounds[i+2]+1e-9)-v:v-Math.ceil(bounds[i]-1e-9))));
    last=first.map((v,i)=>v+direction[i]*side);
  }else{
    const axis=Math.abs(cursor[0]-origin[0])>=Math.abs(cursor[1]-origin[1])?0:1;
    last=[...origin];last[axis]=Math.max(bounds[axis],Math.min(bounds[axis+2],cursor[axis]));
  }
  const rendered=fromGrid([...first,...last]).map((v,i)=>Math.max(i%2?t:l,Math.min(i%2?b-(edges?0:1):r-(edges?0:1),v)));
  return {start:rendered.slice(0,2),end:rendered.slice(2)};
}
export function selectionFromDrag(panels,start,end,{kind='point'}={}) {
  const edges=['rectangle','polygon'].includes(kind),p=panelAt(panels,...start,{edges});
  if(panelAt(panels,...end,{edges})!==p)throw new Error('Selection must stay in one source panel');
  let coords=kind==='point'?start:[...start,...end];
  if(kind==='rectangle')coords=[Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.max(start[0],end[0]),Math.max(start[1],end[1])];
  return {kind,coordinate_space:coordinateSpace(p),source_object_id:p.source_object_id,coordinates:transformCoordinates(coords,p,{edges}),panel:p};
}
export function selectionRectangle(selection) {
  if(selection.kind!=='rectangle')throw new Error('Draw a rectangle first');
  const p=selection.panel,c=selection.coordinates;
  // Explicit outward integer-bin/edge snapping. The UI shows this rectangle
  // before submission; fractional scientific annotations remain unsnapped.
  const bins=p.domain==='frequency'?c.map((v,i)=>v*p.fft_shape_yx[i%2===0?1:0]+Math.floor(p.fft_shape_yx[i%2===0?1:0]/2)+.5):c;
  const rect=[Math.floor(bins[0]+1e-9),Math.floor(bins[1]+1e-9),Math.ceil(bins[2]-1e-9),Math.ceil(bins[3]-1e-9)];
  const bounds=p.domain==='frequency'?(p.fft_rect_xyxy??[0,0,p.fft_shape_yx[1],p.fft_shape_yx[0]]):p.source_rect_xyxy;
  if(rect[0]<bounds[0]||rect[1]<bounds[1]||rect[2]>bounds[2]||rect[3]>bounds[3]||rect[0]>=rect[2]||rect[1]>=rect[3])throw new Error('Selection exceeds current data window');
  return rect;
}
