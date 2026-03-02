from flask import Flask, render_template, request, jsonify, session, redirect, url_for
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

# --- STRICT SECURITY SETTINGS ---
app.secret_key = os.environ.get("SECRET_KEY", "fallback_secret_key")
MASTER_PASSWORD = os.environ.get("MASTER_PASSWORD", "admin") 
app.permanent_session_lifetime = timedelta(minutes=5) 

# --- ANTI-HACKER RATE LIMITING ---
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# --- SECURE FILE HANDLING ---
UPLOAD_FOLDER = 'static/images'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'webm', 'mov'}
DATA_FILE = 'posts.json'
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

def read_posts():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_posts(posts):
    with open(DATA_FILE, 'w') as f:
        json.dump(posts, f, indent=4)

# --- ROUTES ---

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

@app.route('/api/posts', methods=['GET'])
@login_required
def get_posts():
    posts = read_posts()
    for p in posts:
        if 'id' not in p:
            p['id'] = p.get('image_url', '').split('/')[-1].split('.')[0]
        if 'price' not in p:
            p['price'] = random.randint(10, 50)
        if 'likes' not in p:
            p['likes'] = 0
        if 'type' not in p:
            p['type'] = 'video' if p.get('image_url', '').lower().endswith(('.mp4', '.webm', '.mov')) else 'image'
    return jsonify(posts)

@app.route('/api/upload', methods=['POST'])
@login_required
def upload_post():
    if 'media' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['media']
    caption = request.form.get('caption', '')
    
    raw_price = request.form.get('price', '')
    try:
        price = int(raw_price) if raw_price else random.randint(10, 50)
    except ValueError:
        price = random.randint(10, 50)
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

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
            'image_url': f"/static/images/{filename}",
            'type': media_type,
            'caption': caption,
            'price': price,
            'likes': 0,
            'date': datetime.now().strftime("%B %d, %Y")
        }

        posts = read_posts()
        posts.insert(0, new_post) 
        save_posts(posts)

        return jsonify(new_post)
    else:
        return jsonify({'error': 'Invalid file type.'}), 400

@app.route('/api/like', methods=['POST'])
@login_required
def like_post():
    data = request.get_json()
    post_id = data.get('id')
    
    posts = read_posts()
    for p in posts:
        if p.get('id') == post_id:
            p['likes'] = p.get('likes', 0) + 1
            save_posts(posts)
            return jsonify({'success': True, 'likes': p['likes']})
            
    return jsonify({'success': False, 'error': 'Post not found'}), 404

@app.route('/api/delete', methods=['POST'])
@login_required
def delete_post():
    data = request.get_json()
    post_id = data.get('id')
    
    posts = read_posts()
    post_to_delete = next((p for p in posts if p.get('id') == post_id), None)
    
    if post_to_delete:
        updated_posts = [p for p in posts if p.get('id') != post_id]
        save_posts(updated_posts)
        filename = post_to_delete['image_url'].split('/')[-1]
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({'success': True})

    return jsonify({'success': False, 'error': 'Not found'}), 400

if __name__ == '__main__':
    print("Secure Waitress server starting on port 5000...")
    serve(app, host='0.0.0.0', port=5000)