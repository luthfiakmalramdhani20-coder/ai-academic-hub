---
title: AI Academic Hub
emoji: 🎓
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# AI Academic Hub

Transkrip, catatan komprehensif, mind map, flashcard, dan kuis dari rekaman kuliah & kegiatan.

## Secrets (Settings → Variables and secrets)
- `GROQ_API_KEY`, `GEMINI_API_KEY`, `CREATOR_PASSWORD`
- Opsional agar data tidak hilang saat Space restart: `HF_TOKEN` (token *write*) dan
  `HF_DATASET_REPO` (mis. `username/hub-data`; dibuat otomatis sebagai dataset privat).

## Lokal
Jalankan `MULAI_APLIKASI.bat` (port 8000). Tanpa `HF_TOKEN`/`HF_DATASET_REPO`, sinkronisasi dilewati.
