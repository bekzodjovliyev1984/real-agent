# 🎬 O'zbekcha YouTube Shorts ishlab chiqarish tizimi

AI yordamida o'zbek tilida qisqa ilmiy-ommabop Shorts yasaydigan avtomatik tizim. Mavzular: sun'iy intellekt, yangi
texnologiyalar, yangi mashinalar, ilm-fan, ta'lim. Har video quyidagi bosqichlardan o'tadi: tadqiqot →
fakt-tekshiruv → ssenariy → storyboard → kadr qidirish → ovoz → subtitr → montaj → sifat nazorati. Nashr faqat
sizning Telegram'dagi ruxsatingiz bilan bo'ladi, sinov paytida standart holatda **private**.

> Maqsad ko'p video emas. Maqsad: faktlari tekshirilgan, kadrlari gapga mos, ovozi tabiiy, yaxshi montaj
> qilingan, odamlar haqiqatan ko'rishni xohlaydigan Shorts.

---

## 1. Eski tizimdagi muammolar va ularning sababi

| Muammo | Sabab (kodda) |
|---|---|
| Ovoz robotga o'xshaydi, to'xtab-to'xtab gapiradi | Faqat Microsoft Sardor ovozi ishlatilgan. Raqam va chet so'zlar ovozga tayyorlanmagan |
| Bitta statik rasm, kadr gapga mos emas | Rasm sarlavha bo'yicha olingan, kadrning o'zi tekshirilmagan. Video manbalar yo'q edi |
| Ssenariy zerikarli | Hikoya tuzilmasi (hook → payoff) yo'q edi. Faktlar tekshirilmagan |
| Faktlar tekshirilmagan | AI'ning ishonchli ohangi dalil sifatida qabul qilingan, manba URL'lari tekshirilmagan |
| Sifat nazorati yo'q | Quvur tugasa, video "tayyor" deb hisoblangan |
| Ish buzilsa, boshidan boshlanadi | Holat saqlanmagan |

## 2. Nima o'zgardi

- **Fakt-tekshiruv (B):** har da'vo mustaqil qidiruv bilan tekshiriladi. AI ko'rsatgan URL tekshiruv matnida haqiqatan
  bo'lishi va HTTP orqali ochilishi kerak. Manbasi qolmagan da'vo `unverified` bo'ladi va **nashrni bloklaydi**.
- **Ssenariy (C):** faqat tasdiqlangan da'volardan yoziladi. Tuzilma: hook → setup → development → payoff.
  Diktor matnida raqamlar so'z bilan yoziladi, salomlashish va "like bosing" yo'q.
- **Storyboard (D):** har sahnada kadr tavsifi, maqsadi, 2-4 ta inglizcha qidiruv, mezon va tegishli da'vo bor.
  Ssenariy matni o'zgartirilsa (>10%), storyboard rad etiladi.
- **Vizual qidiruv (E):** Pexels/Pixabay stok-videolari, Wikimedia Commons arxivi, yangilik sahifasining rasmi.
  Har nomzod o'lcham, davomiylik va takror bo'yicha tekshiriladi, keyin **AI kadrlarning o'ziga qarab**
  mosligini baholaydi. Mos kadr topilmasa, aloqasiz kadr qo'yilmaydi: sahna faktini ko'rsatuvchi grafika
  yasaladi. Litsenziya va muallif ma'lumotlari saqlanadi.
- **AI video (F):** OpenAI Sora adapteri bor, lekin standart holatda o'chiq. AI kadrlar ekranda "AI TASVIR" deb belgilanadi.
- **Ovoz (G, H):** OpenAI `gpt-4o-mini-tts` (uslub `instructions` bilan beriladi) va Microsoft Edge adapterlari bor.
  Butun matn **bir marta** o'qitiladi, shuning uchun ohang uzilmaydi. Talaffuz lug'ati bor
  (`OpenAI → Open Ey Ay`). Ovoz balandligi ikki bosqichli loudnorm bilan −14 LUFS'ga tekislanadi. Faqat
  boshidagi va oxiridagi jimlik kesiladi, gaplar orasidagi pauzalar saqlanadi.
- **Subtitrlar (I):** vaqt haqiqiy ovozdan olinadi (TTS so'z vaqtlari yoki whisper). Taxminiy vaqt bo'lsa,
  QA nashrni to'xtatadi. Ekranda toza imloli matn ko'rinadi, ovozga ketgan matn alohida saqlanadi.
  Subtitr 2-4 so'zdan iborat, Shorts tugmalari ostiga tushmaydi. Raqamlar sariq rangda ajratiladi.
- **Montaj (J):** kadr cho'zilmaydi. Gorizontal kadr kenglik bo'yicha sig'diriladi va orqasiga uning xira
  versiyasi qo'yiladi. Rasmlar sekin yaqinlashadi. O'tishlar odatda toza kesish, rejada bo'lsa crossfade.
  Natija: 1080×1920, H.264, yuv420p, 30 fps, AAC.
- **Sifat nazorati (K):** tayyor video tekshiriladi: ffprobe, qora va qotib qolgan kadrlar, LUFS, clipping,
  uzun jimlik, A/V sinxronligi, subtitrlar, litsenziyalar. Keyin har sahnadan kadr olinib, AI tomonidan
  baholanadi. Ballar chegaradan past bo'lsa, ko'pi bilan **2 marta** tegishli bosqich qayta bajariladi
  (faqat kadrlar, faqat ovoz yoki faqat subtitr), keyin holat `needs_review` bo'ladi.
- **Nashr (L):** faqat `approved` holatidagi video yuklanadi. `needs_review` holatidagi video ham faqat siz
  Telegram'da ko'rib tasdiqlasangiz va fakt yoki texnik xato bo'lmasa yuklanadi. Standart maxfiylik `private`.
  Yuklashda uzilish bo'lsa qayta uriniladi. Yuklangandan keyin videoning haqiqiy holati tekshiriladi.
- **Analitika (M):** SQLite bazasi va YouTube Analytics API. Videolar soha va hook turi bo'yicha bir xil vaqt
  oynasida solishtiriladi. Xulosa keyingi mavzu tanlashda yo'nalish sifatida ishlatiladi.
- **Ish holati:** har video `data/jobs/<id>/` papkasida saqlanadi. Holatlar: `planned → researched → scripted →
  assets_ready → audio_ready → rendered → approved / qa_failed / needs_review → published`. Dastur to'xtab qolsa,
  `resume` buyrug'i bilan to'xtagan joyidan davom etadi.

## 3. Tuzilma

```
youtube_agent/
  orchestrator.py      quvur: bosqichlar, davom ettirish, tuzatish halqasi, xarajat hisobi
  topic_agent.py       A. mavzu tadqiqoti (veb-qidiruv, faqat ishonchli saytlar)
  fact_checker.py      B. fakt-tekshiruv (URL mavjudligi va ochilishi tekshiriladi)
  script_agent.py      C. ssenariy (hook → payoff, faqat tasdiqlangan da'volar)
  storyboard_agent.py  D. sahnalar va vizual reja
  visual_search.py     E. Pexels / Pixabay / Wikimedia / manba rasmi + AI bilan kadr tekshiruvi
  video_generator.py   F. Sora adapteri (ixtiyoriy)
  tts.py               G. OpenAI va Edge TTS, talaffuz lug'ati
  audio_processing.py  H. jimlikni kesish, loudnorm, o'lchovlar, musiqa (sidechain) va effektlar
  subtitles.py         I. whisper bilan moslash, ASS subtitrlar
  render.py            J. FFmpeg montaj
  quality_gate.py      K. texnik va mazmuniy QA, qaror va yo'naltirish
  publishing.py        L. faqat tasdiqlangan videolarni nashr qilish
  analytics.py         M. YouTube Analytics + SQLite + taqqoslash
  schemas.py           Pydantic JSON shartnomalar (ShortPlan, Claim, Scene, AssetMeta, QAReport...)
  jobs.py              ish papkasi, atomik yozish, holat, log, retry
  llm.py               Claude / OpenAI: research, parse, rasm bilan baholash
  categories.py        sohalar va ularning manbalari
  prompts/*.md         barcha AI ko'rsatmalari (kodga tegmasdan tahrirlash mumkin)
  resources/pronunciation.json
  agent.py, telegram.py, youtube.py, content.py, state.py   Telegram, jadval, kommentlar
  benchmark.py         TTS ovozlarini solishtirish
tests/                 38 ta test (mock + haqiqiy ffmpeg)
docs/examples/         namunaviy plan.json va qa_report.json
```

## 4. O'rnatish (Windows)

```
cd %USERPROFILE%\real-agent
git pull
.venv\Scripts\activate
pip install -r requirements.txt
```
Kerakli dasturlar: Python 3.11+, ffmpeg (`winget install --id Gyan.FFmpeg -e`).

Kalitlar (`python -m youtube_agent set-key NOM` buyrug'i so'raydi va `.env` ga yozadi):

| Kalit | Nima uchun | Majburiymi |
|---|---|---|
| `OPENAI_API_KEY` | matn, kadr tekshiruvi, ovoz, whisper | ha (`LLM_PROVIDER=openai` bo'lsa) |
| `PIXABAY_API_KEY` | stok-video va rasmlar | tavsiya etiladi |
| `PEXELS_API_KEY` | stok-video (vertikal) | ixtiyoriy |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | ruxsat so'rash | `run` uchun |
| `client_secret.json` + `auth` | YouTube yuklash va statistika | nashr uchun |

## 5. Buyruqlar

```
python -m youtube_agent tts-benchmark                 # ovozlarni solishtirish: data\tts_benchmark\*.wav
python -m youtube_agent produce "Sun'iy intellekt"    # bitta Shorts (YouTube'ga YUKLAMAYDI)
python -m youtube_agent jobs                          # ishlar va holatlari
python -m youtube_agent resume <job_id>               # to'xtagan ishni davom ettirish
python -m youtube_agent qa <job_id>                   # sifat nazoratini qayta o'tkazish
python -m youtube_agent publish <job_id> --privacy private    # qo'lda nashr (faqat approved)
python -m youtube_agent analytics                     # statistika va taqqoslash
python -m youtube_agent run                           # Telegram + jadval (Du, Se, Pa, Sha 19:00)
```
Har ishning fayllari `data\jobs\<job_id>\` papkasida: `research.json`, `claims.json`, `script.json`, `plan.json`,
`assets.json` (litsenziyalar), `assets_log.json` (qaysi kadrlar nega rad etilgani), `narration.json`, `captions.ass`,
`render\video.mp4`, `qa_report.json`, `job.log`.

## 6. Private'dan ommaviy nashrga o'tish

1. Sinov paytida `YOUTUBE_PRIVACY=private`. Video yuklanadi, lekin faqat siz ko'rasiz.
2. Bir necha videoni YouTube Studio'da ko'rib, sifati yoqsa: `YOUTUBE_PRIVACY=scheduled`. Shunda video jadval
   vaqtida (19:00) o'zi ochiladi, yoki `public` qilsangiz darhol ochiladi.
3. Google Cloud'dagi OAuth ilovasi "Testing" holatida bo'lsa, token 7 kunda eskiradi. Uni **In production**
   holatiga o'tkazing.
4. Statistika uchun `yt-analytics.readonly` ruxsati kerak. `auth` buyrug'i uni so'raydi. Agar eski
   `token.json` bo'lsa, uni o'chirib, `auth` ni qayta bajaring.

## 7. Testlar va cheklovlar

```
pip install -r requirements-dev.txt
python -m pytest tests -q
```
**Tekshirilgan (soxta AI va provayderlar, lekin haqiqiy ffmpeg bilan):** sxemalar va validatsiya; raqam va apostrof
normallashtirish; subtitrlarni moslash; fakt-tekshiruv (o'ylab topilgan va ochilmaydigan URL'lar tashlanadi);
ssenariy qoidalari; kadr tanlash (rad etish, takror, grafikaga o'tish); montaj (9:16, kadr cho'zilmaydi, crossfade
sinxronligi); **ataylab buzilgan videoni rad etish**; QA qarorlari va yo'naltirish; boshidan oxirigacha quvur
(tasdiq, davom ettirish, 2 ta tuzatishdan keyin `needs_review`); nashr faqat tasdiq bilan; analitika bazasi;
Telegram oqimi.

**Haqiqiy API bilan sinalmagan** (ishlab chiqish serveridan tashqi API'lar bloklangan, birinchi sinov sizning
kompyuteringizda bo'ladi): OpenAI (matn, TTS, whisper, Sora), Claude, Pixabay, Pexels, Wikimedia, YouTube yuklash
va Analytics.

**Ma'lum cheklovlar:**
- OpenAI TTS o'zbek tiliga maxsus qilinmagan, talaffuz sifatini oldindan bilib bo'lmaydi.
  `tts-benchmark` bilan eshitib ko'ring.
- `audio_quality` balli o'lchovlar va whisper o'xshashligiga asoslangan. U quloq bilan eshitishning o'rnini bosmaydi.
- Yangilik saytlaridagi rasmlarning foydalanish huquqi tekshirilmagan. QA ularni `license_warnings` da
  ko'rsatadi; o'chirish uchun `ALLOW_PUBLISHER_IMAGES=0`.
- YouTube API videoni "Short" deb belgilashga imkon bermaydi. Odatda vertikal va 60 soniyadan qisqa video
  avtomatik Short bo'ladi, buni yuklangandan keyin tekshiring.
- "Viewed vs swiped away" ko'rsatkichi Analytics API'da yo'q, bazada `NULL` saqlanadi.

## 8. Pulni tejash: sinov rejimi va chegara

- `TEST_MODE=1` (standart holatda yoqiq): hamma joyda arzon `gpt-5-mini` modeli ishlatiladi, avtomatik qayta tuzatishlar o'chiq.
  Sozlash tugagach `.env` faylida `TEST_MODE=0` qiling.
- `MAX_COST_PER_VIDEO=0.30`: bitta video uchun sarf chegarasi. Sarf shundan oshsa, jarayon keyingi pullik
  bosqichdan oldin to'xtaydi. Shu paytgacha qilingan ish saqlanadi.
- **Hech qachon `produce` buyrug'ini qayta ishga tushirmang** - u hammasini boshidan, yana pul to'lab qiladi.
  Buning o'rniga to'xtagan ishni davom ettiring: `python -m youtube_agent resume <job_id>`. Bu buyruq faqat qolgan
  bosqichlarni bajaradi va yana bitta chegara miqdorigacha ruxsat beradi.
- platform.openai.com → Settings → Limits bo'limida OpenAI'ning o'zida ham oylik chegara qo'ying.

## 9. Bitta video narxi (taxminiy)

Narxlar `pricing.py` va `.env` dagi `PRICE_*` bilan sozlanadi. Har ishning haqiqiy sarfi `job.json → costs`
maydoniga yoziladi.

| Bosqich | Taxmin |
|---|---|
| Tadqiqot + fakt-tekshiruv (GPT-5 + ~10 veb-qidiruv) | $0.20–0.35 |
| Ssenariy, storyboard, tahlil (GPT-5) | $0.10–0.25 |
| Kadr tekshiruvi (GPT-5 mini, ~15 ta) | ~$0.02 |
| Yakuniy AI QA (kadrlar bilan) | ~$0.03 |
| TTS (~45 s) + whisper | ~$0.02 |
| **Jami (Sora'siz)** | **~$0.40–0.70** |
| Sora yoqilsa (masalan 2 sahna × 4 s) | +~$0.80 |

Asos qilingan narxlar (1M token uchun): GPT-5 $1.25 kirish / $10 chiqish, GPT-5 mini $0.25 / $2. Boshqalar:
veb-qidiruv ~$0.01, TTS ~$0.015/daqiqa, whisper $0.006/daqiqa, Sora ~$0.10/soniya. Uchinchi tomon
manbalari bir-biriga zid, rasmiy narx sahifasini tekshiring.

## 10. Namuna

`docs/examples/plan.example.json` va `docs/examples/qa_report.example.json` soxta provayderlar bilan o'tkazilgan
test ishidan olingan. Ulardagi URL va faktlar test uchun o'ylab topilgan, maqsad faqat fayl tuzilmasini ko'rsatish.

## 11. Telegram buyruqlari

`/status`, `/video` (hozir yasash), `/jobs`, `/comments`, `/analytics`, `/cancel`. Video tayyor bo'lganda bot
QA hisoboti va narx bilan yuboradi:
- ✅ Joylash
- ❌ Yo'q
- 🔄 Boshqa video yarat

Kommentlarga javob ham faqat sizning ruxsatingiz bilan yoziladi.
