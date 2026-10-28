import test from 'node:test';
import assert from 'node:assert/strict';
import {layoutAnnotations,renderAnnotationsSVG,presentationText,crystallographicSVGText} from '../ui/image-panel/annotation-presentation.mjs';

const point=(id,coordinates=[80,90],presentation={},text='')=>({annotation_id:id,kind:'point',coordinates,text,status:'hypothesized',color:'white',anchor:{source_object_id:'source',coordinates:[12.2,40.6]},presentation});
const options={width:400,height:300,preset:'diffraction'};
const overlap=(a,b)=>Math.max(0,Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x))*Math.max(0,Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y));

test('presentation keeps scientific anchors, confirmation, and source objects read-only',()=>{
 const marks=[point('actual-annotation-id',[45.25,71.125],{label:{text:'(1 -1 0)',offset:[8,-20],pinned:true}},'old text')];
 marks[0].status='user_confirmed';const before=structuredClone(marks);
 const layout=layoutAnnotations(marks,{...options,selectedId:'actual-annotation-id'});
 assert.equal(layout.items[0].id,'actual-annotation-id');assert.equal(layout.items[0].selected,true);
 assert.deepEqual(layout.items[0].anchor,[45.25,71.125]);assert.equal(layout.items[0].label.text,'(1 -1 0)');
 assert.deepEqual(layout.items[0].label.offset,[8,-20]);assert.deepEqual([layout.items[0].label.x,layout.items[0].label.y],[53.25,51.125]);
 renderAnnotationsSVG(layout,{interactive:true});assert.deepEqual(marks,before);
 assert.ok(layout.legend.some(row=>row.status==='user_confirmed'));assert.equal(marks[0].text,'old text');
});

test('multi-domain preset uses shape and colour, central status legend, and honest blank peak labels',()=>{
 const marks=['A','B','shared','unexplained'].map((category,i)=>point(category,[50+i*85,100],{category},i?'':'(1 -1 0) (hyp.)'));
 const layout=layoutAnnotations(marks,{...options,preset:'multi-domain'});
 assert.deepEqual(layout.items.map(item=>item.shape),['circle','square','double_circle','diamond']);
 assert.notEqual(layout.items[0].color,layout.items[1].color);assert.equal(layout.items[2].color,'#f1f4f5');
 assert.equal(layout.items[0].label.text,'(1 -1 0)');assert.deepEqual(layout.items.slice(1).map(item=>item.label.text),['g₂','g₃','g₄']);
 assert.equal(layout.legend.length,4);assert.ok(layout.legend.every(row=>row.status==='hypothesized'));
 assert.equal(layout.items.some(item=>/hyp/.test(item.label.text)),false);
 const real=layoutAnnotations([point('blank')],{...options,preset:'real-space'});assert.equal(real.items[0].label.visible,false);assert.equal(real.items[0].color,'#f1f4f5');
});

test('CSS visual sizes survive zoom; pinned offset stays in base render coordinates',()=>{
 const mark=point('peak',[90,100],{marker_radius:6,line_width:1.2,label:{text:'g1',font_size:12,offset:[30,15],pinned:true}});
 const normal=layoutAnnotations([mark],options).items[0],zoom=layoutAnnotations([mark],{...options,scale:3}).items[0];
 for(const name of ['radius','lineWidth'])assert.equal(zoom[name]*3,normal[name]);
 assert.equal(zoom.label.fontSize*3,normal.label.fontSize);assert.deepEqual(zoom.label.offset,normal.label.offset);
 assert.deepEqual([zoom.label.x,zoom.label.y],[normal.label.x,normal.label.y]);assert.equal(zoom.label.text,'g₁');
 const small=layoutAnnotations([point('export',[5,5],{label:{text:'A',font_size:4.25}})],options);assert.equal(small.items[0].label.fontSize,4.25);
});

test('layer switches keep unexplained reflections visible and distinguish simulated marks',()=>{
 const marks=[point('exp'),point('A',[130,90],{layer:'simulation_A'}),point('B',[180,90],{layer:'simulation_B'}),point('unknown',[240,90],{category:'unexplained'}),point('hidden',[300,90],{category:'unexplained',geometry_visible:false})];
 const layout=layoutAnnotations(marks,{...options,layers:{experimental:false,simulation_A:true,simulation_B:false}});
 assert.deepEqual(layout.items.map(item=>item.geometryVisible),[false,true,false,true,false]);
 assert.ok(layout.items[1].dash.length);assert.deepEqual(layout.items[3].dash,[]);assert.equal(layout.items[3].color,'#e4e7eb');
 assert.equal(layout.items[0].label.visible,false);assert.equal(layout.items[3].label.visible,true);
 marks[3].status='retracted';assert.equal(layoutAnnotations(marks,options).items[3].geometryVisible,false);
});

test('deterministic placement avoids edges, occupied labels, and peak centres without moving scientific marks',()=>{
 const marks=[point('one',[12,12],{label:{text:'(1 -1 0)'}}),point('two',[35,24],{label:{text:'g2'}}),point('three',[140,70],{label:{text:'(2 0 0)'}})];
 const layout=layoutAnnotations(marks,{...options,width:180,height:100,arrange:true});
 assert.deepEqual(layout,layoutAnnotations(marks,{...options,width:180,height:100,arrange:true}));
 const labels=layout.items.map(item=>item.label).filter(label=>label.visible);
 for(const label of labels){assert.ok(label.x>=0&&label.y>=0);assert.ok(label.x+label.width<=180+.001);assert.ok(label.y+label.height<=100+.001);}
 for(let i=0;i<labels.length;i++)for(let j=i+1;j<labels.length;j++)assert.equal(overlap(labels[i],labels[j]),0);
 assert.equal(layout.suggestedUpdates.length,3);
 for(const update of layout.suggestedUpdates){assert.deepEqual(Object.keys(update).sort(),['id','presentation']);assert.deepEqual(Object.keys(update.presentation),['label']);assert.equal(update.presentation.label.pinned,false);}
 assert.deepEqual(marks.map(mark=>mark.coordinates),[[12,12],[35,24],[140,70]]);
});

test('explicit arrange retains pinned labels and never suggests a scientific or status edit',()=>{
 const marks=[point('pinned',[30,40],{label:{text:'A',offset:[80,50],pinned:true}}),point('movable',[36,42],{label:{text:'B',offset:[74,48],pinned:false}})];
 const initial=layoutAnnotations(marks,options);assert.deepEqual(initial.items[1].label.offset,[74,48]);
 const arranged=layoutAnnotations(marks,{...options,arrange:true});assert.deepEqual(arranged.items[0].label.offset,[80,50]);
 assert.deepEqual(arranged.suggestedUpdates.map(update=>update.id),['movable']);assert.notDeepEqual(arranged.items[1].label.offset,[74,48]);
 assert.equal('coordinates'in arranged.suggestedUpdates[0],false);assert.equal('status'in arranged.suggestedUpdates[0].presentation,false);
});

test('crowded labels yield to peaks; analysis selection can reveal detail while figure mode omits handles',()=>{
 const marks=Array.from({length:25},(_,i)=>point(`p${i}`,[70,60],{label:{text:`reflection ${i}`}}));
 const layout=layoutAnnotations(marks,{...options,width:140,height:120,selectedId:'p24'});
 assert.equal(layout.items.length,25);assert.ok(layout.items.every(item=>item.geometryVisible));
 assert.ok(layout.items.filter(item=>!item.label.visible).length>0);assert.equal(layout.items[24].label.visible,true);
 assert.match(renderAnnotationsSVG(layout,{figureLayout:{legend:false}}),/data-part="handles"/);
 const figure=layoutAnnotations(marks,{...options,width:140,height:120,mode:'figure',selectedId:'p24'});
 assert.doesNotMatch(renderAnnotationsSVG(figure,{figureLayout:{legend:false}}),/data-part="handles"/);
 const hidden=point('hidden',[10,10],{label:{text:'Important',figure_visible:false,important:true}});assert.equal(layoutAnnotations([hidden],{...options,mode:'figure'}).items[0].label.visible,false);
});

test('crystallographic typography renders only entered indices with overlines and g subscripts',()=>{
 assert.equal(presentationText(' g1  (hyp.) '),'g₁');assert.equal(presentationText('g_12'),'g₁₂');
 assert.equal(crystallographicSVGText('(1-10)'),'('+'1<tspan text-decoration="overline">1</tspan>0)');
 assert.equal(crystallographicSVGText('[−1 1 0]'),'[<tspan text-decoration="overline">1</tspan> 1 0]');
 assert.equal(crystallographicSVGText('{-12 2 0}'),'{<tspan text-decoration="overline">12</tspan> 2 0}');
 assert.equal(crystallographicSVGText('<1-10>'),'⟨1<tspan text-decoration="overline">1</tspan>0⟩');
 assert.equal(crystallographicSVGText('⟨-110⟩'),'⟨<tspan text-decoration="overline">1</tspan>10⟩');
 assert.equal(crystallographicSVGText('$\\langle \\bar{1}10 \\rangle$'),'⟨<tspan text-decoration="overline">1</tspan> 1 0⟩');
 assert.equal(crystallographicSVGText('$(\\overline{1}10)$'),'(<tspan text-decoration="overline">1</tspan>10)');
 assert.equal(crystallographicSVGText('$g_{1}$'),'g₁');
 assert.match(crystallographicSVGText('d_(1 -1 0)'),/^d<tspan baseline-shift="sub" font-size="75%">/);
 assert.equal(crystallographicSVGText('(12)'),'('+'12)');assert.equal(crystallographicSVGText('\\bar{1}'),'<tspan text-decoration="overline">1</tspan>');
});

test('SVG escapes labels, IDs, and panel letters; unsupported styles cannot inject attributes',()=>{
 const hostile=point('id" onload="boom',[20,25],{marker_shape:'<script>',label:{text:'<script>alert("x")</script> & safe',offset:[8,9],pinned:true}},'original');hostile.color='red" onload="boom';
 const svg=renderAnnotationsSVG(layoutAnnotations([hostile],options),{interactive:true,figureLayout:{legend:false,letter:'<image onerror="boom">',scaleBar:{x:10,y:270,length:80,label:'5 < nm',color:'url(javascript:bad)'}}});
 assert.doesNotMatch(svg,/<script|<image|onload="boom|url\(javascript|<foreignObject/);
 assert.match(svg,/&lt;script&gt;/);assert.match(svg,/data-annotation-id="id&quot; onload=&quot;boom"/);
 assert.match(svg,/5 &lt; nm/);assert.match(svg,/data-part="panel-letter"/);assert.doesNotMatch(svg,/data-part="legend"/);
 assert.match(svg,/data-part="label"/);assert.match(svg,/fill="#f1f4f5"/);
});

test('editable SVG retains render map when output is enlarged and exports every supported geometry',()=>{
 const marks=[point('p',[12.125,20.75]),{annotation_id:'box',kind:'rectangle',coordinates:[20,30,50,60],text:'A'},{annotation_id:'line',kind:'line',coordinates:[0,10,60,70]},{annotation_id:'arrow',kind:'arrow',coordinates:[10,90,80,100]},{annotation_id:'poly',kind:'polygon',coordinates:[120,10,150,40,130,60]}];
 const layout=layoutAnnotations(marks,{width:200,height:120,preset:'real-space',mode:'figure'}),svg=renderAnnotationsSVG(layout,{width:1000,height:600,figureLayout:{legend:false}});
 assert.match(svg,/width="1000" height="600" viewBox="0 0 200 120"/);assert.match(svg,/cx="12.125" cy="20.75"/);
 assert.match(svg,/<rect x="20" y="30" width="30" height="30"/);assert.match(svg,/<polyline points="0 10 60 70"/);assert.match(svg,/<polygon points="120 10 150 40 130 60"/);
 assert.match(svg,/data-part="label"/);assert.doesNotMatch(svg,/<svg[^>]*<svg|<image|<canvas|data-part="handles"/);
 assert.doesNotMatch(renderAnnotationsSVG(layout,{includeRoot:false,figureLayout:{legend:false}}),/<svg/);
});
