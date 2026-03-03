from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
from werkzeug.utils import secure_filename
from waitress import serve
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import os
import json
import random
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# --- IRONCLAD SECURITY SETTINGS ---
app.secret_key = os.environ.get("SECRET_KEY", "fallback_secret_key")
MASTER_PASSWORD = os.environ.get("MASTER_PASSWORD", "admin") 
app.permanent_session_lifetime = timedelta(minutes=60) 

app.config['SESSION_COOKIE_SECURE'] = True      
app.config['SESSION_COOKIE_HTTPONLY'] = True    
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'   

# --- ANTI-HACKER RATE LIMITING ---
limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri="memory://"
)

# --- THE VAULT (SECURE FILE HANDLING) ---
UPLOAD_FOLDER = 'private_media'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 700 * 1024 * 1024 # Block files larger than 700MB
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'mov'}
DATA_FILE = 'posts.json'
MESSAGES_FILE = 'messages.json'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- DATABASE HELPERS ---
def read_json(filepath):
    if not os.path.exists(filepath): return []
    try:
        with open(filepath, 'r') as f: return json.load(f)
    except: return []

def write_json(filepath, data):
    with open(filepath, 'w') as f: json.dump(data, f, indent=4)

# --- ROUTES: AUTHENTICATION ---
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute") 
def login():
    error = None
    if request.method == 'POST':
        submitted_pw = request.form.get('password')
        if submitted_pw == MASTER_PASSWORD:
            session.permanent = True 
            session['logged_in'] = True
            return redirect(url_for('home'))
        else:
            error = 'Invalid Credentials. Access Denied.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def home():
    return render_template('index.html')

# --- SECURE MEDIA BOUNCER ---
@app.route('/api/media/<filename>')
@login_required
def secure_media(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- ROUTES: MEDIA FEED ---
@app.route('/api/posts', methods=['GET'])
@login_required
def get_posts():
    posts = read_json(DATA_FILE)
    for p in posts:
        if 'id' not in p: p['id'] = p.get('image_url', '').split('/')[-1].split('.')[0]
        if 'price' not in p: p['price'] = random.randint(10, 50)
        if 'likes' not in p: p['likes'] = 0
        if 'type' not in p: p['type'] = 'video' if p.get('image_url', '').lower().endswith(('.mp4', '.webm', '.mov')) else 'image'
    return jsonify(posts)

@app.route('/api/upload', methods=['POST'])
@login_required
def upload_post():
    if 'media' not in request.files: return jsonify({'error': 'No file'}), 400
    file = request.files['media']
    caption = request.form.get('caption', '')
    raw_price = request.form.get('price', '')
    try: price = int(raw_price) if raw_price else random.randint(10, 50)
    except ValueError: price = random.randint(10, 50)
    
    if file and allowed_file(file.filename):
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        safe_filename = secure_filename(file.filename)
        filename = f"{timestamp}_{safe_filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        file_ext = filename.lower().split('.')[-1]
        media_type = 'video' if file_ext in ['mp4', 'webm', 'mov'] else 'image'

        new_post = {
            'id': timestamp, 
            'image_url': f"/api/media/{filename}", 
            'type': media_type, 'caption': caption, 'price': price,
            'likes': 0, 'date': datetime.now().strftime("%B %d, %Y")
        }
        posts = read_json(DATA_FILE)
        posts.insert(0, new_post) 
        write_json(DATA_FILE, posts)
        return jsonify(new_post)
    return jsonify({'error': 'Invalid file'}), 400

@app.route('/api/like', methods=['POST'])
@login_required
def like_post():
    data = request.get_json()
    posts = read_json(DATA_FILE)
    for p in posts:
        if p.get('id') == data.get('id'):
            p['likes'] = p.get('likes', 0) + 1
            write_json(DATA_FILE, posts)
            return jsonify({'success': True, 'likes': p['likes']})
    return jsonify({'success': False}), 404

@app.route('/api/delete', methods=['POST'])
@login_required
def delete_post():
    data = request.get_json()
    posts = read_json(DATA_FILE)
    post_to_delete = next((p for p in posts if p.get('id') == data.get('id')), None)
    if post_to_delete:
        updated_posts = [p for p in posts if p.get('id') != data.get('id')]
        write_json(DATA_FILE, updated_posts)
        filename = post_to_delete['image_url'].split('/')[-1]
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(filepath): os.remove(filepath)
        return jsonify({'success': True})
    return jsonify({'success': False}), 400

# --- ROUTES: CHAT SYSTEM ---
@app.route('/api/messages', methods=['GET'])
@login_required
def get_messages():
    return jsonify(read_json(MESSAGES_FILE))

@app.route('/api/messages', methods=['POST'])
@login_required
def post_message():
    data = request.get_json()
    sender = data.get('sender', 'Anonymous')
    text = data.get('text', '')
    
    if not text: return jsonify({'error': 'Empty message'}), 400

    new_msg = {
        'id': str(datetime.now().timestamp()),
        'sender': sender,
        'text': text,
        'time': datetime.now().strftime("%I:%M %p")
    }
    
    messages = read_json(MESSAGES_FILE)
    messages.append(new_msg)
    write_json(MESSAGES_FILE, messages)
    
    return jsonify(new_msg)

if __name__ == '__main__':
    print("Secure Waitress server starting on port 5000...")
    # Locked strictly to Localhost. Invisible to local Wi-Fi.
    serve(app, host='127.0.0.1', port=5000)