extends Node3D
## 16 km world, 1 km sectors. Only the 3x3 neighborhood owns geometry/collision.
const SIZE = 16000.0
const TILE = 1000.0
const POIS = {"Snowy Heights":Vector2(-4600,-5200), "Verdant Forest":Vector2(-5000,-1600), "Dust Bowl":Vector2(2300,-4800), "Metro City":Vector2(5600,-1800), "Lake District":Vector2(0,-1500), "Marshlands":Vector2(-1800,3300), "Savanna Industry":Vector2(3700,3300), "Jungle Base":Vector2(-5100,3200), "Relay Nine":Vector2.ZERO, "Coastal Town":Vector2(5600,5200)}
var sectors: Dictionary = {}
var material: StandardMaterial3D
var headless = DisplayServer.get_name() == "headless"

static func height_at(x: float, z: float) -> float:
	var coast = 1.0 - pow(x / 7600.0, 4.0) - pow(z / 7200.0, 4.0)
	var h = maxf(-30.0, coast * 45.0)
	h += sin(x * .0009) * cos(z * .0008) * 35.0
	h += 320.0 * exp(-pow((x+4200.0)/1700.0,2)-pow((z+4800.0)/1700.0,2))
	# Preserve a flat authored combat sector with a continuous apron.
	return lerpf(8.0, h, smoothstep(200.0,650.0,Vector2(x,z).length()))

static func biome(x: float, z: float) -> Color:
	if x < -2000 and z < -3500: return Color(.76,.83,.85)
	if x > 1000 and z < -2000: return Color(.64,.49,.29)
	if z > 1800 and x < 1000: return Color(.20,.29,.21)
	return Color(.37,.40,.25)

func _ready() -> void:
	material = StandardMaterial3D.new()
	material.vertex_color_use_as_albedo = true
	material.roughness = .95
	if not headless:
		var sea = MeshInstance3D.new()
		var plane = PlaneMesh.new(); plane.size = Vector2(24000,24000);sea.mesh=plane
		var water = StandardMaterial3D.new();water.albedo_color=Color(.07,.25,.30);water.roughness=.32;water.metallic=.4
		sea.material_override=water;sea.position.y=-6;add_child(sea)
	var outpost = load("res://assets/outpost.glb").instantiate()
	add_child(outpost);outpost.position.y=8
	for node in outpost.find_children("*","MeshInstance3D",true,false):
		node.create_trimesh_collision()
		node.visibility_range_end=650.0
		node.cast_shadow=GeometryInstance3D.SHADOW_CASTING_SETTING_ON
		if headless: node.visible=false
	update_sectors(Vector3.ZERO)

func update_sectors(point: Vector3) -> void:
	update_regions([point])

func update_regions(points: Array) -> void:
	var needed: Dictionary = {}
	for point in points:
		var center = Vector2i(floori((point.x+8000)/TILE),floori((point.z+8000)/TILE))
		for x in range(maxi(0,center.x-1),mini(16,center.x+2)):
			for z in range(maxi(0,center.y-1),mini(16,center.y+2)):
				var key=Vector2i(x,z);needed[key]=true
				if not sectors.has(key): _make_sector(key)
	for key in sectors.keys():
		if not needed.has(key): sectors[key].queue_free();sectors.erase(key)

func _make_sector(key: Vector2i) -> void:
	var st=SurfaceTool.new();st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var origin=Vector2(key.x*TILE-8000,key.y*TILE-8000)
	for x in range(16):
		for z in range(16):
			var a=origin+Vector2(x,z)*62.5
			for offset in [Vector2(0,0),Vector2(62.5,0),Vector2(0,62.5),Vector2(62.5,0),Vector2(62.5,62.5),Vector2(0,62.5)]:
				var p=a+offset;st.set_color(biome(p.x,p.y));st.add_vertex(Vector3(p.x,height_at(p.x,p.y),p.y))
	st.generate_normals();var mesh=MeshInstance3D.new();mesh.mesh=st.commit();mesh.material_override=material
	add_child(mesh);mesh.create_trimesh_collision();mesh.visible=not headless;sectors[key]=mesh
