from pathlib import Path
import shutil, sys
root=Path(sys.argv[1]).resolve()

def replace(path, old, new):
    p=root/path
    s=p.read_text(encoding='utf-8')
    assert s.count(old)==1,(path,s.count(old))
    p.write_text(s.replace(old,new),encoding='utf-8',newline='\n')

replace('crystallography/registration_proposal.py','''    source = first["source_object_id"]
    require(type(source) is str and OBJECT_ID.fullmatch(source),
            "An exact immutable source science object is required")
''','''    # A display wrapper is provenance, not the scientific producer. Current
    # callers have already checked these grids against committed workspace
    # objects in bind_geometry(). Historical records without grids retain the
    # old exact-source contract; never mix the two evidence generations.
    with_grid = ["scientific_grid_identity" in row for row in measurements]
    require(all(with_grid) or not any(with_grid),
            "Cannot mix grid-bound and historical measurements; remeasure on the selected grid")
    grid = measurements[0].get("scientific_grid_identity") if all(with_grid) else None
    if all(with_grid):
        require(type(grid) is dict and set(grid) == {
                    "source_grid_object_id", "shape_yx", "dtype", "array_sha256",
                    "source_rect_xyxy", "coordinate_space"} and
                type(grid.get("source_grid_object_id")) is str and
                OBJECT_ID.fullmatch(grid["source_grid_object_id"]) and
                grid.get("coordinate_space") == first["coordinate_space"],
                "A complete committed scientific grid identity is required")
        require(all(type(row.get("scientific_grid_identity")) is dict and
                    canonical(row["scientific_grid_identity"]) == canonical(grid)
                    for row in measurements),
                "Registration measurements must share the exact scientific grid, not merely equal pixels")
    source = grid["source_grid_object_id"] if grid is not None else first["source_object_id"]
    require(type(source) is str and OBJECT_ID.fullmatch(source),
            "An exact immutable source science object is required")
''')
replace('crystallography/registration_proposal.py','''        require(row["source_object_id"] == source and row["coordinate_space"] == first["coordinate_space"] and
''','''        require((grid is not None or row["source_object_id"] == source) and row["coordinate_space"] == first["coordinate_space"] and
''')
replace('crystallography/registration_proposal.py','''    value = {"binding_version": 1, "source_object_id": source,
''','''    value = {"binding_version": 2 if grid is not None else 1, "source_object_id": source,
             **({"scientific_grid_identity": grid} if grid is not None else {}),
''')
replace('tools/image_workspace.py','''        need(not any(context.get(field) for field in ("reconstruction_type", "data_meaning")),
             "Domain declaration cannot override an existing reconstruction/data-meaning statement")
''','''        # Free-text data_meaning is retained context, not an established
        # coordinate domain. The explicit sourced declaration owns that choice;
        # reconstruction_type and typed native/scale evidence still forbid a
        # silent reinterpretation. Do not parse or delete the user's text.
        need(not context.get("reconstruction_type"),
             "Domain declaration cannot override an existing reconstruction-type statement")
''')
replace('tools/image_workspace.py','''            need(not any((context or {}).get(field) for field in ("reconstruction_type", "data_meaning")),
                 "Domain declaration cannot silently replace an existing user reconstruction/data-meaning statement")
''','''            need(not (context or {}).get("reconstruction_type"),
                 "Domain declaration cannot silently replace an existing user reconstruction-type statement")
''')
replace('docs/CENTRE_REVISIONS.md','''No flag overrides known real-space/native units or Fourier lineage, an existing
calibration domain, or an existing reconstruction/data-meaning statement. The
''','''No flag overrides known real-space/native units or Fourier lineage, an existing
calibration domain, or an existing reconstruction-type statement. Free-text
`data_meaning` is retained as background, not parsed or used as a blanket veto:
the new explicit declaration and its user source establish the domain only for
an otherwise unknown input. This is not implicit inference from that text. The
''')
replace('docs/CONSTRAINED_REGISTRATION.md','''All measurements must share one immutable scientific source plane/frame/ROI,
coordinate space, active calibration record and exact centre version. The
''','''All measurements must share one immutable scientific source plane/frame/ROI,
coordinate space, active calibration record and exact centre version. Current
records use a version-2 binding of their verified `scientific_grid_identity`:
changing gamma, annotations or a display-only frequency window does not change
that identity. Original view IDs remain in each observation's provenance.
Different captures/frames/FFT producers, array hashes or scientific ROI extents
still reject. Historical records without a grid use the old strict source-ID
contract; they cannot be mixed with grid-bound records. An old saved proposal
remains historical; make a new proposal before continuing with the v2 binding. The
''')
anchor='    def test_current_scale_revision_reuses_points_and_fft_but_not_old_physical_results(self):'
replace('tests/test_analysis_revision.py',anchor,'''    def test_display_revisions_share_registration_and_saved_proposal_without_recomputing(self):
        view = self.image("view", "display-gamma", object_id=self.fft["object_id"], gamma=.8)
        zoom = self.image("view", "display-zoom", object_id=view["object_id"],
                          gamma=1.1, frequency_rect=[16, 0, 32, 32])
        mixed = [self.image("measure", "display-peak-"+str(i), object_id=obj["object_id"], points=row["points"])
                 for i, (obj, row) in enumerate(zip((self.fft, view, zoom, view), self.measures))]
        self.assertEqual(len({row["source_object_id"] for row in mixed}), 3)
        registered = self.register("display-register", mixed, zoom)
        self.assertTrue(registered["held_out_validation_passed"])
        self.assertEqual(registered["experimental_geometry_binding"]["binding_version"], 2)
        comparison = self.compare("display-compare", registered, mixed, zoom)
        self.assertTrue(comparison["all_experimental_reflections_matched_within_tolerance"])
        # Display-only remeasurement preserves the semantic binding despite
        # new measurement/view IDs; it is not new independent validation.
        same = [self.image("remeasure", "display-remeasure-"+str(i), object_id=zoom["object_id"],
                           measurement_object_id=row["object_id"]) for i, row in enumerate(mixed)]
        repeated = self.compare("display-compare-again", registered, same, zoom)
        self.assertTrue(repeated["comparison_is_not_new_independent_validation"])
        self.assertTrue(repeated["all_experimental_reflections_matched_within_tolerance"])
        self.assertEqual(self.sha(Path(self.fft["array_path"])), self.fft_hash)

'''+anchor)
replace('tests/revisable-diffraction-mcp.test.mjs',"  const declared=(await c.tool('image_calibrate',{object_id:frame.object_id,scope:'image',coordinate_domain:'reciprocal_space',declare_reciprocal:true,", "  const described=(await c.tool('image_context',{object_id:frame.object_id,metadata:{data_meaning:'SAED diffraction intensity supplied by the researcher'},request_id:'describe-before-scale'})).data;\n  const declared=(await c.tool('image_calibrate',{object_id:described.object_id,scope:'image',coordinate_domain:'reciprocal_space',declare_reciprocal:true,")
replace('tests/revisable-diffraction-mcp.test.mjs',"  for(let i=0;i<peaks.length;i++)measures.push((await c.tool('image_measure',{object_id:centre.object_id,points:[[16,16],peaks[i]],coordinate_space:'source_array_indices',request_id:'peak-'+i})).data);", """  const displayA=(await c.tool('image_preview',{object_id:centre.object_id,gamma:.8,request_id:'display-a'})).data;
  const displayB=(await c.tool('image_preview',{object_id:displayA.object_id,gamma:1.1,request_id:'display-b'})).data;
  const measurementViews=[centre,displayA,displayB,displayA];
  for(let i=0;i<peaks.length;i++)measures.push((await c.tool('image_measure',{object_id:measurementViews[i].object_id,points:[[16,16],peaks[i]],coordinate_space:'source_array_indices',request_id:'peak-'+i})).data);
  assert.equal(new Set(measures.map(m=>m.source_object_id)).size,3);
  assert.equal(displayB.user_context.data_meaning,'SAED diffraction intensity supplied by the researcher');""")
replace('ROADMAP.md','# mcp-dm scope and roadmap\n','# mcp-dm scope and roadmap\n\n## Next active milestone\n\nSee [可探索、可修订的显微分析工具](docs/NEXT_ANALYSIS_DEVELOPMENT.md) for the\npost-PR26 priorities and Codex handoff: actionable failure diagnostics, honestly\nunconfirmed Agent hypotheses, and a real multi-turn scientific task. GUI work\nis limited to actual blockers. The older implementation milestones below are\ncontext, not instructions to rebuild completed features. The independent\nGMS-compatibility work in PR #27 is reviewed separately.\n')
