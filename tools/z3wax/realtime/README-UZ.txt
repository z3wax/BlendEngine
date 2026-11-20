Z3WAX — Ubuntu uchun o‘ynaladigan realtime alpha

Bu paket Godot real-time renderida ishlaydi. Cycles worker ishga tushirilmaydi.
Bu hali tayyor PUBG darajasidagi release emas: karta kontenti va ko‘p o‘yin
mexanikalari tugallanmagan. Android/iOS tasdiqlangan build bu paketga kirmaydi.

Ishga tushirish:
  tar -xzf Z3WAX-Ubuntu-Realtime.tar.gz
  cd Z3WAX-Ubuntu-Realtime
  ./play.sh
  Menyuda START TRAINING: siz + 7 ta bot.

Boshqaruv:
  WASD — yurish; sichqoncha — kamera; chap tugma — otish;
  Space — sakrash; R — qayta o‘qlash; M — karta;
  Escape — kursorni bo‘shatish/qayta ushlash. LOBBY — menyuga qaytish.

Grafika tugmasi:
  NATIVE — 100% 3D o‘lcham, asl soyalar va 2x MSAA.
  BALANCED — 30 FPS maqsad; 75–100% 3D o‘lcham, qisqaroq soya masofasi.
  SPEED — 60 FPS maqsad; 50–100% 3D o‘lcham, uzoq qurol soyasi o‘chadi.
  Maqsad FPS kafolat emas. Oxirgi ikki rejim tasvir aniqligini pasaytirishi
  mumkin. Tekstura fayllari kichraytirilmaydi. UI asl o‘lchamda qoladi.
  Ko‘rsatilgan FPS va p95 o‘yinning real kadr vaqtiga asoslanadi.

Sekin kompyuterda: ./play-speed.sh

O‘z Ubuntu kompyuteringizdagi server:
  Alohida terminalda ./server.sh
  Ikkinchi terminalda ./play.sh
  CONNECT TO SERVER: 127.0.0.1 (shu kompyuter) yoki serverning LAN IP manzili.
  Boshqa qurilmalar uchun UDP 28416 tarmoq orqali ochiq bo‘lishi kerak.
  Server dasturi va o‘yin mahalliy ishlaydi; hosting/ommaviy server talab qilinmaydi.

Muhim o‘lchov chegarasi:
  Dasturlash muhitida haqiqiy GPU yo‘q, llvmpipe ishlatilgan. Shu muhitda
  avvalgi sahna ~2.8 FPS, yangi Native ~3 FPS, Speed ~12 FPS bo‘ldi.
  Bu natijalar sizning videokartangiz yoki telefoningiz tezligini bildirmaydi.
  Sinovlar harakat, sakrash, o‘qlash, otish va protokolni tekshiradi;
  ular o‘yinni xatosiz yoki 30/60 FPS tayyor release deb tasdiqlamaydi.

Model mualliflari va litsenziyalar: licenses/ASSETS.md
Manba: https://github.com/z3wax/BlendEngine/pull/6
