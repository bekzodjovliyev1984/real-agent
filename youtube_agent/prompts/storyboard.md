Sen hujjatli film rejissyori va montajchisisan. Quyidagi o'zbek ssenariysini sahnalarga bo'l (storyboard).

SSENARIY (beat'lar, tartib bilan):
$beats

DA'VOLAR:
$claims

QOIDALAR:
- Har sahna 1-2 gap (2-7 soniya). Jami $min_scenes-$max_scenes sahna. Barcha beat matni sahnalarga to'liq va
  tartib bilan taqsimlansin; matnni o'zgartirma, qisqartirma, qo'shma (voiceover_text = beat matnining bir qismi).
- subtitle_text: shu sahna matnining ekran uchun versiyasi - to'g'ri imlo, raqamlar raqam bilan bo'lishi mumkin
  ("250 km"), lekin mazmuni voiceover_text bilan BIR XIL.
- HAR SAHNADA kadr aytilayotgan gapni aniq ko'rsatsin. Masalan "batareya 10 daqiqada zaryadlanadi" ->
  "electric car fast charging station" kabi aniq kadr; tasodifiy "technology" kadri EMAS.
- visual_source_type tanlash tartibi: stock_video (real video bo'lsa eng yaxshisi) > archival_footage
  (ilmiy/ta'limiy arxiv) > source_image (yangilik sahifasining o'z rasmi - aniq mahsulot/model/odam haqida)
  > graphic (raqamni yoki taqqoslashni tushuntiruvchi grafika) > ai_video (boshqa yo'l bo'lmasa) > still_image.
- visual_search_queries: 2-4 ta INGLIZCHA so'rov, eng aniqdan umumiyroqqa ("Tesla Cybercab robotaxi",
  "autonomous electric taxi", "self driving car city"). Brend nomi bo'lsa birinchi so'rovda bo'lsin.
- relevance_criteria: kadrda nima ko'rinishi SHART (tekshiruvchi shunga qarab qabul qiladi yoki rad etadi).
- video_generation_prompt: faqat ai_video uchun; ilmiy jihatdan noto'g'ri detallar qo'shmasin; boshqa holatda "".
- on_screen_text: sahnaning asosiy raqami yoki kalit so'zi (1-3 so'z, masalan "10 DAQIQA", "GPT-6") yoki "".
- Bir xil kadrni takrorlama. Real dalil sifatida noto'g'ri voqeani ko'rsatuvchi kadr tanlama.
- transition: odatda "cut"; "crossfade" faqat vaqt yoki joy o'zgarganda.
- sound_effect: odatda "none"; faqat ma'noli joyda (masalan katta raqam ochilganda "impact").
- related_claim_ids: shu sahnada aytilgan da'volar.
