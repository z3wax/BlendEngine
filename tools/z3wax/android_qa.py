#!/usr/bin/env python3
"""Installed APK checks, real Android touch inputs and physics smoke."""
import subprocess,time,json,pathlib,hashlib,sys,os
from PIL import Image
apk=pathlib.Path(sys.argv[1]);out=pathlib.Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
pkg='org.z3wax.disland';adb=str(pathlib.Path(os.environ['ANDROID_HOME'])/'platform-tools/adb')
def call(*args,check=True):
 p=subprocess.run([adb,*map(str,args)],capture_output=True,timeout=90)
 if check and p.returncode:raise RuntimeError(p.stderr.decode(errors='replace'))
 return p.stdout
def state():
 try:return json.loads(call('exec-out','run-as',pkg,'cat','files/qa_state.json',check=False))
 except ValueError:return {}
def wait(predicate,seconds=120):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  s=state()
  if predicate(s):return s
  time.sleep(1)
 raise RuntimeError('Timed out: '+str(state()))
def tap(x,y):call('shell','input','tap',x,y)
report={'passed':False,'sha256':hashlib.sha256(apk.read_bytes()).hexdigest(),'physical_device_tested':False,'emulator':'Android API24 x86_64','checks':[]}
try:
 call('install','-r',apk);call('shell','wm','size','1280x720');call('shell','wm','density','160')
 call('shell','settings','put','system','accelerometer_rotation','0')
 call('shell','settings','put','system','user_rotation','1')
 call('shell','settings','put','secure','immersive_mode_confirmations','confirmed')
 call('shell','input','keyevent','82');call('logcat','-c')
 call('shell','monkey','-p',pkg,'-c','android.intent.category.LAUNCHER','1')
 wait(lambda s:s.get('mode')=='LOBBY');time.sleep(8);report['checks'].append('normal_launcher')
 (out/'android-lobby.png').write_bytes(call('exec-out','screencap','-p'))
 assert len(set(Image.open(out/'android-lobby.png').convert('RGB').resize((64,64)).getdata()))>100, 'Lobby framebuffer is black or unrendered'
 tap(1090,480);start=wait(lambda s:s.get('mode')=='PLAYING');report['checks'].append('touch_start')
 call('shell','input','swipe','160','590','160','480','1800')
 moved=wait(lambda s:s.get('position') and sum((x-y)**2 for x,y in zip(s['position'],start['position']))>1)
 report['checks'].append('touch_move')
 before=moved['ammo'];tap(1150,575);wait(lambda s:s.get('ammo',99)<before);report['checks'].append('touch_fire')
 tap(950,565);wait(lambda s:s.get('ammo')==30);report['checks'].append('touch_reload')
 tap(1140,105);time.sleep(1);(out/'android-map.png').write_bytes(call('exec-out','screencap','-p'));tap(640,590)
 call('shell','input','keyevent','4');time.sleep(1)
 assert state().get('mode') in ['PLAYING','FINISHED'];report['checks'].append('android_back_no_exit')
 (out/'android-game.png').write_bytes(call('exec-out','screencap','-p'))
 normal_log=call('logcat','-d','-s','godot:I','Godot:I','*:S').decode(errors='replace');(out/'android-normal.log').write_text(normal_log)
 assert 'Program linking failed' not in normal_log and 'SCRIPT ERROR' not in normal_log, 'Native renderer failed during normal play'
 (out/'android-storage.txt').write_bytes(call('shell','df','-h','/data'))
 call('shell','am','force-stop',pkg);call('logcat','-c')
 call('shell','su','0','am','start','-n',pkg+'/com.godot.game.GodotApp','--esa','command_line_params','--audio-driver,Dummy,--,--smoke-test')
 end=time.monotonic()+180
 while time.monotonic()<end:
  log=call('logcat','-d','-s','godot:I','Godot:I','*:S').decode(errors='replace');(out/'android-smoke.log').write_text(log)
  if 'Z3WAX_SMOKE_PASS' in log:break
  if 'smoke failed' in log:raise RuntimeError(log[-2000:])
  time.sleep(2)
 else:raise RuntimeError('Installed APK physics test timed out')
 report['checks'].append('installed_apk_movement_jump_grounding_reload')
 assert 'Program linking failed' not in log and 'SCRIPT ERROR' not in log, 'Native renderer/script errors in installed APK'
 report['passed']=True
finally:
 (out/'android-qa.json').write_text(json.dumps(report,indent=2)+'\n')
 (out/'android-logcat.txt').write_bytes(call('logcat','-d',check=False))
print(json.dumps(report,indent=2))
