# Changelog

## Unreleased

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
