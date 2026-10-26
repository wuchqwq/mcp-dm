export const markColors={white:'#ffffff',cyan:'#45e8ff',orange:'#ff8c32',amber:'#ffba30',green:'#00e060'};
export function tonePixels(source,{oldGamma=1,gamma=1,range,low,high}={}){
  const result=new Uint8ClampedArray(source),adjust=range&&Number.isFinite(low)&&Number.isFinite(high)&&high>low;
  if(oldGamma===gamma&&!adjust)return result;
  // This cache runs only after display input changes, never while dragging.
  const lut=new Uint8ClampedArray(256);for(let v=0;v<256;v++){let n=Math.pow(v/255,oldGamma);if(adjust)n=Math.max(0,Math.min(1,(range[0]+n*(range[1]-range[0])-low)/(high-low)));lut[v]=255*Math.pow(n,1/gamma);}
  for(let i=0;i<result.length;i+=4){result[i]=lut[result[i]];result[i+1]=lut[result[i+1]];result[i+2]=lut[result[i+2]];}return result;
}
export function drawMark(ctx,mark,{selected=false,scale=1,draft=false}={}){
 if(mark.status==='retracted'||mark.visibility==='outside_view')return;
 let c=mark.coordinates;
 if(mark.kind==='arrow'){
  if(mark.arrow_render_coordinates)c=mark.arrow_render_coordinates;
  else if(c?.length===4){const [x0,y0,x1,y1]=c,d=Math.hypot(x1-x0,y1-y0),n=mark.arrow_length===null?1:Math.min(1,(mark.arrow_length??24)/d);c=[x1+(x0-x1)*n,y1+(y0-y1)*n,x1,y1];}
 }
 if(!Array.isArray(c)||c.length<2)return;
 ctx.save();ctx.strokeStyle=ctx.fillStyle=markColors[mark.color]??markColors.cyan;ctx.lineWidth=mark.line_width??(mark.kind==='arrow'?3:1);ctx.setLineDash(draft?[4,3]:[]);
 if(mark.kind==='point'){ctx.beginPath();ctx.arc(c[0],c[1],3,0,Math.PI*2);ctx.stroke();}
 else if(mark.kind==='rectangle')ctx.strokeRect(c[0],c[1],c[2]-c[0],c[3]-c[1]);
 else if(mark.kind!=='text'){
  ctx.beginPath();ctx.moveTo(c[0],c[1]);for(let i=2;i<c.length;i+=2)ctx.lineTo(c[i],c[i+1]);if(mark.kind==='polygon')ctx.closePath();ctx.stroke();
  if(mark.kind==='arrow'){const [x0,y0,x1,y1]=c,angle=Math.atan2(y1-y0,x1-x0),size=Math.min(mark.arrowhead_size??6,Math.hypot(x1-x0,y1-y0)/3);ctx.beginPath();ctx.moveTo(x1,y1);for(const a of [-.5,.5])ctx.lineTo(x1-size*Math.cos(angle+a),y1-size*Math.sin(angle+a));ctx.closePath();ctx.fill();}
 }
 if(mark.text){ctx.font='11px system-ui';ctx.fillText(mark.text,c[0]+4,c[1]-4);}
 if(selected){ctx.setLineDash([]);ctx.lineWidth=1/scale;const h=3/scale;for(let i=0;i<mark.coordinates.length;i+=2)ctx.strokeRect(mark.coordinates[i]-h,mark.coordinates[i+1]-h,h*2,h*2);}
 ctx.restore();
}
