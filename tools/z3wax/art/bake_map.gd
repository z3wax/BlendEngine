extends SceneTree
const World=preload("res://world.gd")
func _initialize() -> void:
	var resolution=768
	var image=Image.create(resolution,resolution,false,Image.FORMAT_RGB8)
	for y in range(resolution):
		for x in range(resolution):
			var p=(Vector2(x+.5,y+.5)/resolution-Vector2.ONE*.5)*World.SIZE
			var h=World.height_at(p.x,p.y)
			var color: Color
			if h<=-6:
				color=Color(.025,.085,.14).lerp(Color(.10,.29,.32),clampf((h+35)/29,0,1))
			else:
				color=World.biome(p.x,p.y)
				var slope=Vector3(World.height_at(p.x-18,p.y)-World.height_at(p.x+18,p.y),36,World.height_at(p.x,p.y-18)-World.height_at(p.x,p.y+18)).normalized()
				var lighting=.58+.62*maxf(0,slope.dot(Vector3(-.5,.7,-.5).normalized()))
				color*=lighting
				if h<2:color=color.lerp(Color(.66,.60,.43),clampf((2-h)/8,0,1))
			image.set_pixel(x,y,color)
	var output="res://assets/realistic/disland_relief.png"
	assert(image.save_png(output)==OK)
	print("Z3WAX_RELIEF_BAKED 768x768 from authoritative terrain height function")
	quit()
