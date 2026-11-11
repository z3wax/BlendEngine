extends SceneTree
func _initialize() -> void:call_deferred("test")
func test() -> void:
	var game=load("res://main.tscn").instantiate();root.add_child(game)
	game.mode="TEST";game._spawn(1,Vector3(20,8.1,25));game._spawn(2,Vector3(20,8.1,0))
	await physics_frame;await physics_frame
	var a=game.actors[1];var b=game.actors[2]
	game._fire(1);assert(b.health==75);assert(a.ammo==29)
	game._fire(1);assert(b.health==75);assert(a.ammo==29) # cadence
	a.shot_left=0;a.reload_left=1;game._fire(1);assert(a.ammo==29) # reload lock
	a.reload_left=0;a.ammo=0;game._fire(1);assert(b.health==75) # ammo
	a.ammo=30
	var wall=StaticBody3D.new();var shape=CollisionShape3D.new();var box=BoxShape3D.new();box.size=Vector3(4,4,1);shape.shape=box;wall.add_child(shape);game.add_child(wall);wall.position=Vector3(20,9,12)
	await physics_frame;await physics_frame
	game._fire(1);assert(b.health==75) # world blocks shots
	wall.queue_free();await physics_frame;await physics_frame
	for i in range(3):a.shot_left=0;game._fire(1)
	assert(b.health==0);assert(a.kills==1)
	a.shot_left=0;game._fire(1);assert(a.kills==1) # no duplicate kill credit
	game.mode="PLAYING";await physics_frame;await physics_frame
	assert(game.mode=="FINISHED")
	print("Z3WAX_COMBAT_PASS damage,cadence,reload,ammo,occlusion,kill,winner")
	quit()
