# Editor yordamchisi va o'yin agentlari

BlendEngine ikki xil agentni qo'llaydi: sahnani tuzishga yordam beruvchi editor
agent va personajlarni mustaqil boshqaruvchi o'yin AI tizimi. Ikkalasi native
Blender/Godot ish jarayonida ishlaydi. O'yindagi NPC uchun internet, model yoki
API kaliti talab qilinmaydi.

## Editor agentini ishlatish

Blender'da BlendEngine addonini yoqing. 3D View oynasida **N → AI → Scene Agent**
panelini oching. **Offline tools** rejimida quyidagilarni yozish mumkin:

- `qizil kub qo'sh`
- `add a blue sphere`
- `NPC qo'sh`
- `tanlangan obyektni 2, 3, 1 ga ko'chir`
- `o'yinchiga ergashsin`
- `sahnani tahlil qil`

**Make Plan** faqat reja tayyorlaydi. Ko'rsatilgan amallarni **Apply Plan**
bajaradi; **Undo** bilan qaytarish mumkin. Reja tuzilgandagi tanlov saqlanadi:
keyin boshqa obyekt tanlansa ham reja birinchi obyektga tegishli bo'ladi.
Obyekt o'chirib qayta yaratilsa, eski reja uni o'zgartira olmaydi. Play ishlayotgan
paytda avval Stop bosing.

Offline rejim kichik buyruq rejalashtiruvchisi; u til modeli emas. Qo'llanmagan
so'rovni bajarilgandek ko'rsatmaydi. Obyekt, material, joylashuv, NPC xulqi va
sahna tahlili uchun chegaralangan amallar mavjud. Grafik sifatini pasaytiruvchi,
fayl o'chiruvchi yoki erkin Python bajaruvchi amallar yo'q. Paketdagi hamma
amal oldindan tekshiriladi; bajarish xatosida o'zgarishlar qaytariladi.

## Til modelini ulash

**Planner → Language model** ni tanlang. OpenAI-compatible chat-completions
serverining endpoint va model nomini kiriting. Masalan, kompyuterda alohida
o'rnatilgan Ollama serveri uchun `http://127.0.0.1:11434/v1` va siz o'rnatgan
model nomi ishlatiladi. Model vaznlari addon yoki APK ichiga qo'shilmaydi.
Ularni ishga tushirish uchun kerakli RAM va hisoblash vaqti alohida talabdir.

Remote server HTTPS orqali ulanadi. **API key environment variable** maydoniga
kalitning o'zini emas, Blender ishga tushirilishidan oldin tizimda o'rnatilgan
muhit o'zgaruvchisi nomini yozing; standart nom `BLENDENGINE_AI_API_KEY`.
Kalit `.blend`, o'yin JSON'i yoki APKga saqlanmaydi.

Make Plan bosilgandagina so'rov va sahnaning cheklangan xulosasi tanlangan
serverga yuboriladi. So'rov background thread'da ishlaydi; u Blender API'larini
o'zgartirmaydi. Javob ham o'sha cheklangan amallar sxemasidan o'tadi, so'ng
Apply Plan bilan bajariladi. **Cancel Request** javobning keyinroq kelib sahnani
o'zgartirishiga yo'l qo'ymaydi; ketayotgan HTTP so'rovi timeoutgacha davom etishi
mumkin. Lokal HTTP server bilan transport tekshirilgan; haqiqiy tashqi model
hisobi yoki pullik so'rov testda ishlatilmagan.

## O'yin ichidagi NPC

**New Agent Demo** Last Signal sahnasini yordamchi Rescue Scout bilan yaratadi.
NPC alohida skelet va animatsiyaga ega; asosiy personajning mesh va material
resurslarini qayta ishlatadi. Harakat va fizika har bir simulyatsiya qadamida,
qaror qabul qilish esa odatda 0,15 soniya oralig'ida bajariladi.

- **Follow Player:** ko'rish/aniqlash masofasida o'yinchiga ergashadi va yaqinida to'xtaydi.
- **Patrol:** boshlang'ich joyi atrofidagi nuqtalar bo'ylab yuradi.
- **Guard:** hududni kuzatadi va maqsad yo'qolganda joyiga qaytadi.
- **Guide:** keyingi topilmagan iz tomon yo'l ko'rsatadi, o'yinchi uzoqlashsa kutadi.
- **Idle:** joyida turadi.

Agent devorlardan o'tmaydi: keshdagi geometriya, cheklangan yo'l qidiruvi va
harakat tekshiruvlaridan foydalanadi. Guide izlarni o'yinchi o'rniga yig'maydi
va o'yinchiga zarar yetkazmaydi. Pause tanasi va animatsiyasini to'xtatadi;
Restart/Stop boshlang'ich holatni tiklaydi. Editor runtime'ida avvalgi dushman
shablonlari ham saqlangan.

Native Android/Godot adapteri yuqoridagi beshta xulqni va eng ko'p 8 agentni
qo'llaydi. Native eksport qilinmagan dushman shablonida aniq xato beradi.
NPC sozlamalari `story.json` dagi `npc_agents` orqali uzatiladi; `[]` agentlarni
o'chiradi. Avatar geometriyasi qayta bake qilinmaydi; shu sababli katta nusxa
teksturalari APKga qo'shilmaydi. Maxsus boshqa avatarni native adapterga
avtomatik tarjima qilish bu bosqichga kirmaydi.

## Tekshiruv

```sh
python3 -m unittest discover -s tests/python -p 'blendengine_agent_*.py'
blender -b --factory-startup --python-exit-code 1 --python tests/python/blendengine_editor_agent.py
blender -b --factory-startup --python-exit-code 1 --python tests/python/blendengine_ai.py
bash native/android_game/tests/agent_smoke.sh
bash native/android_game/tests/smoke.sh
```

Editor testlari haqiqiy operator, lokal HTTP javobi, bekor qilish, eskirgan reja
va sahnani qaytarishni tekshiradi. NPC testlari devor atrofidan aylanib o'tish,
mustaqil skelet animatsiyasi, pause/restart va missiya yakunini tekshiradi.
Blender va Android renderer sozlamalari, teksturalar va mavjud GLB o'zgartirilmaydi.
