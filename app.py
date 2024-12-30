from flask import Flask, render_template, request, flash, redirect, url_for, send_file, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import yt_dlp
from mutagen.mp3 import MP3
from datetime import datetime, timedelta
import replicate
import requests
from urllib.parse import urlparse
import json
import subprocess
import tempfile
import io
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', os.urandom(24))
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///music.db')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Session configuration
app.config['SESSION_TYPE'] = 'filesystem'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=31)  # Session lasts for 31 days
app.config['SESSION_COOKIE_SECURE'] = True  # Only send cookie over HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access to session cookie
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # CSRF protection
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=31)  # Remember me cookie duration

# Get port from environment variable
PORT = int(os.getenv('PORT', 5000))

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'stems'), exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# User Model
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    is_approved = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Song Model
class Song(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(255))
    duration = db.Column(db.Float)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    source_url = db.Column(db.String(1024))  # Store the source URL
    
    # Stem information
    has_stems = db.Column(db.Boolean, default=False)
    vocals_stem = db.Column(db.String(255))
    drums_stem = db.Column(db.String(255))
    bass_stem = db.Column(db.String(255))
    other_stem = db.Column(db.String(255))
    piano_stem = db.Column(db.String(255))  # New piano stem
    guitar_stem = db.Column(db.String(255))  # New guitar stem
    processing_stems = db.Column(db.Boolean, default=False)
    stem_error = db.Column(db.String(255))

    def get_stem_status(self):
        if self.stem_error:
            return 'error', self.stem_error
        elif self.processing_stems:
            return 'processing', 'Stems are being processed'
        elif self.has_stems:
            return 'complete', 'Stems are ready'
        else:
            return 'not_started', 'Stem separation not started'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember', False)
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            if not user.is_approved:
                flash('Your account is pending approval.', 'warning')
                return redirect(url_for('login'))
            
            # Make session permanent and login user
            session.permanent = True
            login_user(user, remember=remember)
            
            # Get the next page from args or default to dashboard
            next_page = request.args.get('next')
            if not next_page or urlparse(next_page).netloc != '':
                next_page = url_for('dashboard')
                
            return redirect(next_page)
            
        flash('Invalid email or password', 'error')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('register'))
        
        # Check if this is the first user
        is_first_user = User.query.count() == 0
        
        user = User(
            email=email,
            is_approved=is_first_user,  # Auto-approve first user
            is_admin=is_first_user  # Make first user admin
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        if is_first_user:
            flash('Registration successful! You are the first user and have been automatically approved as admin.', 'success')
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Registration successful. Please wait for admin approval.', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    songs = Song.query.filter_by(user_id=current_user.id).all()
    return render_template('dashboard.html', songs=songs)

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    pending_users = User.query.filter_by(is_approved=False).all()
    return render_template('admin.html', pending_users=pending_users)

@app.route('/approve/<int:user_id>')
@login_required
def approve_user(user_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(user_id)
    user.is_approved = True
    db.session.commit()
    flash(f'User {user.email} has been approved', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/download', methods=['GET', 'POST'])
@login_required
def download_song():
    if request.method != 'POST':
        return render_template('download.html')
        
    url = request.form.get('url')
    if not url:
        flash('Please enter a URL', 'error')
        return redirect(url_for('download_song'))

    # Check if this URL has already been downloaded by the user
    existing_song = Song.query.filter_by(user_id=current_user.id, source_url=url).first()
    if existing_song:
        flash('You have already downloaded this song!', 'info')
        return redirect(url_for('song_info', song_id=existing_song.id))

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    base_filename = f"download_{timestamp}"
    output_template = os.path.join(app.config['UPLOAD_FOLDER'], base_filename)

    # Configure yt-dlp options
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': output_template + '.%(ext)s',
        'restrictfilenames': True,
        'extract_flat': True,
        'force_generic_extractor': False,
    }

    try:
        # First try to get info
        info = None
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except:
            pass

        # Get title and artist info if available
        title = base_filename
        if info and isinstance(info, dict):
            # Try to get the best title possible
            title = info.get('track') or info.get('title') or info.get('alt_title')
            artist = info.get('artist') or info.get('creator') or info.get('uploader')
            
            if title and artist:
                title = f"{artist} - {title}"
            elif title:
                title = title
                
            # Clean the title
            title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
            title = title[:180] if title else base_filename

        # Download the file
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.download([url])
            if result != 0:
                raise Exception("Download failed")

            # Find the downloaded file
            expected_path = output_template + '.mp3'
            if not os.path.exists(expected_path):
                # Fallback: find most recent mp3
                mp3_files = [f for f in os.listdir(app.config['UPLOAD_FOLDER']) if f.endswith('.mp3')]
                if not mp3_files:
                    raise FileNotFoundError("No MP3 file found after download")
                latest_file = max(mp3_files, key=lambda x: os.path.getctime(
                    os.path.join(app.config['UPLOAD_FOLDER'], x)
                ))
                expected_path = os.path.join(app.config['UPLOAD_FOLDER'], latest_file)

            # Create song entry
            try:
                audio = MP3(expected_path)
                song = Song(
                    filename=os.path.basename(expected_path),
                    title=title,
                    duration=audio.info.length,
                    user_id=current_user.id,
                    source_url=url  # Save the source URL
                )
                db.session.add(song)
                db.session.commit()
                
                flash('Song downloaded successfully!', 'success')
                return redirect(url_for('song_info', song_id=song.id))
                
            except Exception as e:
                if os.path.exists(expected_path):
                    os.remove(expected_path)
                raise Exception(f"Failed to save song: {str(e)}")

    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e).lower()
        if 'private' in error_msg:
            flash('This content is private. Please try downloading public content only.', 'error')
        elif 'copyright' in error_msg:
            flash('This content is not available due to copyright restrictions.', 'error')
        else:
            flash('Could not download the audio. Please check the URL and try again.', 'error')
        app.logger.error(f"Download error for URL {url}: {error_msg}")
        
    except Exception as e:
        app.logger.error(f"Error processing download: {str(e)}")
        flash('An error occurred while processing your download.', 'error')
        
    return redirect(url_for('download_song'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_song():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
        if file and file.filename.endswith('.mp3'):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            # Get audio information
            audio = MP3(filepath)
            
            # Save song information
            song = Song(
                filename=filename,
                title=os.path.splitext(filename)[0],
                duration=audio.info.length,
                user_id=current_user.id
            )
            db.session.add(song)
            db.session.commit()
            
            return redirect(url_for('song_info', song_id=song.id))
        else:
            flash('Invalid file type. Please upload MP3 files only.', 'error')
    return render_template('upload.html')

@app.route('/song/<int:song_id>')
@login_required
def song_info(song_id):
    song = Song.query.get_or_404(song_id)
    if song.user_id != current_user.id and not current_user.is_admin:
        return redirect(url_for('dashboard'))
    return render_template('song_info.html', song=song)

@app.route('/download/<int:song_id>')
@login_required
def download_file(song_id):
    song = Song.query.get_or_404(song_id)
    if song.user_id != current_user.id and not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    # Generate a clean filename
    clean_title = song.title.replace('_', ' ').strip()
    download_name = f"{clean_title}.mp3"
    
    return send_file(
        os.path.join(app.config['UPLOAD_FOLDER'], song.filename),
        as_attachment=True,
        download_name=download_name
    )

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/process_stems/<int:song_id>', methods=['POST'])
@login_required
def process_stems(song_id):
    song = Song.query.get_or_404(song_id)
    if song.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Check if stems already exist
    if song.has_stems and all([
        song.vocals_stem, song.drums_stem, song.bass_stem, song.other_stem,
        song.piano_stem, song.guitar_stem
    ]):
        return jsonify({
            'status': 'success',
            'message': 'All stems already available',
            'cached': True
        })
    
    try:
        # Mark as processing
        song.processing_stems = True
        song.stem_error = "Preparing audio file for processing..."
        db.session.commit()
        
        # Get the full path of the audio file
        audio_path = os.path.join(app.config['UPLOAD_FOLDER'], song.filename)
        
        # Create output directory for stems
        stem_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'stems', str(song.id))
        os.makedirs(stem_dir, exist_ok=True)
        
        # Update status
        song.stem_error = "Initializing AI model for stem separation..."
        db.session.commit()
        
        # Open and read the audio file
        with open(audio_path, 'rb') as audio_file:
            # Run Replicate API with optimized parameters
            song.stem_error = "Running AI model for stem separation (this may take several minutes)..."
            db.session.commit()
            
            output = replicate.run(
                "ryan5453/demucs:7a9db77ed93f8f4f7e233a94d8519a867fbaa9c6d16ea5b53c1394f1557f9c61",
                input={
                    "jobs": 0,
                    "audio": audio_file,
                    "stem": "none",  # Always process all stems
                    "model": "htdemucs_6s",  # Using 6-stem model
                    "split": True,
                    "shifts": 1,
                    "overlap": 0.25,
                    "clip_mode": "rescale",
                    "mp3_preset": 2,
                    "wav_format": "int24",
                    "mp3_bitrate": 320,
                    "output_format": "mp3",
                }
            )
        
        # Process and save all stems
        stem_types = ['vocals', 'drums', 'bass', 'other', 'piano', 'guitar']
        total_stems = len(stem_types)
        for i, stem_type in enumerate(stem_types, 1):
            if stem_type in output and output[stem_type]:
                song.stem_error = f"Downloading {stem_type.capitalize()} stem ({i}/{total_stems})..."
                db.session.commit()
                
                # Download and save stem
                response = requests.get(output[stem_type], timeout=30)
                response.raise_for_status()
                
                stem_filename = f"{os.path.splitext(song.filename)[0]}_{stem_type}.mp3"
                stem_path = os.path.join(stem_dir, stem_filename)
                
                with open(stem_path, 'wb') as f:
                    f.write(response.content)
                
                setattr(song, f"{stem_type}_stem", stem_filename)
                
                # For vocals, also save instrumental
                if stem_type == 'vocals' and 'no_vocals' in output:
                    song.stem_error = "Downloading instrumental track..."
                    db.session.commit()
                    
                    response = requests.get(output['no_vocals'], timeout=30)
                    response.raise_for_status()
                    
                    inst_filename = f"{os.path.splitext(song.filename)[0]}_instrumental.mp3"
                    inst_path = os.path.join(stem_dir, inst_filename)
                    
                    with open(inst_path, 'wb') as f:
                        f.write(response.content)
        
        # Mark processing as complete
        song.has_stems = True
        song.processing_stems = False
        song.stem_error = None
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'message': 'Stems processed successfully'
        })
        
    except Exception as e:
        error_message = str(e)
        if "exceeded the rate limit" in error_message.lower():
            error_message = "Rate limit exceeded. Please try again in a few minutes."
        elif "invalid api key" in error_message.lower():
            error_message = "API configuration error. Please contact support."
        
        song.processing_stems = False
        song.stem_error = error_message
        db.session.commit()
        app.logger.error(f"Stem processing error for song {song_id}: {error_message}")
        return jsonify({
            'status': 'error',
            'message': error_message
        }), 500

@app.route('/stem_status/<int:song_id>')
@login_required
def stem_status(song_id):
    song = Song.query.get_or_404(song_id)
    if song.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Check if processing has been going on for too long (10 minutes)
    if song.processing_stems:
        processing_timeout = timedelta(minutes=10)
        current_time = datetime.utcnow()
        
        # If the song was last updated more than 10 minutes ago and is still processing
        if current_time - song.last_updated > processing_timeout:
            song.processing_stems = False
            song.stem_error = "Processing timed out. Please try again."
            db.session.commit()
            
            return jsonify({
                'status': 'error',
                'message': 'Processing timed out. Please try again.',
                'has_stems': song.has_stems,
                'stems': None
            })
    
    status, message = song.get_stem_status()
    return jsonify({
        'status': status,
        'message': message,
        'has_stems': song.has_stems,
        'stems': {
            'vocals': song.vocals_stem,
            'drums': song.drums_stem,
            'bass': song.bass_stem,
            'other': song.other_stem,
            'piano': song.piano_stem,
            'guitar': song.guitar_stem
        } if song.has_stems else None
    })

@app.route('/download_stem/<int:song_id>/<stem_type>')
@login_required
def download_stem(song_id, stem_type):
    song = Song.query.get_or_404(song_id)
    if song.user_id != current_user.id and not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    if not song.has_stems:
        flash('Stems are not available for this song', 'error')
        return redirect(url_for('song_info', song_id=song.id))
    
    stem_filename = getattr(song, f"{stem_type}_stem")
    if not stem_filename:
        flash(f'{stem_type} stem is not available', 'error')
        return redirect(url_for('song_info', song_id=song.id))
    
    # Generate a clean filename for the stem
    clean_title = song.title.replace('_', ' ').strip()
    if stem_type == 'other' and stem_filename.endswith('instrumental.mp3'):
        download_name = f"{clean_title} - Instrumental.mp3"
    else:
        stem_type_clean = stem_type.capitalize()
        download_name = f"{clean_title} - {stem_type_clean}.mp3"
    
    stem_path = os.path.join(app.config['UPLOAD_FOLDER'], 'stems', str(song.id), stem_filename)
    return send_file(
        stem_path,
        as_attachment=True,
        download_name=download_name
    )

@app.route('/download_merged_stems/<int:song_id>', methods=['POST'])
@login_required
def download_merged_stems(song_id):
    song = Song.query.get_or_404(song_id)
    if song.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    if not song.has_stems:
        flash('Stems are not available for this song', 'error')
        return redirect(url_for('song_info', song_id=song.id))
    
    # Get selected stems from request
    selected_stems = request.form.getlist('stems[]')
    if not selected_stems:
        flash('Please select at least one stem', 'error')
        return redirect(url_for('song_info', song_id=song.id))
    
    try:
        # Create temporary directory for processing
        with tempfile.TemporaryDirectory() as temp_dir:
            stem_files = []
            
            # Collect paths of selected stems
            for stem_type in selected_stems:
                stem_filename = getattr(song, f"{stem_type}_stem")
                if stem_filename:
                    stem_path = os.path.join(app.config['UPLOAD_FOLDER'], 'stems', str(song.id), stem_filename)
                    if os.path.exists(stem_path):
                        stem_files.append(stem_path)
            
            if not stem_files:
                flash('No valid stems found', 'error')
                return redirect(url_for('song_info', song_id=song.id))
            
            # Create unique output filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_path = os.path.join(temp_dir, f'merged_{timestamp}.mp3')
            
            # Build ffmpeg command to merge stems
            input_files = []
            filter_parts = []
            for i, stem_file in enumerate(stem_files):
                input_files.extend(['-i', stem_file])
                filter_parts.append(f'[{i}:a]')
            
            filter_complex = f"{''.join(filter_parts)}amix=inputs={len(stem_files)}:duration=longest[aout]"
            
            # Construct full command
            command = [
                'ffmpeg', '-y',
                *input_files,
                '-filter_complex', filter_complex,
                '-map', '[aout]',
                '-b:a', '320k',
                output_path
            ]
            
            # Run ffmpeg command
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode != 0:
                raise Exception(f"FFmpeg error: {result.stderr}")
            
            # Create output filename for download
            stem_types = '_'.join(selected_stems)
            clean_title = song.title.replace('_', ' ').strip()
            download_name = f"{clean_title} - {stem_types}.mp3"
            
            # Read the file into memory before sending
            with open(output_path, 'rb') as f:
                file_data = f.read()
            
            # Create response with file data
            response = send_file(
                io.BytesIO(file_data),
                mimetype='audio/mpeg',
                as_attachment=True,
                download_name=download_name
            )
            
            # Add cache control headers
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            
            return response
            
    except subprocess.CalledProcessError as e:
        app.logger.error(f"FFmpeg error: {e.stderr}")
        flash('Error merging stems', 'error')
    except Exception as e:
        app.logger.error(f"Error processing stems: {str(e)}")
        flash('Error processing stems', 'error')
    
    return redirect(url_for('song_info', song_id=song.id))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Create database tables
    app.run(host='0.0.0.0', port=PORT, debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true') 