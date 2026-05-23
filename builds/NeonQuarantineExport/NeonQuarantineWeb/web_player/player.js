const canvas = document.getElementById('game');
const ctx = canvas.getContext('2d');
const hud = document.getElementById('hud');
const keys = new Set();
let data, player, last = performance.now(), fps = 0;

function resize(){ canvas.width = innerWidth * devicePixelRatio; canvas.height = innerHeight * devicePixelRatio; }
addEventListener('resize', resize); resize();
addEventListener('keydown', e => keys.add(e.key.toLowerCase()));
addEventListener('keyup', e => keys.delete(e.key.toLowerCase()));

function color(tag, type){
  if(tag === 'Player' || tag === 'PlayerBody') return '#00d7bd';
  if(tag === 'Enemy' || tag === 'Zombie') return '#c53333';
  if(tag === 'Coin') return '#f5bf35';
  if(tag === 'Damage') return '#d82188';
  if(tag === 'Health') return '#39e876';
  if(tag === 'Water') return '#4ab6c7';
  if(type === 'LIGHT') return '#f7cf67';
  return '#60696d';
}

function worldToScreen(x,y){
  const s = Math.min(canvas.width, canvas.height) / 34;
  return [canvas.width/2 + (x - player.location[0]) * s, canvas.height/2 - (y - player.location[1]) * s];
}

function update(dt){
  const speed = (keys.has('shift') ? 8 : 5) * dt;
  if(keys.has('w')) player.location[1] += speed;
  if(keys.has('s')) player.location[1] -= speed;
  if(keys.has('a')) player.location[0] -= speed;
  if(keys.has('d')) player.location[0] += speed;
}

function draw(){
  ctx.fillStyle = '#0b130f';
  ctx.fillRect(0,0,canvas.width,canvas.height);
  ctx.strokeStyle = 'rgba(255,255,255,.055)';
  for(let i=-24;i<=24;i++){
    const [x1,y1]=worldToScreen(i,-24), [x2,y2]=worldToScreen(i,24);
    ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
    const [x3,y3]=worldToScreen(-24,i), [x4,y4]=worldToScreen(24,i);
    ctx.beginPath(); ctx.moveTo(x3,y3); ctx.lineTo(x4,y4); ctx.stroke();
  }
  for(const obj of data.objects){
    const [x,y]=worldToScreen(obj.location[0], obj.location[1]);
    const r = (obj.tag === 'Player' || obj.tag === 'PlayerBody') ? 14 : (obj.tag === 'Enemy' || obj.tag === 'Zombie') ? 12 : obj.tag === 'Coin' ? 8 : 10;
    ctx.fillStyle = color(obj.tag, obj.type);
    ctx.globalAlpha = obj.tag === 'Ground' ? .2 : .95;
    ctx.beginPath(); ctx.arc(x,y,r,0,Math.PI*2); ctx.fill();
  }
  ctx.globalAlpha = 1;
  hud.innerHTML = `<b>${data.project.title}</b><br>FPS ${fps.toFixed(0)} | Objects ${data.objects.length}<br>WASD move, Shift sprint<br>${data.project.target_platform} web preview`;
}

function loop(now){
  const dt = Math.min((now-last)/1000, .05); last = now; fps = 1/dt;
  update(dt); draw(); requestAnimationFrame(loop);
}

fetch('game_data.json').then(r=>r.json()).then(json=>{
  data = json;
  player = data.objects.find(o => o.player_controller && o.player_controller.enabled) || data.objects[0];
  requestAnimationFrame(loop);
});
