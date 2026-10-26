from pathlib import Path
import subprocess

ROOT = Path.cwd()
BASE = '4f590f398fd4823426dc08a3b1317d5b15dcd06f'
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == BASE

def replace(name, old, new):
    p = ROOT / name
    s = p.read_text(encoding='utf-8')
    assert s.count(old) == 1, (name, s.count(old))
    p.write_text(s.replace(old, new), encoding='utf-8', newline='\n')

replace('tools/image_calibration.py', '\ndef active_scale(record):', '''
def revised_reciprocal_origin(previous, scale):
    """A scale-only revision preserves a known pixel DC, not an old unit value.

    Call only after exact image/scope/domain validation. Withdrawal retains the
    recorded centre as evidence but supplies no active physical coordinates.
    No centre is inferred for an input that never had one.
    """
    if not previous or previous.get("coordinate_domain") != "reciprocal_space":
        return {}
    dc = previous.get("dc_index_xy")
    if dc is None:
        return {}
    require(type(dc) is list and len(dc) == 2 and all(finite(v) for v in dc),
            "Saved reciprocal DC must contain two finite pixel coordinates")
    result = {"dc_index_xy": list(dc),
              "origin_inherited_from_calibration_id": previous["calibration_id"],
              "origin_revision_policy": "scale-only correction; unchanged captured pixel DC"}
    if "dc_identity_source" in previous:
        result["dc_identity_source"] = previous["dc_identity_source"]
    if scale is not None:
        zeros = [-value * scale[axis] for value, axis in zip(dc, ("x", "y"))]
        require(all(finite(v) for v in zeros) and
                all(index == 0 or zero != 0 for index, zero in zip(dc, zeros)),
                "Revised physical zero underflows or overflows binary64")
        result["physical_zero_xy"] = zeros
    return result


def active_scale(record):''')
replace('tools/image_workspace.py', 'domain = request.get("coordinate_domain", old.get("coordinate_domain", "real_space") if old and request.get("xy_scale", 1) is None else "real_space")', 'domain = request.get("coordinate_domain", old.get("coordinate_domain", "real_space") if old else "real_space")')
replace('tools/image_workspace.py', '        return previous, context, record, {"attached_existing_calibration": False}', '''        if same_scope:
            record.update(calibration.revised_reciprocal_origin(old, scale))
        return previous, context, record, {"attached_existing_calibration": False}''')
name = 'tools/image_panel.mjs'
old = next(line for line in (ROOT/name).read_text(encoding='utf-8').splitlines() if "else if(body.action==='measure')" in line)
replace(name, old, '''  else if(body.action==='measure'){
   fields(p,['selection']);const selected=checkSelection(p.selection),domain=selected.panel.domain;
   const spectral=domain==='frequency',scalar=domain==='source_array_indices',peak=selected.kind==='point';
   if(!['frequency','source_array_indices','spatial_pixels'].includes(domain))fail('Unsupported measurement domain');
   let dc=null;
   if(peak){
    if(spectral)dc=[0,0];
    else if(scalar){
     const record=current.xy_calibration;
     if(record?.status!=='active'||record.coordinate_domain!=='reciprocal_space'||
        !Array.isArray(record.dc_index_xy)||record.dc_index_xy.length!==2||!record.dc_index_xy.every(Number.isFinite))
       fail('A reciprocal peak requires an active calibration with an explicit DC; draw a two-point line for pixel geometry');
     dc=record.dc_index_xy;
    }else fail('Draw a two-point spatial line, or choose a reciprocal peak with an explicit DC');
   }else if(selected.coordinates.length!==4||!['line','arrow'].includes(selected.kind))fail('Draw a two-point line or select a reciprocal peak');
   // Reciprocal arrays retain their current calibrated wrapper. Do not replace
   // it with an older bare source while routing the user's selected indices.
   const target=spectral||scalar?current.object_id:await withCurrentContext(selected.source_object_id);
   const args={object_id:target,points:peak?[dc,selected.coordinates]:[selected.coordinates.slice(0,2),selected.coordinates.slice(2)],
    coordinate_space:spectral?'frequency_cycles_per_pixel':scalar?'source_array_indices':'source_pixels'};
   r=await journalCall('image_measure',args);
   lastOperation={...publicObject(r.data),...(peak?{reference:spectral?'mathematical DC [0,0]; geometric period, not phase identification':'recorded calibrated DC; not an independently verified beam centre'}:{})};
   selection=selected;saveSelection();return state();
  }''')
replace(name, "fields(p,['scope','xy_scale','source_text']);r=await displayObject", "fields(p,['scope','xy_scale','source_text','coordinate_domain']);r=await displayObject")
name = 'ui/image-panel/app.mjs'
old = next(line for line in (ROOT/name).read_text(encoding='utf-8').splitlines() if line.startswith('function renderMeasurement()'))
replace(name, old, '''function renderMeasurement(){const m=state.last_operation;$('operation').textContent=m?JSON.stringify(m,null,2):'';const finite=value=>typeof value==='number'&&Number.isFinite(value);
 $('measurement-summary').textContent=finite(m?.physical_distance)?`距离 ${m.physical_distance} ${m.physical_unit??''}`:
 finite(m?.distance_physical)?`距离 ${m.distance_physical} ${m.physical_unit??''}`:
 finite(m?.d_spacing)?`晶面间距（几何） ${m.d_spacing} ${m.d_spacing_unit??''}`:
 finite(m?.period)?`倒空间差向量周期 ${m.period} ${m.period_unit??''}`:
 finite(m?.distance_pixels)?`图像坐标距离 ${m.distance_pixels} px`:
 finite(m?.frequency_distance_cycles_per_pixel)?`频率差 ${m.frequency_distance_cycles_per_pixel} cycles/pixel`:
 '选线段或已知中心的倒空间峰后可测量；候选标记不等于物相确认';}''')
replace(name, "const calibrate=withdraw=>act('calibrate',{scope:$('scope').value,", "const calibrate=withdraw=>act('calibrate',{coordinate_domain:state.object.xy_calibration?.coordinate_domain??'real_space',scope:$('scope').value,")
needle = " $('calibration').hidden=!state.tools.some(t=>t.name==='image_calibrate');"
replace(name, needle, ''' const calibrationRecord=o.xy_calibration;
 if(calibrationRecord?.xy_scale){const xy=calibrationRecord.xy_scale;$('scale-x').value=xy.x;$('scale-y').value=xy.y;
  $('unit').value=({'angstrom':'Å','1/angstrom':'1/Å'})[xy.unit]??xy.unit;$('scope').value=calibrationRecord.scope;}
'''+needle)
replace('ui/image-panel/index.html','<option value="um">µm</option></select>', '<option value="um">µm</option><option value="1/nm">1/nm</option><option value="1/Å">1/Å</option><option value="1/um">1/µm</option></select>')

replace('README.md', '这些功能尚未合并 main。', '这些能力已整合到主线，但仍须显式配置启用，并遵守各自的实验性支持范围。')
replace('README.md', '本功能分支可直接打开', '主线中的可选工具可直接打开')
replace('README.en.md', 'These additions are on the trial branch and have not been merged into main.', 'These additions are integrated on main but remain opt-in experimental capabilities with separately documented scopes.')
replace('README.en.md', 'The feature branch also adds optional', 'Main also includes optional')
replace('README.en.md', 'This feature branch opens uint16', 'The opt-in tools open uint16')
p=ROOT/'docs/UNIFIED_IMAGE_TRIAL.md';s=p.read_text(encoding='utf-8');p.write_text('''# Try the unified image tools

The PR #12–#23 feature chain and closeout fixes are integrated into `main`.
Use a clean checkout of current main for the combined trial. Do not manually
merge the old stacked branches or reset a working tree with local changes.
This integration is not a new stable native release: default v0.6 remains
unchanged, and image/structure/native paths still require explicit opt-in.
The native adapter remains restricted to the exact supported GMS build and
per-operation scopes, including small float32 return with nm or 1/nm units.

'''+s[s.index('## Connect once'):],encoding='utf-8',newline='\n')
replace('docs/NATIVE_CALIBRATION_HANDOFF.md', 'Scale uncertainty remains unknown unless supplied.', '''A same-scope scale-only correction inherits its established coordinate domain
when omitted. On reciprocal captures it retains the recorded pixel DC and its
source; physical zero is recalculated as `-dc_index * new_signed_scale` in the
new unit, rather than copying an old unit value. Withdrawal retains the pixel
centre as historical geometry but disables physical measurements. Restoring a
scale can reuse that centre. An absent centre is never inferred, and this does
not provide independent beam-centre verification or a centre-editing tool.

Scale uncertainty remains unknown unless supplied.''')
replace('docs/LOCAL_IMAGE_PANEL.md', '- Enter the actual user statement, scope, signed X/Y scale and unit to create', '''- Calibrated reciprocal scalar captures also support line measurement and
  point-to-recorded-DC measurement through the same backend. A point requires
  an active scale and an explicit recorded centre; the panel never guesses one.
  Uncalibrated/withdrawn reciprocal arrays still permit two-point pixel geometry.
  The current record's domain and signed units are retained in calibration edits;
  this is not a way to reinterpret an unknown array as a diffraction image.
- Enter the actual user statement, scope, signed X/Y scale and unit to create''')

payload = Path(__file__).resolve().parent
# Tests are shipped as separate readable review payloads, never runtime code.
p=ROOT/'tests/image-panel-reciprocal.test.mjs';assert not p.exists();p.write_bytes((payload/'image-panel-reciprocal.test.mjs').read_bytes())
p=ROOT/'tests/image-panel-ui.test.mjs';p.write_bytes(p.read_bytes()+(payload/'ui-tests.txt').read_bytes())
p=ROOT/'tests/test_native_calibration_handoff.py';s=p.read_text(encoding='utf-8');needle='    def test_automatic_native_scale_mixed_units_signed_axes_read_offset_and_3_4_5(self):';assert s.count(needle)==1;p.write_text(s.replace(needle,(payload/'calibration-tests.txt').read_text(encoding='utf-8')+needle),encoding='utf-8',newline='\n')
subprocess.run(['git','diff','--check'],check=True)
