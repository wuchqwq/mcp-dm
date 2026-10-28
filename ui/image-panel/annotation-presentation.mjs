// Shared, deterministic presentation only. Input anchors and scientific values stay read-only.
const SHAPES = new Set(['circle', 'square', 'double_circle', 'diamond', 'cross']);
const COLORS = {white:'#f1f4f5',cyan:'#79d9ee',orange:'#efad79',amber:'#e5c46b',green:'#a1d2a1'};
const CATEGORIES = {A:{color:'#79d9ee',shape:'circle',label:'Domain A'},B:{color:'#efad79',shape:'square',label:'Domain B'},shared:{color:'#f1f4f5',shape:'double_circle',label:'Shared'},unexplained:{color:'#e4e7eb',shape:'diamond',label:'Unexplained'}};
const PRESETS = new Set(['real-space', 'diffraction', 'multi-domain']);
const finite = (value, fallback) => Number.isFinite(value) ? value : fallback;
const bounded = (value, fallback, min, max) => Math.max(min,Math.min(max,finite(value,fallback)));
const xml = value => String(value??'').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/g,'�').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
const number = value => String(Math.round(finite(value,0)*1000)/1000);
const colorValue = (value, fallback) => COLORS[value] ?? (/^#[a-f\d]{3}(?:[a-f\d]{3})?$/i.test(String(value)) ? value : fallback);
const subscripts = '₀₁₂₃₄₅₆₇₈₉';

export function presentationText(value) {
 return String(value??'').replace(/\$([^$]*)\$/g,'$1').replace(/\\langle\b/g,'⟨').replace(/\\rangle\b/g,'⟩').replace(/\bg_\{(\d+)\}/g,'g$1').replace(/\s*\((?:hyp\.?|hypothesized|hypothesis)\)\s*/gi,' ').replace(/\bg_?(\d+)\b/g,(_,digits)=>'g'+[...digits].map(d=>subscripts[Number(d)]).join('')).replace(/\s+/g,' ').trim();
}

// Compact three/four index notation is unambiguous only for single digit indices.
// Space-separated indices can contain multiple digits. No indices are inferred.
function indices(body) {
 const normalized=body.replace(/\\(?:bar|overline)\{(\d+)\}/g,'-$1').replace(/−/g,'-').trim();
 if(!/^[\d+\-\s,]+$/.test(normalized))return null;
 const tokens=/[\s,]/.test(normalized)?normalized.split(/[\s,]+/):normalized.match(/[+\-]?\d/g);
 if(!tokens||![3,4].includes(tokens.length)||tokens.some(t=>!/^[-+]?\d+$/.test(t)))return null;
 return tokens;
}

export function crystallographicSVGText(value) {
 const text=presentationText(value), groups=/(d_)?([({\[<⟨])((?:[\d+\-−\s,]|\\(?:bar|overline)\{\d+\})+)([)}\]>⟩])/g;
 const inline=value=>{let result='',cursor=0,match;const bars=/\\(?:bar|overline)\{(\d+)\}/g;while((match=bars.exec(value))){result+=xml(value.slice(cursor,match.index))+`<tspan text-decoration="overline">${xml(match[1])}</tspan>`;cursor=match.index+match[0].length;}return result+xml(value.slice(cursor));};
 let result='',cursor=0,match;
 const renderGroup=(left,body,right)=>{
  const expected={'(':')','{':'}','[':']','<':'>','⟨':'⟩'}[left],tokens=indices(body);
  if(expected!==right||!tokens)return xml(left+body+right);
  const separator=/[\s,]/.test(body)?' ':'';
  return xml(left==='<'?'⟨':left)+tokens.map(token=>token.startsWith('-')?`<tspan text-decoration="overline">${xml(token.slice(1))}</tspan>`:xml(token.replace(/^\+/,''))).join(separator)+xml(right==='>'?'⟩':right);
 };
 while((match=groups.exec(text))){
  const prefix=text.slice(cursor,match.index);
  if(/\\(?:bar|overline)$/.test(prefix)&&match[2]==='{'){
   result+=inline(prefix+match[0]);cursor=match.index+match[0].length;continue;
  }
  result+=inline(prefix);
  if(match[1])result+=`d<tspan baseline-shift="sub" font-size="75%">${renderGroup(match[2],match[3],match[4])}</tspan>`;
  else result+=renderGroup(match[2],match[3],match[4]);
  cursor=match.index+match[0].length;
 }
 return result+inline(text.slice(cursor));
}

function boxOverlap(a,b){return Math.max(0,Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x))*Math.max(0,Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y));}
function labelExtent(text,fontSize){return {width:Math.max(fontSize*.7,[...text].reduce((sum,c)=>sum+(/[il1.,' ]/.test(c)?.32:/[MW@]/.test(c)?.86:.59),0)*fontSize),height:fontSize*1.25};}
function candidates(anchor,extent,gap){const [x,y]=anchor,{width:w,height:h}=extent;return [[x+gap,y-h-gap],[x+gap,y+gap],[x-w-gap,y-h-gap],[x-w-gap,y+gap],[x-w/2,y-h-gap],[x-w/2,y+gap],[x+gap,y-h/2],[x-w-gap,y-h/2]];}
function place(anchor,extent,gap,width,height,placed,points){
 let best=null;
 for(const [cx,cy]of candidates(anchor,extent,gap)){
  const box={x:Math.max(0,Math.min(Math.max(0,width-extent.width),cx)),y:Math.max(0,Math.min(Math.max(0,height-extent.height),cy)),...extent};
  const overlap=placed.reduce((sum,other)=>sum+boxOverlap(box,other),0);
  const pointPenalty=points.reduce((sum,[x,y])=>sum+(x>box.x-gap*.4&&x<box.x+box.width+gap*.4&&y>box.y-gap*.4&&y<box.y+box.height+gap*.4?extent.height*extent.height:0),0);
  const score=overlap*4+pointPenalty+Math.abs(box.x-cx)+Math.abs(box.y-cy);
  if(!best||score<best.score)best={...box,score,overlap};
 }
 return best;
}

/** Marks have already been transformed to render pixels by the caller. */
export function layoutAnnotations(marks=[],options={}) {
 const preset=PRESETS.has(options.preset)?options.preset:'real-space',mode=options.mode==='figure'?'figure':'analysis';
 const scale=bounded(options.scale,1,.000001,1000000),width=bounded(options.width,1024,1,1000000),height=bounded(options.height,1024,1,1000000);
 const layers=options.layers??{},items=[],legendMap=new Map(),suggestedUpdates=[];let categorySimulation=false;
 const validMarks=marks.filter(mark=>mark&&Array.isArray(mark.coordinates)&&mark.coordinates.length>=2&&mark.coordinates.every(Number.isFinite));
 const anchors=validMarks.filter(mark=>mark.kind==='point').map(mark=>mark.coordinates.slice(0,2));
 let peakNumber=0;
 for(const mark of validMarks){
  const p=mark.presentation??{},lp=p.label??{},category=CATEGORIES[p.category]?p.category:'none',categoryStyle=CATEGORIES[category];
  const layer=['experimental','simulation_A','simulation_B'].includes(p.layer)?p.layer:'experimental';
  const hidden=mark.status==='retracted'||mark.visibility==='outside_view';
  const layerVisible=layers[layer]!==false||category==='unexplained';
  const geometryVisible=!hidden&&layerVisible&&p.geometry_visible!==false;
  const id=mark.annotation_id??mark.id,selected=mode==='analysis'&&id===options.selectedId,hovered=mode==='analysis'&&id===options.hoverId;
  const baseColor=preset==='multi-domain'&&categoryStyle?categoryStyle.color:colorValue(mark.color,COLORS.white);
  const color=category==='unexplained'?CATEGORIES.unexplained.color:baseColor;
  const shape=SHAPES.has(p.marker_shape)?p.marker_shape:layer!=='experimental'?'cross':categoryStyle&&preset==='multi-domain'?categoryStyle.shape:'circle';
  const radius=bounded(p.marker_radius,preset==='real-space'?3.5:5,.1,100)/scale,lineWidth=bounded(p.line_width,mark.kind==='arrow'?1.4:1,.05,32)/scale;
  const anchor=mark.coordinates.slice(0,2),hasManualOffset=Array.isArray(lp.offset)&&lp.offset.length===2&&lp.offset.every(Number.isFinite);
  if(mark.kind==='point')peakNumber++;
  const originalText=lp.text??mark.text??'',text=presentationText(originalText)||(lp.text===undefined&&mark.kind==='point'&&preset!=='real-space'?'g'+String(peakNumber).split('').map(d=>subscripts[Number(d)]).join(''):'');
  const fontSize=bounded(lp.font_size,preset==='real-space'?12:11,1,256)/scale,extent=labelExtent(text,fontSize),important=lp.important===true||mark.kind==='text';
  const label={text,x:anchor[0],y:anchor[1],...extent,fontSize,leader:lp.leader!==false,pinned:lp.pinned===true,visible:!hidden&&layerVisible&&lp.visible!==false&&Boolean(text),offset:hasManualOffset?[...lp.offset]:null,important};
  if(mode==='figure'&&lp.figure_visible===false)label.visible=false;
  if(preset==='real-space'&&text.length>22&&!important&&!selected&&!hovered)label.visible=false;
  const item={id,mark,shape,color,radius,lineWidth,geometryVisible,selected,hovered,layer,category,anchor,coordinates:[...mark.coordinates],dash:layer==='experimental'?[]:[3/scale,2.5/scale],label};
  items.push(item);
  if(!hidden&&layerVisible){
   const status=mark.status==='user_confirmed'?'user_confirmed':mark.status==='hypothesized'||/\((?:hyp\.?|hypothesized|hypothesis)\)/i.test(String(originalText))?'hypothesized':'';
   const key=[category,category==='none'?layer:'',status].join(':');
   const baseLabel=categoryStyle?.label??(layer==='experimental'?'Experimental observation':layer==='simulation_A'?'Simulation A':'Simulation B');
   const labelText=baseLabel+(status==='hypothesized'?' · candidate':status==='user_confirmed'?' · confirmed':'');
   if(category!=='none'&&layer!=='experimental')categorySimulation=true;
   if((category!=='none'||layer!=='experimental'||status)&&(!legendMap.has(key)||layer==='experimental'))legendMap.set(key,{key,label:labelText,color,shape,status,layer,dash:category==='none'?item.dash:[]});
  }
 }
 // Pinned labels have precedence; stable source order prevents hover-induced jumps.
 const placed=[];
 const ordered=[...items.filter(i=>i.label.pinned),...items.filter(i=>!i.label.pinned&&i.label.important),...items.filter(i=>!i.label.pinned&&!i.label.important)];
 for(const item of ordered){
  const {label,anchor}=item,lp=item.mark.presentation?.label??{},manual=label.offset&&(!options.arrange||label.pinned);
  if(manual){label.x=anchor[0]+label.offset[0];label.y=anchor[1]+label.offset[1];}
  else {
   const box=place(anchor,label,item.radius+4/scale,width,height,placed,anchors);
   label.x=box.x;label.y=box.y;label.offset=[label.x-anchor[0],label.y-anchor[1]];
   if(label.visible&&box.overlap>label.width*label.height*.1&&!label.important&&!item.selected&&!item.hovered)label.visible=false;
   if(options.arrange&&!label.pinned&&(!lp.offset||label.offset.some((v,i)=>Math.abs(v-lp.offset[i])>.01)))suggestedUpdates.push({id:item.id,presentation:{...item.mark.presentation,label:{...lp,offset:[...label.offset],pinned:false}}});
  }
  if(label.visible)placed.push(label);
 }
 if(categorySimulation)legendMap.set('simulated',{key:'simulated',label:'Simulated reflection',color:COLORS.white,shape:'cross',status:'',layer:'simulation',dash:[3/scale,2.5/scale]});
 return {items,legend:[...legendMap.values()],suggestedUpdates,mode,preset,scale,width,height};
}

function shapeSVG(shape,x,y,r,color,lineWidth,dash=''){
 const attrs=`fill="none" stroke="${xml(color)}" stroke-width="${number(lineWidth)}"${dash?` stroke-dasharray="${xml(dash)}"`:''}`;
 if(shape==='square')return `<rect x="${number(x-r)}" y="${number(y-r)}" width="${number(r*2)}" height="${number(r*2)}" ${attrs}/>`;
 if(shape==='diamond')return `<path d="M ${number(x)} ${number(y-r)} L ${number(x+r)} ${number(y)} L ${number(x)} ${number(y+r)} L ${number(x-r)} ${number(y)} Z" ${attrs}/>`;
 if(shape==='cross')return `<path d="M ${number(x-r)} ${number(y)} H ${number(x+r)} M ${number(x)} ${number(y-r)} V ${number(y+r)}" ${attrs}/>`;
 return `<circle cx="${number(x)}" cy="${number(y)}" r="${number(r)}" ${attrs}/>`+(shape==='double_circle'?`<circle cx="${number(x)}" cy="${number(y)}" r="${number(r*1.55)}" ${attrs}/>`:'');
}

function geometrySVG(item){
 const {mark,color,lineWidth,radius,shape}=item,c=mark.kind==='arrow'&&mark.arrow_render_coordinates?.every(Number.isFinite)?mark.arrow_render_coordinates:item.coordinates;
 const dash=item.dash.map(number).join(' '),attrs=`fill="none" stroke="${xml(color)}" stroke-width="${number(lineWidth)}" stroke-linecap="round" stroke-linejoin="round"${dash?` stroke-dasharray="${dash}"`:''}`;
 if(mark.kind==='point')return shapeSVG(shape,c[0],c[1],radius,color,lineWidth,dash);
 if(mark.kind==='text')return '';
 if(mark.kind==='rectangle'&&c.length===4)return `<rect x="${number(Math.min(c[0],c[2]))}" y="${number(Math.min(c[1],c[3]))}" width="${number(Math.abs(c[2]-c[0]))}" height="${number(Math.abs(c[3]-c[1]))}" ${attrs}/>`;
 let result=`<${mark.kind==='polygon'?'polygon':'polyline'} points="${c.map(number).join(' ')}" ${attrs}/>`;
 if(mark.kind==='arrow'&&c.length===4){const dx=c[2]-c[0],dy=c[3]-c[1],distance=Math.hypot(dx,dy);if(distance){const ux=dx/distance,uy=dy/distance,size=Math.min(radius*1.5,distance/3),bx=c[2]-ux*size,by=c[3]-uy*size;result+=`<path d="M ${number(bx-uy*size*.45)} ${number(by+ux*size*.45)} L ${number(c[2])} ${number(c[3])} L ${number(bx+uy*size*.45)} ${number(by-ux*size*.45)}" ${attrs}/>`;}}
 return result;
}

/** SVG contains only escaped text and a fixed vocabulary of SVG elements/attributes. */
export function renderAnnotationsSVG(layout,{width=layout.width,height=layout.height,includeRoot=true,interactive=false,figureLayout={}}={}) {
 width=bounded(width,layout.width,1,1000000);height=bounded(height,layout.height,1,1000000);
 const scale=layout.scale??1,fontFamily='Arial, Helvetica, sans-serif';let content='';
 for(const item of layout.items){
  const {label,anchor,mark}=item,id=xml(item.id),part=interactive?` data-annotation-id="${id}"`:'';
  if(item.geometryVisible)content+=`<g${part} data-part="geometry"><title>${xml([mark.text??label.text,mark.status].filter(Boolean).join(' · '))}</title>${geometrySVG(item)}</g>`;
  if(label.visible){
   const near=[Math.max(label.x,Math.min(label.x+label.width,anchor[0])),Math.max(label.y,Math.min(label.y+label.height,anchor[1]))];
   if(label.leader&&Math.hypot(near[0]-anchor[0],near[1]-anchor[1])>item.radius+3/scale)content+=`<path d="M ${number(anchor[0])} ${number(anchor[1])} L ${number(near[0])} ${number(near[1])}" fill="none" stroke="${xml(item.color)}" stroke-width="${number(.65/scale)}" opacity="0.78" pointer-events="none"/>`;
   content+=`<g${part} data-part="label"${interactive?' style="cursor:move"':''}><title>${xml([mark.text??label.text,mark.status].filter(Boolean).join(' · '))}</title>${interactive?`<rect x="${number(label.x-2/scale)}" y="${number(label.y-2/scale)}" width="${number(label.width+4/scale)}" height="${number(label.height+4/scale)}" fill="transparent"/>`:''}<text x="${number(label.x)}" y="${number(label.y+label.fontSize)}" fill="${xml(item.color)}" font-family="${fontFamily}" font-size="${number(label.fontSize)}" font-weight="400" stroke="#11151b" stroke-width="${number(.6/scale)}" stroke-opacity="0.7" paint-order="stroke fill" stroke-linejoin="round">${crystallographicSVGText(label.text)}</text></g>`;
  }
  if(layout.mode==='analysis'&&item.selected&&item.geometryVisible){const r=3/scale;content+=`<g data-part="handles" pointer-events="none" fill="#11151b" stroke="${xml(item.color)}" stroke-width="${number(1/scale)}">`;for(let i=0;i<item.coordinates.length;i+=2)content+=`<rect x="${number(item.coordinates[i]-r)}" y="${number(item.coordinates[i+1]-r)}" width="${number(r*2)}" height="${number(r*2)}"/>`;content+='</g>';}
 }
 const fs=bounded(figureLayout.fontSize,layout.items.find(item=>item.label.text)?.label.fontSize??11/scale,1/scale,256/scale),padding=fs*.8;
 if(figureLayout.letter){content+=`<text data-part="panel-letter" x="${number(padding)}" y="${number(padding+fs*1.25)}" fill="#f1f4f5" font-family="${fontFamily}" font-size="${number(fs*1.25)}" font-weight="600" stroke="#11151b" stroke-width="${number(1/scale)}" paint-order="stroke fill">${xml(figureLayout.letter)}</text>`;}
 if(figureLayout.legend!==false&&figureLayout.showLegend!==false&&layout.legend.length){
  const font=bounded(figureLayout.legendFontSize,Math.min(fs,9/scale),1/scale,256/scale),gap=font*1.55,columns=figureLayout.legendColumns===2?2:1,columnWidth=columns===2?layout.width/2-padding:Math.max(...layout.legend.map(row=>labelExtent(row.label,font).width))+font*2.55,maxWidth=columnWidth*columns;
  const x=finite(figureLayout.legendX,padding),y=finite(figureLayout.legendY,padding+(figureLayout.letter?fs*2:0)),legendHeight=Math.ceil(layout.legend.length/columns)*gap+padding;
  content+=`<g data-part="legend" pointer-events="none"><rect x="${number(x)}" y="${number(y)}" width="${number(maxWidth+padding)}" height="${number(legendHeight)}" rx="${number(3/scale)}" fill="#11151b" fill-opacity="0.78"/>`;
  layout.legend.forEach((row,i)=>{const lx=x+(i%columns)*columnWidth,cy=y+padding+Math.floor(i/columns)*gap+font*.5;content+=shapeSVG(row.shape,lx+padding+font*.36,cy,font*.31,row.color,.9/scale,(row.dash??[]).map(number).join(' '))+`<text x="${number(lx+padding+font*1.45)}" y="${number(cy+font*.33)}" fill="#f1f4f5" font-family="${fontFamily}" font-size="${number(font)}">${xml(row.label)}</text>`;});content+='</g>';
 }
 const bar=figureLayout.scaleBar;
 if(bar&&Number.isFinite(bar.x)&&Number.isFinite(bar.y)&&Number.isFinite(bar.length)&&bar.length>0){
  const color=colorValue(bar.color,COLORS.white),x=bar.x,y=bar.y,end=x+bar.length,barFont=bounded(bar.font_size,fs*scale,1,256)/scale;
  content+=`<g data-part="scale-bar" fill="${xml(color)}" stroke="${xml(color)}"><path d="M ${number(x)} ${number(y)} H ${number(end)}" stroke-width="${number(3/scale)}"/><text x="${number((x+end)/2)}" y="${number(y-6/scale)}" text-anchor="middle" stroke="none" font-family="${fontFamily}" font-size="${number(barFont)}">${xml(bar.label??'')}</text></g>`;
 }
 return includeRoot?`<svg xmlns="http://www.w3.org/2000/svg" width="${number(width)}" height="${number(height)}" viewBox="0 0 ${number(layout.width)} ${number(layout.height)}" role="img" aria-label="Scientific annotations">${content}</svg>`:content;
}
