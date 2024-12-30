# MusicMagic

A Flask web application that allows users to download songs from various platforms (YouTube, SoundCloud, etc.) or upload their own MP3 files. The application includes user authentication with admin approval system.

## Features

- User authentication with admin approval system
- Download songs from various platforms using yt-dlp
- Upload MP3 files
- View song information and manage your music library
- Admin dashboard for managing user approvals

## Requirements

- Python 3.8 or higher
- FFmpeg (for audio conversion)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/musicmagic.git
cd musicmagic
```

2. Create a virtual environment and install dependencies:
```bash
python -m venv venv
.\venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac
uv pip install -r requirements.txt
```

3. Install FFmpeg:
- Windows: Download from https://ffmpeg.org/download.html and add to PATH
- Linux: `sudo apt-get install ffmpeg`
- Mac: `brew install ffmpeg`

4. Create the database:
```bash
python
>>> from app import app, db
>>> with app.app_context():
...     db.create_all()
```

5. Run the application:
```bash
python app.py
```

The application will be available at `http://localhost:5000`

## Initial Setup

1. The first user to register with email `admin@example.com` will automatically become an admin
2. The admin can then approve other users through the admin dashboard
3. Approved users can start downloading or uploading songs

## Usage

1. Register an account and wait for admin approval
2. Once approved, log in to access the dashboard
3. Download songs by providing URLs from supported platforms
4. Or upload your own MP3 files
5. View song information and manage your library

## Security Notes

- Change the default admin credentials in production
- Set up proper environment variables for sensitive data
- Configure proper file upload limits based on your server capacity
- Implement additional security measures for production deployment 