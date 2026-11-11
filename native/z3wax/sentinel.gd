extends RefCounted
## Server-side protocol validation. Never inspect a player's files/processes.
var strikes: Dictionary = {}
var sequences: Dictionary = {}
var windows: Dictionary = {}
var evidence: Array = []
func validate(peer: int, sequence: int, move: Vector2, yaw: float, pitch: float, now: int) -> bool:
	var reason = ""
	if not is_finite(move.x) or not is_finite(move.y) or not is_finite(yaw) or not is_finite(pitch): reason="non_finite_input"
	elif move.length()>1.05 or absf(pitch)>1.5 or absf(yaw)>10000: reason="invalid_input_range"
	elif sequence<=sequences.get(peer,-1): return false # reordering is not a ban reason
	var window=windows.get(peer,[now,0])
	if now-window[0]>=1000: window=[now,0]
	window[1]+=1;windows[peer]=window
	if window[1]>90: reason="input_flood"
	if reason!="":
		strikes[peer]=strikes.get(peer,0)+1
		var event={"peer":peer,"reason":reason,"time_ms":now}
		evidence.append(event)
		if evidence.size()>256: evidence.pop_front()
		var log=FileAccess.open("user://sentinel.jsonl",FileAccess.READ_WRITE if FileAccess.file_exists("user://sentinel.jsonl") else FileAccess.WRITE)
		if log: log.seek_end();log.store_line(JSON.stringify(event))
		return false
	sequences[peer]=sequence
	return true
func should_kick(peer: int) -> bool: return strikes.get(peer,0)>=12
func forget(peer: int) -> void:
	strikes.erase(peer);sequences.erase(peer);windows.erase(peer)
