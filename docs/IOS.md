# Native iOS / imzosiz IPA

[LastSignal-AI-unsigned.ipa](https://github.com/z3wax/BlendEngine/releases/download/last-signal-ai-ios-v1/LastSignal-AI-unsigned.ipa)
va [reliz fayllari](https://github.com/z3wax/BlendEngine/releases/tag/last-signal-ai-ios-v1).

Bu **imzosiz IPA**: oddiy iPhonega o'rnatishdan oldin haqiqiy Apple imzosi va
mos provisioning profile bilan imzolanishi kerak. Buildda Apple Developer
sertifikati ishlatilmaydi. Simulator uchun chiqarilgan alohida ilova ZIP'i
jismoniy iPhone uchun IPA o'rnini bosmaydi.

O'yin Godot 4.6.3 C++ runtime va OpenGL ES 3 Compatibility rendererida ishlaydi.
WebView yoki browser o'yini ochilmaydi. Maya va mustaqil Rescue Scout, native
fizika, skelet animatsiyasi va beshta izli birinchi bob mavjud. Adapter Godotning
iOS 14 minimumini ishlatadi; jismoniy qurilma va FPS alohida tekshirilishi kerak.

## Mac'da chiqarish

Xcode o'rnatilgan macOS'da repozitoriyni oching:

```sh
tools/ios/setup_toolchain.sh
python3 tools/ios/build_ios.py --project native/android_game \
  --output /tmp/LastSignal-AI-unsigned.ipa --qa --proof-dir /tmp/ios-proof
```

Setup aynan Godot 4.6.3 macOS editori va iOS template'ini rasmiy manbadan
yuklab, SHA-256 ni tekshiradi. Godot haqiqiy Xcode loyiha yaratadi; Xcode
`iphoneos` uchun ARM64 executable va resurslarni yig'adi. `CODE_SIGNING_ALLOWED=NO`
ishlatiladi va ad-hoc imzo bo'lsa olib tashlanadi. `Payload/*.app` IPA ichiga
joylanadi. U shunchaki nomi o'zgartirilgan ZIP emas.

Godot loyiha generatsiyasi uchun talab qiladigan `0000000000` Team ID qiymati
faqat unsigned eksport placeholder'idir; u haqiqiy Apple team yoki imzo emas.
Natija ARM64 Mach-O device platformasi, Info.plist, Godot pack, CRC va SHA-256
bilan tekshiriladi. Simulator executable'ini device IPA sifatida qabul qilmaydi.

## Engine editoridan eksport

Build panelida **IOS** ni tanlang. iOS Bundle ID, versiya, build raqami,
Godot executable va **Native SDK Root** ni belgilang. Last Signal sahnasi va
NPC sozlamalari native Godot loyihasiga chiqariladi. Linux/Windows'dagi editor
faqat shu loyihani tayyorlaydi; IPA uchun uni Mac'dagi build launcher bilan
yig'ing. Linux'da mavjud bo'lmagan IPA muvaffaqiyatli deb ko'rsatilmaydi.

Bu adapter Last Signal va uning beshta qo'llangan NPC xulqiga mo'ljallangan.
NPC boshqa grafik modelni qayta bake qilmaydi: Maya'ning mesh/material
resurslarini qayta ishlatib, mustaqil skeleton va fizik tanani oladi.
Qarang: [AI agentlari](AI_AGENTS.md).

## Tekshiruv va dalillar

GitHubdagi **Build native unsigned iOS IPA** workflow'i macOS/Xcode bilan
device IPA va alohida iOS Simulator ilovasini yaratadi. Simulator'da:

- oddiy launch va native sahna yuklanishi;
- o'yinchi turganda Scoutning yurishi va alohida skelet animatsiyasi;
- izlarni NPC o'yinchi o'rniga yig'masligi;
- beshta iz, uchta sakrash va yerda/platformada turgan missiya yakuni;
- NPC devordan aylanib o'tishi, pause, checkpoint va restart tekshiriladi.

Simulator hisobotida `passed` bo'lmasa IPA relizga chiqmaydi. Device IPA
strukturasi tekshirilishi jismoniy iPhonega o'rnatish sinovi degani emas.
Simulator tekshiruvi UIKit sensorli bosish avtomatizatsiyasini da'vo qilmaydi.
PNG, video, simulator ZIP'i, build loglari va JSON hisobotlar relizga qo'shiladi;
videodagi simulator FPS'i haqiqiy iPhone FPS ko'rsatkichi emas.

Android loyihasining grafik presetlari o'zgartirilmaydi. iOS tayyorlash alohida
nusxada amalga oshadi; mavjud teksturalar, soya va AA sozlamalari pasaytirilmaydi.
