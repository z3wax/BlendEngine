extends SceneTree
func _initialize() -> void:
	var directory := OS.get_environment("Z3WAX_PACKAGE_DIR").path_join("licenses")
	var license := FileAccess.open(directory.path_join("GODOT-LICENSE.txt"), FileAccess.WRITE)
	license.store_string(Engine.get_license_text()); license.close()
	var third_party := FileAccess.open(directory.path_join("GODOT-THIRD-PARTY.json"), FileAccess.WRITE)
	third_party.store_string(JSON.stringify({"copyrights":Engine.get_copyright_info(), "licenses":Engine.get_license_info()}, "  "))
	third_party.close()
	quit()
