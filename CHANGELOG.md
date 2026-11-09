# Changelog

## Unreleased

### Neon Quarantine HD

- `tools/blendengine/create_realistic_soldier_showcase.py`: askar o'yinining GPU'li kompyuterlar uchun HD versiyasini yaratadi. Unda to'liq teksturali shahar real masshtabda, PBR materiallar, askar pozasi, kadrga chiqarilgan miltiq, HDRI, tuman va bake qilingan yorug'lik bor. Zombilar Play Mode'da o'yinchiga yuzi bilan yuradi.
- `docs/GRAPHICS.md` ga HD renderlar va Play Mode screenshoti qo'shildi; `docs/AI_GAME_CREATOR.md` ga haqiqiy interfeys screenshotlari qo'shildi.

- Zombilar butun askar modelidan "yuqtirilgan askarlar" sifatida quriladi (starter'dagi zombi meshi buzilgan va teksturasiz edi): chirigan teri, qon, uniforma va ko'zlar uchun qatlamli PBR materiallar. Asl model uchun `--zombie-model`.
- Runtime: NPC va o'yinchi yo'nalishi to'g'ri burchak bilan hisoblanadi (avval yon tomondagi nishonda ko'zgudagi aksiga qarardi); culling dunyo koordinatalaridagi chegaralovchi sferani ishlatadi (avval katta yoki parent ostidagi obyektlar noto'g'ri yashirilardi).
- AI rejalashtiruvchi: o'zgartirish so'rovidagi "lava qo'sh" endi dunyoni almashtirmaydi va mavjud xavflarga qo'shiladi.
- `docs/AI_GAME_CREATOR.md` ga AI interfeysining bosqichma-bosqich screenshotlari qo'shildi (menyu, dialog, natija, o'zgartirish, spec, sozlamalar).

### AI Game Creator

- G'oyadan o'ynaladigan o'yin yaratish: **AI Game Creator** paneli, Top Bar va Studio tugmalari, o'zgartirish so'rovi, yangi joylashuv va spec'dan qayta qurish.
- Claude rejalashtiruvchisi: rasmiy `anthropic` SDK, structured outputs (JSON Schema), `claude-opus-5-5` odatiy model, server tomonidagi refusal fallback, fon oqimida ishlash; add-on sozlamalarida API kalit va SDK o'rnatish tugmasi.
- Offline rejalashtiruvchi: o'zbek, ingliz va rus kalit so'zlari, sonlar va vaqt, o'zgartirish so'rovlari.
- Protsedural sahna quruvchi: 10 mavzu, 3D arena va 2D yon ko'rinish, umumiy mesh'lar, maqsadlar no-code qoidalar sifatida.
- `tools/blendengine/ai_create_game.py` buyruq qatori vositasi.
- Runtime: **Add To Variable**, **Collect Object**, **Win Game** amallari, NPC **Attack Damage**, `Victory`/`Game Over` holati, Stop'dan keyin sahnani tiklash, platformalarga qo'nish, 2D harakat, dunyo chegarasi, HUD'da maqsad va vaqt; yengilgan dushman qayta hisoblanmaydi.
- Testlar: `tests/python/blendengine_ai_spec.py` (Blender'siz) va `tests/python/blendengine_ai_creator.py` (headless o'yin sinovlari).

### Documentation

- Loyiha banneri va monogramma, arxitektura xaritasi, boshlang‘ich misol va navigatsiya qo‘shildi.
- Roadmap, baholash protokoli va reliz tartibi hujjatlashtirildi.
- Hujjatlar tekshiruvi uchun alohida CI workflow qo‘shildi.

Bu yozuv dastur relizi emas. Ilova manba kodi ushbu hujjatlashtirish ishida o‘zgartirilmadi. Oldingi o‘zgarishlar tarixi commitlarda saqlanadi; bu yerda qayta to‘qib yozilmagan.
