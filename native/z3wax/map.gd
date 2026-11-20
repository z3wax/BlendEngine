extends Control
var player=Vector2.ZERO
var zone_radius=7000.0
const World=preload("res://world.gd")
var terrain=preload("res://assets/realistic/disland_relief.png")
func _draw() -> void:
	var rect=Rect2(Vector2(24,20),size-Vector2(48,42))
	draw_rect(Rect2(Vector2.ZERO,size),Color(.02,.045,.06))
	draw_texture_rect(terrain,rect,false)
	var font=get_theme_default_font()
	for i in range(17):
		var x=rect.position.x+i*rect.size.x/16;var y=rect.position.y+i*rect.size.y/16
		draw_line(Vector2(x,rect.position.y),Vector2(x,rect.end.y),Color(1,1,1,.16))
		draw_line(Vector2(rect.position.x,y),Vector2(rect.end.x,y),Color(1,1,1,.16))
		if i<16:
			draw_string(font,Vector2(x+rect.size.x/32-4,14),String.chr(65+i),HORIZONTAL_ALIGNMENT_LEFT,-1,13,Color(.7,.77,.78))
			draw_string(font,Vector2(2,y+rect.size.y/32+4),str(i+1),HORIZONTAL_ALIGNMENT_LEFT,-1,13,Color(.7,.77,.78))
	var circle=PackedVector2Array()
	for i in range(97):circle.append(rect.get_center()+Vector2(cos(i*TAU/96),sin(i*TAU/96))*zone_radius/World.SIZE*rect.size)
	draw_polyline(circle,Color(.35,.9,.85),2,true)
	for place in World.POIS:
		var p=rect.position+(World.POIS[place]/World.SIZE+Vector2.ONE*.5)*rect.size
		var color=Color(.98,.78,.4) if place=="Relay Nine" else Color(.8,.83,.82)
		draw_circle(p,3,color)
		var label=place if place=="Relay Nine" else place+" *"
		draw_string_outline(font,p+Vector2(6,0),label,HORIZONTAL_ALIGNMENT_LEFT,-1,14,3,Color(.02,.04,.05))
		draw_string(font,p+Vector2(6,0),label,HORIZONTAL_ALIGNMENT_LEFT,-1,14,color)
	draw_circle(rect.position+(player/World.SIZE+Vector2.ONE*.5)*rect.size,5,Color.WHITE)
	draw_string(font,Vector2(25,size.y-3),"* Planned settlements — this relief shows current terrain, not finished city content.",HORIZONTAL_ALIGNMENT_LEFT,-1,13,Color(.68,.76,.78))
