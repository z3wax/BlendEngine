class_name StaticRenderBatch
extends RefCounted
## Merge static surfaces by identical material inside small cells. Original
## collision bodies remain; no triangles, UVs, normals or textures are removed.
static func combine(root: Node3D, cell_size: float = 32.0) -> Dictionary:
	var groups: Dictionary = {}
	var sources := 0
	for node in root.find_children("*", "MeshInstance3D", true, false):
		var instance := node as MeshInstance3D
		if instance.mesh == null or instance.skin != null or not instance.is_visible_in_tree():
			continue
		if instance.mesh.get_surface_count() != 1:
			continue
		var pose := root.global_transform.affine_inverse() * instance.global_transform
		var center := pose * instance.mesh.get_aabb().get_center()
		var cell := Vector3i(floori(center.x / cell_size), floori(center.y / cell_size), floori(center.z / cell_size))
		for surface in range(instance.mesh.get_surface_count()):
			var material := instance.get_active_material(surface)
			if material == null or instance.mesh.surface_get_primitive_type(surface) != Mesh.PRIMITIVE_TRIANGLES:
				continue
			var key := "%s/%s/%s/%s" % [cell, material.get_rid().get_id(), instance.cast_shadow, instance.layers]
			if not groups.has(key): groups[key] = []
			groups[key].append({"instance":instance, "surface":surface, "pose":pose, "material":material})
	var replacements: Dictionary = {}
	var batches := 0
	for group in groups.values():
		if group.size() < 2: continue
		var builder := SurfaceTool.new()
		builder.begin(Mesh.PRIMITIVE_TRIANGLES)
		builder.set_material(group[0].material)
		for item in group:
			builder.append_from(item.instance.mesh, item.surface, item.pose)
			replacements[item.instance] = int(replacements.get(item.instance, 0)) + 1
		var combined := MeshInstance3D.new()
		combined.name = "StaticBatch%d" % batches
		combined.mesh = builder.commit()
		combined.cast_shadow = group[0].instance.cast_shadow
		combined.layers = group[0].instance.layers
		combined.visibility_range_end = group[0].instance.visibility_range_end
		root.add_child(combined)
		batches += 1
	for instance in replacements:
		# Only hide an original after all its surfaces have replacements.
		if replacements[instance] == instance.mesh.get_surface_count():
			instance.hide()
			sources += 1
	return {"source_instances":sources, "batches":batches}
