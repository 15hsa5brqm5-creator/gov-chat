import os
import sqlite3
import hashlib
import secrets
import time
import re
import json
import threading
import random
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, g
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_bcrypt import Bcrypt
from functools import wraps
import base64
import requests

# ============================================================
# الإعدادات الأساسية
# ============================================================

app = Flask(__name__)
app.config['SECRET_KEY'] = 'gov-chat-super-secret-key-2024-CHANGE-THIS'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = 'static/uploads'

bcrypt = Bcrypt(app)
# استخدام polling بدلاً من websockets لتجنب eventlet
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static/profiles', exist_ok=True)
os.makedirs('static/gifts', exist_ok=True)
os.makedirs('static/voice', exist_ok=True)
os.makedirs('static/stories', exist_ok=True)

DATABASE = 'govchat.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(DATABASE)
    cursor = db.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            password TEXT NOT NULL,
            is_guest BOOLEAN DEFAULT 1,
            role TEXT DEFAULT 'visitor',
            gender TEXT,
            age INTEGER,
            country TEXT,
            city TEXT,
            ip_address TEXT,
            last_seen TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            gold INTEGER DEFAULT 0,
            gems INTEGER DEFAULT 0,
            messages_count INTEGER DEFAULT 0,
            profile_picture TEXT,
            name_color TEXT DEFAULT '#ffffff',
            is_banned INTEGER DEFAULT 0,
            is_muted INTEGER DEFAULT 0,
            mute_until TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS private_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER NOT NULL,
            from_username TEXT NOT NULL,
            to_username TEXT NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # إنشاء مستخدم المالك إذا لم يوجد
    password_hash = bcrypt.generate_password_hash('Admin@123').decode('utf-8')
    cursor.execute('''
        INSERT OR IGNORE INTO users 
        (username, email, password, is_guest, role, gold, gems)
        VALUES ('Admin', 'admin@govchat.com', ?, 0, 'owner', 100000, 1000)
    ''', (password_hash,))
    
    db.commit()
    db.close()
    print("✅ قاعدة البيانات تم إنشاؤها بنجاح")
    print("👤 حساب المالك: Admin")
    print("🔑 كلمة المرور: Admin@123")

init_db()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'يجب تسجيل الدخول أولاً'}), 401
        return f(*args, **kwargs)
    return decorated_function

# ============================================================
# المسارات
# ============================================================

@app.route('/')
def index():
    if 'user_id' in session:
        return render_template('chat.html')
    return render_template('login.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/chat')
def chat_page():
    return render_template('chat.html')

@app.route('/admin')
def admin_panel():
    return render_template('admin.html')

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
    username = data.get('username', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    
    if not username or len(username) < 3:
        return jsonify({'error': 'اسم المستخدم يجب أن يكون 3 أحرف على الأقل'}), 400
    
    if not password or len(password) < 6:
        return jsonify({'error': 'كلمة المرور يجب أن تكون 6 أحرف على الأقل'}), 400
    
    db = get_db()
    existing = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
    if existing:
        return jsonify({'error': 'اسم المستخدم موجود مسبقاً'}), 400
    
    password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    cursor = db.cursor()
    cursor.execute('''
        INSERT INTO users (username, email, password, is_guest, role, gold, gems)
        VALUES (?, ?, ?, 0, 'visitor', 100, 2)
    ''', (username, email, password_hash))
    
    user_id = cursor.lastrowid
    db.commit()
    
    session['user_id'] = user_id
    session['username'] = username
    session['role'] = 'visitor'
    
    return jsonify({'success': True, 'user_id': user_id, 'username': username})

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    db = get_db()
    user = db.execute('SELECT id, username, password, role FROM users WHERE username = ?', (username,)).fetchone()
    
    if not user or not bcrypt.check_password_hash(user['password'], password):
        return jsonify({'error': 'اسم المستخدم أو كلمة المرور غير صحيحة'}), 401
    
    session['user_id'] = user['id']
    session['username'] = user['username']
    session['role'] = user['role']
    
    return jsonify({'success': True, 'user_id': user['id'], 'username': user['username']})

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/guest-login', methods=['POST'])
def api_guest_login():
    data = request.get_json()
    guest_name = data.get('username', f'زائر_{random.randint(1000, 9999)}')
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''
        INSERT INTO users (username, is_guest, role, gold, gems)
        VALUES (?, 1, 'visitor', 50, 0)
    ''', (guest_name,))
    
    user_id = cursor.lastrowid
    db.commit()
    
    session['user_id'] = user_id
    session['username'] = guest_name
    session['role'] = 'visitor'
    
    return jsonify({'success': True, 'user_id': user_id, 'username': guest_name})

@app.route('/api/user/stats')
@login_required
def api_user_stats():
    db = get_db()
    user = db.execute('SELECT id, username, role, gold, gems, messages_count FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    return jsonify(dict(user))

@app.route('/api/send-message', methods=['POST'])
@login_required
def api_send_message():
    data = request.get_json()
    room = data.get('room', 'main')
    message = data.get('message', '').strip()
    
    if not message:
        return jsonify({'error': 'الرسالة فارغة'}), 400
    
    db = get_db()
    db.execute('''
        INSERT INTO messages (room, user_id, username, message)
        VALUES (?, ?, ?, ?)
    ''', (room, session['user_id'], session['username'], message))
    db.execute('UPDATE users SET messages_count = messages_count + 1 WHERE id = ?', (session['user_id'],))
    db.commit()
    
    # بث الرسالة لجميع المستخدمين (بدون WebSockets حقيقي)
    socketio.emit('new_message', {
        'username': session['username'],
        'message': message,
        'time': datetime.now().strftime('%H:%M'),
        'user_role': session.get('role', 'visitor')
    }, room=room)
    
    return jsonify({'success': True})

# مهام تلقائية بسيطة
def auto_gold_task():
    while True:
        time.sleep(60)
        db = sqlite3.connect(DATABASE)
        db.execute('UPDATE users SET gold = gold + 100')
        db.commit()
        db.close()

threading.Thread(target=auto_gold_task, daemon=True).start()

# ============================================================
# تشغيل الخادم
# ============================================================

if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║                    GOV-CHAT - الشات الحكومي               ║
    ║                                                          ║
    ║  ✅ تم تشغيل الخادم بنجاح                                 ║
    ║  🔗     http://localhost:5000                           ║
    ║                                                          ║
    ║  👤 حساب المالك: Admin                                   ║
    ║  🔑 كلمة المرور: Admin@123                               ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, use_reloader=False)
