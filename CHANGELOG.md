# Changelog

## Unreleased

### BlendEngine add-on

- Smart Optimizer: kamera ko'ra olmaydigan yuz va obyektlarni olib tashlash, bir xil material va mesh'larni birlashtirish, teksturalarni ekran pikseli ajrata oladigan o'lchamga moslash, occlusion uchun ko'rinuvchi to'plamlar va LOD mesh'lar. Asllar saqlanadi va qaytariladi.
- Runtime: chegaralovchi sfera bo'yicha frustum culling, saqlangan to'plamlar bo'yicha occlusion culling, LOD almashtirish, kadr vaqtiga qarab sifat boshqaruvchisi. EEVEE Next'da kadrdan tashqaridagi obyektlar soyasi saqlanadi. Test Run tugaganda ko'rinish holati qaytariladi.
- Highland Patrol: koddan yaratiladigan ochiq maydon birinchi shaxs shooter shabloni (relyef, qoyalar, qarag'aylar, o't, osmon, miltiq, dushmanlar). Tashqi model va teksturasiz.
- Cinematic Look: obyektiv (depth of field), overscan, yumshoq soyalar va olib tashlanadigan compositor effektlari.
- `tests/python/blendengine_optimizer.py` va `tools/blendengine/optimizer_benchmark.py` qo'shildi. Batafsil: [docs/OPTIMIZER.md](docs/OPTIMIZER.md).

### Documentation

- Loyiha banneri va monogramma, arxitektura xaritasi, boshlang‘ich misol va navigatsiya qo‘shildi.
- Roadmap, baholash protokoli va reliz tartibi hujjatlashtirildi.
- Hujjatlar tekshiruvi uchun alohida CI workflow qo‘shildi.

Bu yozuv dastur relizi emas. Blender C/C++ manbasi o‘zgartirilmadi; o‘zgarishlar BlendEngine Python qo‘shimchasiga tegishli. Oldingi o‘zgarishlar tarixi commitlarda saqlanadi; bu yerda qayta to‘qib yozilmagan.
