extends SceneTree
func _initialize() -> void:
	var s=load("res://sentinel.gd").new()
	assert(s.validate(2,1,Vector2(0,-1),0,0,1000))
	assert(not s.validate(2,1,Vector2.ZERO,0,0,1001))
	assert(s.strikes.get(2,0)==0) # duplicate packet != cheating
	assert(not s.validate(2,2,Vector2(NAN,0),0,0,1002))
	assert(not s.validate(2,3,Vector2(9,0),0,0,1003))
	for i in range(12):s.validate(3,i,Vector2.ZERO,INF,0,2000+i)
	assert(s.should_kick(3))
	s.forget(3);assert(not s.should_kick(3))
	assert(s.validate(4,1,Vector2.ZERO,0,0,5000))
	assert(s.validate(4,2,Vector2.ZERO,0,0,10000)) # network stall is valid
	var world=load("res://world.gd")
	assert(world.SIZE==16000)
	assert(is_equal_approx(world.height_at(20,25),8))
	print("Z3WAX_PROTOCOL_PASS finite,range,replay,flood_state,latency,world_extent")
	quit()
