# 🤖 YouTube kanal agenti (Claude yoki OpenAI asosida)

Bu agent **YouTube Shorts** kanalini avtomatik yuritadi: har safar eng so'nggi, hayratlanarli yangilikni topib, 35–50 soniyalik vertikal video qiladi.

- **Mavzular:** Koinot, Sun'iy intellekt, Tibbiyot, Ilm-fan (navbat bilan almashadi).
- **Faqat rasmiy manbalar:** AI yangiliklari Anthropic, OpenAI, Google DeepMind, xAI, Mistral AI, NVIDIA
  saytlaridan; koinot yangiliklari NASA, ESA, SpaceX, Blue Origin, O'zbekkosmos saytlaridan; tibbiyot WHO, NIH,
  NEJM, Lancet va boshqalardan olinadi. Rasmlar ham shu mavzuga oid: yangilik sahifasining asosiy rasmi,
  NASA rasm arxivi, Wikimedia Commons. Mavzuga aloqasiz stok-kadrlar ishlatilmaydi.
- **Jadval:** Dushanba, Seshanba, Payshanba, Shanba — soat **19:00** (Toshkent vaqti).
- **O'zi tayyorlaydi:** sun'iy intellekt (Claude yoki OpenAI) oxirgi haftalardagi eng qiziq yangilikni topadi → kuchli "hook" bilan qisqa ssenariy yozadi → har sahnaga katta raqam/kalit so'z va mavzuga oid rasm qo'yadi → diktor ovozi, so'zma-so'z yonadigan subtitr, progress chizig'i va fon musiqasi bilan 1080×1920 Shorts yasaydi.
- **Telegram orqali ruxsat so'raydi:** joylashdan ~3 soat oldin videoni sizga yuboradi:
  `✅ Ha, joylash` / `❌ Yo'q` / `🔄 Boshqa video yarat`.
  Tasdiqlasangiz, video YouTube'ga yuklanadi va aynan 19:00 da avtomatik ochiladi.
- **Kommentlar:** har 30 daqiqada yangi kommentlarni tekshiradi, javob loyihasini yozib,
  Telegram'da so'raydi: `✅ Javob berish` / `✏️ O'zim yozaman` / `❌ O'tkazib yuborish`.
  Spam va haqoratlarni o'zi o'tkazib yuboradi.

Sizning ruxsatingizsiz **hech narsa** YouTube'ga chiqmaydi.

```
 Jadval (16:00) ──► AI: yangilik + ssenariy ──► Kadrlar + ovoz + subtitr ──► short.mp4
                                                                              │
             Telegram: "Video qo'yilsinmi?"  ◄────────────────────────────────┘
                 │ ✅
                 ▼
 YouTube'ga yuklash (19:00 da ochiladi) ──► Telegram: havola

 Har 30 daq: yangi kommentlar ──► AI javob loyihasi ──► Telegram: "Javob yozilsinmi?" ──► YouTube
```

## ⚠️ Muhim: kanalni bir marta o'zingiz ochasiz

YouTube API kanal **yaratishga** ruxsat bermaydi — bu faqat qo'lda qilinadi (1 daqiqalik ish):
1. [youtube.com](https://youtube.com) ga Google akkaunt bilan kiring → avatar → **Kanal yaratish**.
2. [youtube.com/verify](https://youtube.com/verify) da telefon raqam bilan tasdiqlang
   (15 daqiqadan uzun video va o'z muqovangizni qo'yish uchun kerak).

Qolgan hamma ishni agent o'zi bajaradi.

## O'rnatish

### 1. Kerakli dasturlar
- Python 3.11+
- `ffmpeg` (Ubuntu: `sudo apt install ffmpeg fonts-dejavu-core`, Windows: ffmpeg.org dan yuklab, PATH ga qo'shing)

```bash
git clone https://github.com/bekzodjovliyev1984/real-agent.git
cd real-agent
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Sun'iy intellekt kaliti (ikkisidan biri)
Matnni (tadqiqot, ssenariy, komment javoblari) yozadigan provayderni `.env` dagi `LLM_PROVIDER` bilan tanlaysiz:

- **OpenAI:** [platform.openai.com/api-keys](https://platform.openai.com/api-keys) → yangi kalit →
  `LLM_PROVIDER=openai`, `OPENAI_API_KEY=sk-...` (model: `OPENAI_MODEL`, standart `gpt-5`).
- **Claude:** [console.anthropic.com](https://console.anthropic.com) → **API Keys** → yangi kalit →
  `LLM_PROVIDER=claude`, `ANTHROPIC_API_KEY=sk-ant-...` (model: `CLAUDE_MODEL`, standart `claude-opus-5-5`).

Keyinroq istalgan vaqtda bitta qatorni o'zgartirib, boshqasiga o'tishingiz mumkin. Video yasash
(slaydlar, ovoz, montaj) ikkala holatda ham bir xil.

### 2.1. Rasmlar
Kalit shart emas: rasmlar yangilik sahifasining o'zidan, NASA arxividan va Wikimedia Commons'dan avtomatik
olinadi, mualliflar video tavsifiga yoziladi. Ixtiyoriy: `AI_IMAGES=1` - rasm topilmasa OpenAI chizadi (pullik);
`STOCK_FALLBACK=1` + `PIXABAY_API_KEY` - oxirgi chora sifatida Pixabay.

**Fon musiqasi (ixtiyoriy):** loyiha ichida `music` papkasini yarating va unga mualliflik
huquqisiz `.mp3` fayllarni qo'ying (masalan, YouTube Studio → Audio Library'dan). Agent har
videoga tasodifiy bittasini past ovozda qo'shadi.

### 3. Telegram bot
1. Telegram'da [@BotFather](https://t.me/BotFather) → `/newbot` → tokenni `.env` dagi `TELEGRAM_BOT_TOKEN` ga yozing.
2. Agentni ishga tushirib (`python -m youtube_agent run`), botingizga `/start` yozing —
   bot sizning **chat ID** ingizni aytadi. Uni `TELEGRAM_CHAT_ID` ga yozib, agentni qayta ishga tushiring.
   Bot faqat shu chat ID'dagi odamning (ya'ni sizning) buyruqlarini bajaradi.

### 4. YouTube ruxsati (bir marta)
1. [console.cloud.google.com](https://console.cloud.google.com) → yangi loyiha.
2. **APIs & Services → Library** → **YouTube Data API v3** → *Enable*.
3. **OAuth consent screen** → *External* → o'z email'ingizni **Test users** ga qo'shing.
   (Token 7 kunda eskirmasligi uchun keyinroq ilovani **In production** holatiga o'tkazing.)
4. **Credentials → Create credentials → OAuth client ID → Desktop app** → JSON'ni yuklab,
   loyiha papkasiga `client_secret.json` nomi bilan saqlang.
5. Brauzer bor kompyuterda ishga tushiring:
   ```bash
   python -m youtube_agent auth
   ```
   Kanal ochilgan Google akkauntni tanlang. `token.json` paydo bo'ladi
   (agent serverda ishlasa, shu faylni serverga ko'chiring).

### 5. Sinab ko'rish
```bash
python -m youtube_agent test-video "Sun'iy intellekt"   # bitta videoni yasab ko'radi (YouTube'ga yuklamaydi)
python -m youtube_agent run                              # agentni ishga tushiradi
```

## Telegram buyruqlari

| Buyruq | Vazifasi |
|---|---|
| `/status` | Keyingi joylash vaqtlari va kutilayotgan so'rovlar |
| `/video` | Hoziroq yangi video tayyorlash (tasdiqlansa darhol chiqadi) |
| `/comments` | Kommentlarni hozir tekshirish |
| `/cancel` | Komment javobini tahrirlashni bekor qilish |

## 24/7 ishlatish

Agent jadval bo'yicha ishlashi uchun doim yoqiq kompyuter yoki server (VPS) kerak.

**Docker:**
```bash
docker build -t youtube-agent .
docker run -d --restart=always --env-file .env \
  -v $PWD/data:/app/data -v $PWD/token.json:/app/token.json \
  --name youtube-agent youtube-agent
```

**systemd (Linux):** `youtube-agent.service` faylini ko'ring.

## Sozlash (`.env`)

| O'zgaruvchi | Standart | Izoh |
|---|---|---|
| `LLM_PROVIDER` | `claude` | `claude` yoki `openai` |
| `PUBLISH_DAYS` | `mon,tue,thu,sat` | Joylash kunlari |
| `PUBLISH_TIME` | `19:00` | Joylash vaqti |
| `TIMEZONE` | `Asia/Tashkent` | Vaqt mintaqasi |
| `PREPARE_HOURS_BEFORE` | `3` | Video necha soat oldin tayyorlanib, sizga yuboriladi |
| `TOPICS` | `Koinot,Sun'iy intellekt,Tibbiyot,Ilm-fan` | Mavzular navbati |
| `VIDEO_LANGUAGE` | `o'zbek` | Ssenariy tili |
| `TTS_VOICE` | `uz-UZ-SardorNeural` | Diktor ovozi (`uz-UZ-MadinaNeural` — ayol ovozi; ruscha: `ru-RU-DmitryNeural`) |
| `COMMENT_CHECK_MINUTES` | `30` | Kommentlarni tekshirish oralig'i |

## Loyiha tuzilmasi

```
youtube_agent/
  agent.py     — jadval, Telegram tugmalari, asosiy sikl
  content.py   — Claude / OpenAI: veb-qidiruv, ssenariy, komment javoblari
  video.py     — kadrlar (Pillow) + ovoz (edge-tts) + subtitr va montaj (ffmpeg)
  images.py    — mavzuga oid rasmlarni topish (manba sahifa, NASA, Wikimedia)
  youtube.py   — YouTube Data API: yuklash, kommentlar
  telegram.py  — Telegram Bot API
  state.py     — holatni data/state.json da saqlash
  config.py    — .env sozlamalari
```

## Eslatmalar

- Videolar YouTube'da **"AI yordamida yaratilgan"** (`containsSyntheticMedia`) deb belgilanadi — bu YouTube qoidalari talabi.
- Tibbiy videolarga avtomatik ravishda "shifokor maslahatining o'rnini bosmaydi" ogohlantirishi qo'shiladi.
- YouTube API'ning kunlik limiti 10 000 birlik; bitta video yuklash ~1600 birlik. Haftasiga 4 ta video bemalol sig'adi.
- Claude va OpenAI API pullik: bitta video taxminan bir necha o'n sent turadi (veb-qidiruv + ssenariy).
