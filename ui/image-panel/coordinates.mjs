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
  if(matches.length!==1)throw new Error('Choose a point inside exactly one data panel, away from axes');
  return matches[0];
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
