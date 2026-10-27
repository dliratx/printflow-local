"""Versioned test protocols shared by the portal, CAD worker and MCP.

The generated coupons are PrintFlow designs, not modified 3DBenchy models.
Their readings are diagnostic observations, not certified machine limits.
"""
VERSION=1
ORCA='https://github.com/OrcaSlicer/OrcaSlicer/wiki/'
SOURCES={
 'sequence':{'title':'OrcaSlicer calibration sequence','url':ORCA+'calibration_guide'},
 'temperature':{'title':'OrcaSlicer temperature test','url':ORCA+'temp_calib'},
 'flow':{'title':'OrcaSlicer flow ratio','url':ORCA+'flow_ratio_calib'},
 'volumetric':{'title':'OrcaSlicer maximum volumetric speed','url':ORCA+'volumetric_speed_calib'},
 'retraction':{'title':'OrcaSlicer retraction test','url':ORCA+'retraction_calib'},
 'tolerance':{'title':'OrcaSlicer tolerance calibration','url':ORCA+'tolerance_calib'},
 'overhang':{'title':'OrcaSlicer overhang settings','url':ORCA+'quality_settings_overhangs'},
 'bridge':{'title':'Prusa: poor bridging','url':'https://help.prusa3d.com/article/poor-bridging_1802'},
 'first_layer':{'title':'Prusa: first layer issues','url':'https://help.prusa3d.com/article/first-layer-issues_1804'},
 'support':{'title':'OrcaSlicer support settings','url':ORCA+'support_settings_support'},
 'benchy':{'title':'Original 3DBenchy inspection features','url':'https://www.3dbenchy.com/features/'},
 'u1':{'title':'Snapmaker U1 official FAQ','url':'https://wiki.snapmaker.com/en/FAQ/u1'},
}
CATEGORIES=[
 {'id':'baseline','name':'Baseline & first layer','description':'Start with adhesion and a consistent reference.'},
 {'id':'overhangs','name':'Overhangs & bridges','description':'Find where unsupported surfaces begin to lose definition.'},
 {'id':'details','name':'Surface & fine details','description':'Inspect strings, ringing, top surfaces and small features.'},
 {'id':'fit','name':'Dimensions & assembly','description':'Measure actual sizes and useful clearances.'},
 {'id':'supports','name':'Support removal','description':'Compare release effort and the supported underside.'},
 {'id':'material','name':'Material & extrusion','description':'Use calibrated sweeps for temperature, pressure and flow.'},
 {'id':'multicolor','name':'Multiple tools','description':'Check tool alignment using the printer manufacturer’s procedure.'},
]

def test(id,name,category,stage,summary,measures,readout,limits,criteria,sources,mode='coupon',**extra):
    return dict(id=id,name=name,category=category,stage=stage,summary=summary,measures=measures,
                readout=readout,limits=limits,criteria=criteria,sources=[SOURCES[k] for k in sources],
                mode=mode,version=VERSION,**extra)

TESTS=[
 test('benchy','Original 3DBenchy','baseline','benchmark','A repeatable overall check before and after tuning.',
      ['Hull finish and curved overhangs','Cabin roof, small openings and chimney','Underside and overall dimensions'],
      'Keep the original scale and orientation. Photograph front, side, rear and underside; compare the same areas between runs.',
      'Print without supports. It does not isolate one setting or test support removal.',
      ['surface','stringing','bridges','first_layer','dimensions'],['benchy'],'original',nominal='Original scale · no supports'),
 test('first_layer','Five first-layer patches','baseline','baseline','Check adhesion and line consistency across a 100 × 100 mm area.',
      ['Gaps between lines','Raised ridges or rough lines','Lifting at the five patch locations'],
      'Compare the center patch and four corners after cooling. Compare 20 and 30 mm/s first-layer infill while keeping the perimeter at 20 mm/s. Record where lines lift or leave gaps. Photos: top and underside.',
      'This samples a local bed area. It does not replace bed leveling, measure Z offset, or authorize firmware changes.',
      ['first_layer'],['first_layer','u1'],nominal='Five 20 × 20 × 0.20 mm patches'),
 test('overhang','Overhang angle ladder','overhangs','fit','Find which underside angles stay clean without supports.',
      ['Progressive underside roughness','Drooping edges and curling','The steepest acceptable angle for this material and layer height'],
      'From left to right: 35°, 45°, 55°, 65°, 75° FROM VERTICAL. Inspect each underside and record the highest acceptable angle; larger angles are harder.',
      'Keep orientation, cooling and material constant. This result is specific to this coupon, not a universal support threshold.',
      ['bridges','surface'],['overhang'],nominal='35° → 75° from vertical · no supports'),
 test('bridges','Bridge span ladder','overhangs','fit','Compare unsupported horizontal spans with anchors at both ends.',
      ['Sagging and broken bridge strands','Clean contact with the end pillars','Longest acceptable unsupported span'],
      'Rows from front to back: 10, 20, 30, 40, 50 mm clear span. Inspect from below and record the last clean span. Compare only bridge speed between variants.',
      'A bridge has two anchors; a one-sided overhang is different. Results depend on cooling, material and orientation.',
      ['bridges'],['bridge'],nominal='10–50 mm spans · no supports'),
 test('stringing','Stringing towers','details','retraction','Reveal strings between separated towers at fixed native retraction.',
      ['Fine strings between towers','Blobs at travel start and end','Tip quality'],
      'Photograph the spaces between all four towers before removing strings. Record material dryness and whether strings are fine webs or thick branches.',
      'This is a diagnostic coupon, not a retraction sweep. Use native Orca retraction calibration to vary retraction by height.',
      ['stringing','surface'],['retraction'],nominal='Four towers · 30 mm tall'),
 test('surface','Surface & ringing block','details','benchmark','Inspect flat faces, top skin and echoes after corners.',
      ['Ringing near vertical corners','Gaps or ridges on the top skin','Consistency of outer walls'],
      'Use side lighting on each face and a top photo. Compare the same face at 40 and 60 mm/s outer wall speed; other settings stay fixed.',
      'Appearance does not measure resonance or prove mechanical strength. Official input shaping remains a native operation.',
      ['surface'],['flow','sequence'],nominal='30 × 30 × 12 mm block'),
 test('fine_features','Thin walls & pins','details','benchmark','Check which small features actually survive slicing and printing.',
      ['Thin wall continuity','Small pin reproduction','Fragile or missing details'],
      'Left-to-right walls are 0.4, 0.6, 0.8, 1.0 and 1.2 mm. Front pins are 1.2, 2 and 3 mm in diameter. Check the G-code before interpreting a missing feature.',
      'Wall generation and line width affect what is sliced. Do not infer reliable strength from a surviving thin wall.',
      ['surface'],['overhang','sequence'],nominal='0.4–1.2 mm walls · 1.2–3 mm pins'),
 test('dimensions','20 mm dimensional block','fit','fit','Measure dimensional accuracy along all three axes.',
      ['X, Y and Z dimensions','Round 5 and 10 mm through-holes','Elephant foot near the bed'],
      'Use calipers on each axis away from the bottom flare. Record nominal, measured and acceptable tolerance. Check the two holes separately.',
      'Do not infer dimensions from photos or change steps/mm from a single cube. Hole fit and outside size can need different compensation.',
      ['dimensions','first_layer'],['tolerance'],nominal='20 × 20 × 20 mm · Ø5 and Ø10 holes'),
 test('clearance','Pin & hole clearance gauge','fit','fit','Choose a useful assembly clearance from real fits.',
      ['Smallest hole accepting the loose pin','Sliding versus tight fit','Variation between repeated insertions'],
      'Use the loose Ø5 mm pin in five holes, left to right: Ø5.15, 5.20, 5.25, 5.30, 5.40 mm. These values are DIAMETRAL clearance, not clearance per side.',
      'Allow the part to cool. Do not force the pin. Record fit and dimensions; tolerance changes with material, orientation and feature size.',
      ['dimensions'],['tolerance'],nominal='Ø5 pin · 0.15–0.40 mm diametral clearance'),
 test('support_removal','Support release coupon','supports','fit','Balance removal effort against the finish of the supported underside.',
      ['How the support releases after cooling','Scars or damaged edges','Flatness and roughness of the underside'],
      'Compare 0.16, 0.32 and 0.48 mm top Z gap at 0.16 mm layers. Use the same material for model and support. Report removal effort and photograph the underside.',
      'Larger gaps can release more easily but worsen the underside. Orca rounds gaps to printable layer positions; inspect the emitted support height. Only physical removal confirms release. No mixed-material interface is assumed.',
      ['supports','surface'],['support'],nominal='Supported cantilever · three Z-gap variants'),
 test('temperature','Temperature tower','material','temperature','Select a useful temperature range for the loaded filament.',
      ['Surface and bridge quality by temperature','Stringing changes','Physically checked layer bonding'],
      'Run the native Orca temperature calibration within the filament maker’s range. Record the best section and its temperature; inspect the emitted temperature changes.',
      'A plain tower STL does not create a temperature sweep. Native calibration must add temperature changes to the G-code.',
      ['surface','bridges','stringing'],['temperature'],'native',nominal='Native Orca temperature sweep'),
 test('volumetric','Maximum volumetric flow','material','volumetric','Find a conservative material throughput limit.',
      ['First visible under-extrusion','Dulling or damaged extrusion at high flow','Usable flow below the failure point'],
      'Use the native increasing-flow test, measure the failure location and calculate the flow. Start 10–20% below that measured limit and verify.',
      'Hardware detection and spool claims do not establish a measured flow limit. This test needs a generated flow sweep.',
      ['surface'],['volumetric'],'native',nominal='Native Orca flow sweep'),
 test('flow_ratio','Flow ratio patches','material','flow','Tune material quantity using controlled flow patches.',
      ['Top surface gaps','Ridges and material buildup','Selected correction patch and final ratio'],
      'Run Orca’s flow-ratio passes. Record the starting ratio, selected patch and resulting ratio; confirm it on another print.',
      'A photo supports diagnosis but does not establish flow numerically by itself. Recheck pressure advance after a large correction.',
      ['surface'],['flow'],'native',nominal='Native Orca flow-ratio passes'),
 test('retraction_sweep','Retraction sweep','material','retraction','Compare retraction lengths after temperature and flow are stable.',
      ['Stringing by tower height','Blobs and restart gaps','Selected retraction value'],
      'Run native Orca retraction calibration and inspect the height-to-value mapping. Keep within the printer and material guidance.',
      'PrintFlow records the selected value but does not automatically override retraction. A fixed tower is not this sweep.',
      ['stringing'],['retraction'],'native',nominal='Native Orca retraction sweep'),
 test('pressure_advance','Pressure / dynamic flow','material','pressure','Improve corner extrusion using the supported printer procedure.',
      ['Corner bulging','Line starts and ends','The selected pressure calibration result'],
      'For U1 use official Dynamic Flow Calibration on the actual loaded hotend and filament. For other printers follow their supported procedure.',
      'Do not replace firmware. Keep manual K as evidence; PrintFlow does not override U1 firmware calibration.',
      ['surface'],['u1','sequence'],'native',nominal='Official printer calibration'),
 test('tool_alignment','Tool alignment','multicolor','baseline','Check registration before combining independently loaded tools.',
      ['XY alignment between tools','Z alignment and nozzle condition','The manufacturer’s calibration result'],
      'Run the official U1 multi-tool calibration after the required physical checks. Record the tools and materials used, then verify a small multicolor model.',
      'This is not an AMS purge test. PrintFlow does not modify tool offsets or firmware from a picture.',
      ['surface'],['u1'],'native',nominal='Official U1 multi-tool procedure'),
]

def get_test(identifier):
    found=next((t for t in TESTS if t['id']==identifier),None)
    if not found:raise ValueError('Unknown calibration test')
    return found

def recipe(identifier):
    t=get_test(identifier)
    if t['mode']=='native':raise ValueError('This test needs the native calibration generator. Open its guide or ask AI to plan it.')
    common={'enable_support':False,'brim_type':'no_brim'}
    key='layer_height';values=[.12,.16];unit='mm layers'
    if identifier=='first_layer':
        common.update(layer_height=.2,initial_layer_print_height=.2,initial_layer_speed=20);key='initial_layer_infill_speed';values=[20,30];unit='mm/s first-layer infill'
    elif identifier=='bridges':common.update(layer_height=.16);key='bridge_speed';values=[20,30];unit='mm/s bridge speed'
    elif identifier=='surface':common.update(layer_height=.16);key='outer_wall_speed';values=[40,60];unit='mm/s outer walls'
    elif identifier=='support_removal':
        common.update(layer_height=.16,enable_support=True,support_type='normal(auto)',support_style='snug',support_threshold_angle=45,support_on_build_plate_only=False,support_interface_top_layers=3,support_interface_spacing=.3,support_object_xy_distance=.35)
        key='support_top_z_distance';values=[.16,.32,.48];unit='mm support Z gap'
    return {'variable':key,'layer_height':common.get('layer_height',.16),'supports':common['enable_support'],
            'variants':[{'name':t['name']+' · '+str(v)+' '+unit,'changes':common|{key:v}} for v in values]}

def catalog():return {'version':VERSION,'reviewed_at':'2026-10-24','categories':CATEGORIES,'tests':TESTS}


def validate_emitted_test(identifier,result):
    """Check emitted extrusion features, not just requested support switches."""
    spec=get_test(identifier)
    if spec['mode']=='native':raise ValueError('Use the native generator for this calibration test')
    plates=result.get('plates',[])
    if len(plates)!=1:raise ValueError('A calibration comparison requires one plate per variant')
    features=plates[0].get('extrusion_moves_by_feature')
    if not isinstance(features,dict):raise ValueError('Review calibration extrusion features before printing')
    supports=sum(v for k,v in features.items() if 'support' in k.lower())
    if identifier=='support_removal' and not supports:
        raise ValueError('The support-release test contains no support extrusion. Re-prepare this test before printing.')
    if identifier!='support_removal' and supports:
        raise ValueError('This calibration test must be printed without supports. Re-prepare it before printing.')
