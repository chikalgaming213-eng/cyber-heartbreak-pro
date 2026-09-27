# Cyber Heartbreak Pro

Folder proyek Python modular untuk hand tracking bertema cyber-security, bucin, dan patah hati.

## Instalasi

```bash
pip install -r requirements.txt
```

## Menjalankan

```bash
python run.py
python run.py --record
```

`main_console.py` adalah console utama yang sudah memiliki gesture, filter, HUD, recording, dan screenshot.
`advanced_logic.py` berisi bank logika tambahan untuk threshold adaptif, telemetry, event bus,
filter pipeline, keamanan state, dan simulasi efek yang dapat dikembangkan di Acode.

## Struktur

- `run.py` - launcher sederhana
- `main_console.py` - engine hand tracking utama
- `advanced_logic.py` - library logika lanjutan
- `requirements.txt` - dependensi
