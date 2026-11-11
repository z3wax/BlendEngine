# BlendEngine grafikasi

Bu bosqich mavjud EEVEE rendererini ishlatadi: sifat profillari endi faqat loyiha
metadatasini emas, haqiqiy render sozlamalarini ham o'zgartiradi.

## Ishlatish

BlendEngine qo'shimchasini yoqing va Optimization sahifasidagi **Graphics &
Performance** bo'limini oching. **High** yoki **Cinematic** tugmasini bosing.
Ro'yxatdan profil tanlasangiz, **Apply Selected Profile** bilan qo'llang.
Qiymatlarni qo'lda tahrirlagandan keyin **Custom** tugmasini bosing.
Natijani Material Preview o'rniga **Rendered** ko'rinishida yoki F12 orqali ko'ring.

| Rejim | Viewport / render namunalari | Akslar | Asosiy maqsad |
|---|---|---|---|
| Ultra Low | 1 / 1 | O'chirilgan | Eng kam render xarajati |
| Low | 8 / 16 | O'chirilgan | Yengil qurilmalar |
| Balanced | 32 / 64 | O'chirilgan | Muvozanatli sahna |
| High | 64 / 128 | Next: yarim, legacy: to'liq aniqlikda | Desktop o'yin sahnalari |
| Cinematic | 128 / 256 | To'liq aniqlikda | Kuchli qurilmalar va rasm olish |

High va Cinematic rejimlari yumshoq soyalar, ambient occlusion, akslar va
yorqin joylardagi detallarni saqlovchi rang ishlovini sozlaydi. Blender 3.6 uchun
Filmic, 4.3 uchun AgX ishlatiladi. Ekspozitsiya va gamma saqlanadi.
3.6 da High soyalar 2048, Cinematic soyalar 4096 aniqlikda bo'ladi; EEVEE Next
o'zining shadow ray va shadow pool sozlamalarini ishlatadi.

Yangi Windows, Linux va macOS loyihalari High bilan boshlanadi. Magic Create
Game desktop uchun 1 GB rejimini majburan qo'llab, barcha chiroqlar soyasini
o'chirmaydi. Android/iOS uchun mavjud yengil profil saqlangan. Oldingi faylda
1 GB rejimi chiroqlar soyasini allaqachon o'chirgan bo'lsa, u chiroqlarning
**Shadow** sozlamasini keraklicha yoqing: sifat tugmasi chiroqlarni qayta yozmaydi.

Starter sahnalardagi tosh, yer, devor, yog'och va asfalt materiallarida
procedural rang, roughness va bump mavjud. Tashqi tekstura fayllari kerak emas.

## Cinematic Look

Sifat profili renderer qancha hisoblashini tanlaydi. **Optimize → Cinematic
Look → Apply Cinematic Look** esa kadrni kino ko'rinishiga keltiradi:

- Cinematic profilini qo'llaydi;
- sahna kamerasiga obyektiv beradi: depth of field, `F-Stop` (standart 2.8).
  Uchinchi shaxsda fokus o'yinchida. Birinchi shaxsda kamera o'yinchining
  ichida bo'lgani uchun fokus obyekti qo'yilmaydi, muallif bergan masofa qoladi;
- overscan (ekran chetida screen-space effektlar so'nmasligi uchun), yumshoq va
  jitter'li soyalar, past `light_threshold`, yuqori sifatli normallar, aniq
  (jittered) bokeh;
- compositor'ga bloom, yengil linza dispersiyasi va vinyetka qo'shadi va
  rendered viewport'da compositor'ni yoqadi.

Compositor tugunlari faqat tegilmagan grafga (Render Layers → Composite)
qo'shiladi; muallif yozgan graf o'zgartirilmaydi. **Remove Cinematic Post
Effects** qo'shilgan tugunlarni olib tashlaydi. Blender 5.x compositor API'si
boshqacha: u yerda obyektiv va renderer sozlamalari qo'llanadi, post effektlar
"not available" deb xabar qilinadi.

Kinematik sozlamada o'yin yengil qolishi uchun sahnani
[Smart Optimizer](OPTIMIZER.md) bilan tayyorlang: u renderer sifatiga tegmaydi,
faqat kamera ko'rmaydigan va ekran ajrata olmaydigan ma'lumotni olib tashlaydi.

## Namuna o'yin: Highland Patrol

![Highland Patrol: birinchi shaxs ko'rinishi](graphics/highland_patrol.png)

Ochiq maydondagi birinchi shaxs shooter shabloni: tog' vodiysi, qoya,
qarag'aylar, o't, past quyosh, qo'ldagi miltiq va patrul qilayotgan 6 dushman.
Hammasi `scripts/addons_core/blendengine/highland.py` ichida koddan yaratiladi —
model yoki tekstura fayli yo'q. Bu boshqa o'yinning nusxasi emas: relyef, qurol
va figuralar shu repoda yozilgan.

Editor'da: **Quick Start → Highland Patrol (Outdoor FPS)** yoki **Magic Create**
ro'yxatidan. Keyin **Test Run**: WASD — yurish, sichqonchaning chap tugmasi yoki
F — otish. O'yinchi `Ground` tegli relyef bo'ylab yuradi; o'q dushmanga
ray cast bilan tegadi.

```bash
blender -b --factory-startup --python-exit-code 1 \
  --python tools/blendengine/create_highland_patrol.py -- \
  --output-dir /tmp/highland --render
```

Rasm: Blender 4.3.0 EEVEE Next, 1280×720, 16 namuna, dasturiy render. Sahna:
2697 obyekt, 523 ming uchburchak, 18 ta mesh (daraxt, o't va toshlar bitta
mesh'ni ulashadi), tekstura xotirasi 0 MB. `--optimize` bilan Smart Optimizer
47 ta ko'rinmas obyektni va 14 ming uchburchakni olib tashlaydi (sahna
boshidanoq instancing bilan qurilgani uchun tejam kichik) va occlusion
to'plamlarini tayyorlaydi; bu sahnada tahlil taxminan 2 daqiqa.

Chegaralar: dushmanlar va qurol sodda geometrik shakllar, animatsiya yo'q;
o'yinchi daraxt va toshlardan o'tib ketadi (runtime to'qnashuvni to'xtatmaydi);
dushman relyef balandligiga ergashmaydi. FPS o'lchanmagan (GPU'siz muhit).
Sinov: `tests/python/blendengine_highland.py` (6 test, Blender 4.3.0).

## Namuna: Aperture Hall

![EEVEE yordamida render qilingan Aperture Hall](graphics/aperture_hall.png)

Rasm: Blender 4.3.2 EEVEE Next, 960×540, 16 namuna. Dasturiy render uchun
rasmning namuna soni kamaytirilgan; to'liq aniqlikdagi akslar va Cinematic
soyalar saqlangan. Cinematic profilining odatiy render namunalari soni 256.

Sahna geometriyasi, PBR materiallari va yoritishi loyiha ichidagi Python
generatorida yaratiladi. Yuklab olinadigan modellar yoki teksturalar yo'q.
Generator faqat yangi, alohida ishga tushirilgan Blender sessiyasida qo'llanadi;
joriy sahna obyektlarini tozalaydi.

Repo ildizidan:

```bash
blender -b --factory-startup --python-exit-code 1 \
  --python tools/blendengine/create_graphics_showcase.py -- \
  --output-dir /tmp/blendengine-showcase --render
```

Natijalar: `aperture_hall.blend` va `aperture_hall.png`. `.blend` faylini
Blender/BlendEngine'da oching. Faqat sahnani yaratish uchun `--render` ni
olib tashlang. Windowsda `blender.exe` va o'zingizning chiqish papkangizni
ko'rsating. Rasm renderi uchun xotira va vaqt talab qilinadi; `--width 640
--height 360 --samples 24` bilan tezroq tekshirish mumkin.

## Tekshirish

```bash
blender -b --factory-startup --python-exit-code 1 \
  --python tests/python/blendengine_graphics.py
```

Linuxda rasmiy Blender 3.6.23 binary bilan 12 integratsion test o'tdi.
Blender 4.3.2 bilan 11 test o'tdi, manbadagi 3.6 starter generatoriga tegishli
bitta test ochiq ravishda o'tkazib yuborildi. Testlar haqiqiy bpy API orqali
sifatning o'zgarishi, Custom, Cycles/Workbench saqlanishi, sahna va compositor
saqlanishi, desktop yaratish oqimi, materiallar va faylni qayta ochishni tekshiradi.
Namuna sahna 3.6.23 da yaratilib saqlandi, 4.3.2 EEVEE bilan PNG render qilindi.
Bu natijalar o'zgartirilgan C/C++ manbasining to'liq build sinovi emas.

## Hozirgi chegaralar

- Sifat profili EEVEE uchun ishlaydi. Cycles yoki Workbench tanlangan sahnada
  renderer va uning sozlamalari almashtirilmaydi.
- EEVEE Next'da bloom compositor orqali yaratiladi. Profil mavjud compositor
  grafini o'zgartirmaydi; namuna sahnasida alohida yengil glow effekti bor.
- Volumetric sifat mavjud hajm materiallarini sozlaydi; profil tuman yaratmaydi
  yoki mavjud tuman materialini olib tashlamaydi. Legacy EEVEE uchun chiroq
  soyasini boshqarish chiroqning o'zida qoladi.
- FPS qiymatlari maqsadli budjetdir; o'lchangan tezlik yoki barcha qurilmalarda
  ishlash kafolati emas. FXAA belgisi EEVEE'da yengil temporal samplingga moslanadi.
- Bu Unreal'ning Lumen/Nanite tizimlari yoki beshta platformaga tayyor native
  eksport implementatsiyasi emas. Bu o'zgarish grafika bosqichiga tegishli;
  Android, iOS, macOS, Linux va Windows buildlari alohida tekshirilishi kerak.
