#!/usr/bin/env python3
import pathlib,subprocess,time,json,tempfile
root=pathlib.Path(__file__).resolve().parents[2];project=root/'native/z3wax'
with tempfile.TemporaryDirectory() as temp:
 temp=pathlib.Path(temp);logs=[];processes=[]
 try:
  f=(temp/'server.log').open('w');logs.append(f)
  server=subprocess.Popen(['godot','--headless','--path',str(project),'--','--server'],stdout=f,stderr=subprocess.STDOUT);processes.append(server)
  deadline=time.monotonic()+30
  while 'Z3WAX_SERVER_READY' not in (temp/'server.log').read_text():
   if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError((temp/'server.log').read_text())
   time.sleep(.2)
  for i in range(2):
   f=(temp/f'client{i}.log').open('w');logs.append(f)
   processes.append(subprocess.Popen(['godot','--headless','--path',str(project),'--','--network-test'],stdout=f,stderr=subprocess.STDOUT))
  for p in processes[1:]:assert p.wait(timeout=45)==0
  for i in range(2):
   text=(temp/f'client{i}.log').read_text();assert 'Z3WAX_NETWORK_PASS snapshots=20 actors=2' in text,text
  print('Z3WAX_TWO_CLIENT_PASS authoritative ENet snapshots across 3 processes')
 finally:
  for p in processes:
   if p.poll() is None:p.terminate()
  for p in processes:p.wait(timeout=15)
  for f in logs:f.close()
