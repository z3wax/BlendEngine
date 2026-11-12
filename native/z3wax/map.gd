extends Control
var player=Vector2.ZERO
var zone_radius=7000.0
var world_script=preload("res://world.gd")
func _draw() -> void:
	var bounds=Rect2(Vector2.ZERO,size);draw_rect(bounds,Color(.025,.09,.13))
	var step=size/64.0
	for x in range(64):
		for y in range(64):
			var p=Vector2(x/64.0,y/64.0)*16000-Vector2.ONE*8000
			if world_script.height_at(p.x,p.y)>-6:draw_rect(Rect2(Vector2(x,y)*step,step+Vector2.ONE),world_script.biome(p.x,p.y))
	for i in range(17):
		draw_line(Vector2(i*size.x/16,0),Vector2(i*size.x/16,size.y),Color(1,1,1,.12))
		draw_line(Vector2(0,i*size.y/16),Vector2(size.x,i*size.y/16),Color(1,1,1,.12))
	draw_arc(size/2,zone_radius/16000*size.x,0,TAU,96,Color(.3,.9,.85),2,true)
	for name in world_script.POIS:
		var p=(world_script.POIS[name]+Vector2.ONE*8000)/16000*size
		draw_circle(p,3,Color(.95,.72,.3));draw_string(ThemeDB.fallback_font,p+Vector2(6,0),name,HORIZONTAL_ALIGNMENT_LEFT,-1,13,Color.WHITE)
	draw_circle((player+Vector2.ONE*8000)/16000*size,5,Color.WHITE)
