# MusicMagic 🎵

A web application that lets you download music and split it into separate instrument tracks using AI.

## Features

- Download music from various sources
- Split songs into stems (vocals, drums, bass, guitar, piano, other)
- Create custom mixes by combining stems
- User authentication with admin approval system

## Quick Start

1. Clone and install dependencies:
```bash
git clone https://github.com/yourusername/musicmagic.git
cd musicmagic
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Unix/MacOS
pip install uv
uv pip install -r requirements.txt
```

2. Create a `.env` file:
```
REPLICATE_API_TOKEN=your_token_here
```
Get your token from [Replicate](https://replicate.com)

3. Run the app:
```bash
flask run
```

4. Visit `http://localhost:5000` and register - the first user to register becomes admin!

## Important Notes

- The first user to register automatically becomes admin and can approve other users
- You need a Replicate API token for stem separation
- Maximum file size: 16MB
- Supported formats: MP3
- Stem separation takes several minutes per song

## Tech Stack

- Backend: Flask + SQLite
- Frontend: Bootstrap 5
- AI: Demucs (via Replicate)
- Audio: FFmpeg 