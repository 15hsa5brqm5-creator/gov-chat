# ============================================================
# database.py - دوال متقدمة للتعامل مع قاعدة البيانات
# GOV-CHAT
# ============================================================

import sqlite3
import json
from datetime import datetime, timedelta
from contextlib import contextmanager

DATABASE = 'govchat.db'

@contextmanager
def get_db_connection():
    """سياق للتعامل مع قاعدة البيانات بشكل آمن"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

# ============================================================
# دوال المستخدمين
# ============================================================

def get_user_by_id(user_id):
    """الحصول على مستخدم بواسطة ID"""
    with get_db_connection() as conn:
        return conn.execute('''
            SELECT id, username, email, role, gold, gems, messages_count, 
                   profile_picture, name_color, font_color, theme, status_text,
                   is_invisible, is_muted, mute_until, is_banned, ban_until,
                   gender, age, country, city, private_messages_enabled
            FROM users WHERE id = ?
        ''', (user_id,)).fetchone()

def get_user_by_username(username):
    """الحصول على مستخدم بواسطة اسم المستخدم"""
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()

def update_user_profile(user_id, data):
    """تحديث الملف الشخصي للمستخدم"""
    allowed_fields = ['gender', 'age', 'country', 'city', 'status_text', 
                      'profile_picture', 'cover_photo', 'name_color', 
                      'font_color', 'font_family', 'theme', 'background_image',
                      'background_music']
    
    with get_db_connection() as conn:
        for field in allowed_fields:
            if field in data:
                conn.execute(f'UPDATE users SET {field} = ? WHERE id = ?', (data[field], user_id))

def update_privacy_settings(user_id, settings):
    """تحديث إعدادات الخصوصية"""
    allowed_settings = ['hide_age', 'hide_gender', 'hide_location', 
                        'hide_points', 'hide_gems', 'hide_gifts',
                        'private_messages_enabled', 'min_rank_for_private']
    
    with get_db_connection() as conn:
        for setting in allowed_settings:
            if setting in settings:
                conn.execute(f'UPDATE users SET {setting} = ? WHERE id = ?', (settings[setting], user_id))

def update_sound_settings(user_id, settings):
    """تحديث إعدادات الصوت"""
    allowed_sounds = ['sound_public', 'sound_private', 'sound_click', 'sound_call', 'sound_new_message']
    
    with get_db_connection() as conn:
        for sound in allowed_sounds:
            if sound in settings:
                conn.execute(f'UPDATE users SET {sound} = ? WHERE id = ?', (settings[sound], user_id))

def get_user_notifications(user_id, limit=20):
    """الحصول على إشعارات المستخدم"""
    with get_db_connection() as conn:
        return conn.execute('''
            SELECT id, type, title, content, action_data, is_read, created_at
            FROM notifications WHERE user_id = ? 
            ORDER BY created_at DESC LIMIT ?
        ''', (user_id, limit)).fetchall()

def mark_notification_read(notification_id):
    """تحديد إشعار كمقروء"""
    with get_db_connection() as conn:
        conn.execute('UPDATE notifications SET is_read = 1 WHERE id = ?', (notification_id,))

def get_user_rank(user_id):
    """الحصول على رتبة المستخدم مع الصلاحيات"""
    with get_db_connection() as conn:
        user = conn.execute('SELECT role FROM users WHERE id = ?', (user_id,)).fetchone()
        if user:
            return conn.execute('SELECT * FROM roles WHERE name = ?', (user['role'],)).fetchone()
    return None

def upgrade_user_rank(user_id):
    """ترقية رتبة المستخدم تلقائياً"""
    with get_db_connection() as conn:
        user = conn.execute('SELECT role, messages_count FROM users WHERE id = ?', (user_id,)).fetchone()
        if user:
            current_rank = conn.execute('SELECT rank_level FROM roles WHERE name = ?', (user['role'],)).fetchone()
            if current_rank:
                next_rank = conn.execute('''
                    SELECT name FROM roles 
                    WHERE rank_level > ? ORDER BY rank_level LIMIT 1
                ''', (current_rank['rank_level'],)).fetchone()
                if next_rank and user['messages_count'] >= (current_rank['rank_level'] + 1) * 100:
                    conn.execute('UPDATE users SET role = ? WHERE id = ?', (next_rank['name'], user_id))
                    return next_rank['name']
    return None

# ============================================================
# دوال الرسائل والمحادثات
# ============================================================

def get_room_messages(room_id, limit=50, offset=0):
    """الحصول على رسائل الغرفة"""
    with get_db_connection() as conn:
        return conn.execute('''
            SELECT id, user_id, username, message, message_type, file_path, 
                   voice_path, is_deleted, reply_to, created_at
            FROM messages WHERE room_id = ? AND is_deleted = 0
            ORDER BY created_at DESC LIMIT ? OFFSET ?
        ''', (room_id, limit, offset)).fetchall()

def get_private_conversation(user1_id, user2_id, limit=50):
    """الحصول على المحادثة الخاصة بين مستخدمين"""
    with get_db_connection() as conn:
        return conn.execute('''
            SELECT id, from_user_id, to_user_id, from_username, to_username, 
                   message, is_read, created_at
            FROM private_messages 
            WHERE (from_user_id = ? AND to_user_id = ?) 
               OR (from_user_id = ? AND to_user_id = ?)
            ORDER BY created_at DESC LIMIT ?
        ''', (user1_id, user2_id, user2_id, user1_id, limit)).fetchall()

def delete_message_for_all(message_id, user_id):
    """حذف رسالة للجميع (للمشرفين والمالك)"""
    with get_db_connection() as conn:
        conn.execute('''
            UPDATE messages SET is_deleted = 1, deleted_by = ? 
            WHERE id = ?
        ''', (user_id, message_id))

# ============================================================
# دوال الغرف
# ============================================================

def create_room(room_data):
    """إنشاء غرفة جديدة"""
    with get_db_connection() as conn:
        cursor = conn.execute('''
            INSERT INTO rooms (name, display_name, description, password, icon, type, is_voice_room, welcome_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (room_data['name'], room_data['display_name'], room_data.get('description', ''),
              room_data.get('password'), room_data.get('icon', '🏠'), 
              room_data.get('type', 'public'), room_data.get('is_voice_room', 0),
              room_data.get('welcome_message', 'مرحباً بك في الغرفة')))
        return cursor.lastrowid

def update_room(room_id, room_data):
    """تحديث معلومات الغرفة"""
    with get_db_connection() as conn:
        for key, value in room_data.items():
            if value is not None:
                conn.execute(f'UPDATE rooms SET {key} = ? WHERE id = ?', (value, room_id))

def delete_room(room_id):
    """حذف غرفة (للأدمن فقط)"""
    with get_db_connection() as conn:
        conn.execute('DELETE FROM rooms WHERE id = ? AND name NOT IN ("main", "contests", "voices")', (room_id,))

def get_room_by_name(room_name):
    """الحصول على غرفة بواسطة الاسم"""
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM rooms WHERE name = ?', (room_name,)).fetchone()

def get_all_rooms():
    """الحصول على جميع الغرف"""
    with get_db_connection() as conn:
        return conn.execute('SELECT * FROM rooms ORDER BY id').fetchall()

# ============================================================
# دوال العقوبات
# ============================================================

def mute_user(user_id, admin_id, admin_username, duration_minutes, reason=''):
    """كتم مستخدم لفترة محددة"""
    mute_until = datetime.now() + timedelta(minutes=duration_minutes)
    with get_db_connection() as conn:
        conn.execute('''
            UPDATE users SET is_muted = 1, mute_until = ? WHERE id = ?
        ''', (mute_until.isoformat(), user_id))
        conn.execute('''
            INSERT INTO punishments (user_id, admin_id, admin_username, type, reason, duration, expires_at)
            VALUES (?, ?, ?, 'mute', ?, ?, ?)
        ''', (user_id, admin_id, admin_username, reason, duration_minutes, mute_until.isoformat()))

def kick_user(user_id, admin_id, admin_username, reason=''):
    """طرد مستخدم من الغرفة"""
    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO punishments (user_id, admin_id, admin_username, type, reason)
            VALUES (?, ?, ?, 'kick', ?)
        ''', (user_id, admin_id, admin_username, reason))

def ban_user(user_id, admin_id, admin_username, duration_days=0, reason=''):
    """حظر مستخدم"""
    ban_until = datetime.now() + timedelta(days=duration_days) if duration_days > 0 else None
    with get_db_connection() as conn:
        conn.execute('''
            UPDATE users SET is_banned = 1, ban_until = ? WHERE id = ?
        ''', (ban_until.isoformat() if ban_until else None, user_id))
        conn.execute('''
            INSERT INTO punishments (user_id, admin_id, admin_username, type, reason, duration, expires_at)
            VALUES (?, ?, ?, 'ban', ?, ?, ?)
        ''', (user_id, admin_id, admin_username, reason, duration_days, ban_until.isoformat() if ban_until else None))

def unban_user(user_id):
    """رفع الحظر عن مستخدم"""
    with get_db_connection() as conn:
        conn.execute('UPDATE users SET is_banned = 0, ban_until = NULL WHERE id = ?', (user_id,))

def get_user_punishments(user_id):
    """الحصول على قائمة عقوبات المستخدم"""
    with get_db_connection() as conn:
        return conn.execute('''
            SELECT * FROM punishments WHERE user_id = ? ORDER BY created_at DESC
        ''', (user_id,)).fetchall()

# ============================================================
# دوال المسابقات
# ============================================================

def get_active_contest():
    """الحصول على سؤال المسابقة النشط"""
    with get_db_connection() as conn:
        return conn.execute('''
            SELECT * FROM contests WHERE is_active = 1 ORDER BY id DESC LIMIT 1
        ''').fetchone()

def check_contest_answer(contest_id, user_id, answer):
    """التحقق من إجابة المسابقة"""
    with get_db_connection() as conn:
        contest = conn.execute('SELECT answer, reward_gold, reward_gems FROM contests WHERE id = ?', (contest_id,)).fetchone()
        if contest and contest['answer'].lower() == answer.lower():
            # إضافة المكافأة
            conn.execute('UPDATE users SET gold = gold + ?, gems = gems + ? WHERE id = ?', 
                        (contest['reward_gold'], contest['reward_gems'], user_id))
            # تحديث نقاط المسابقة
            conn.execute('''
                INSERT INTO contest_points (user_id, points) VALUES (?, 10)
                ON CONFLICT(user_id) DO UPDATE SET points = points + 10
            ''', (user_id,))
            return True
    return False

def add_contest_question(question, answer, hint, reward_gold, reward_gems):
    """إضافة سؤال مسابقة جديد (للمالك)"""
    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO contests (question, answer, hint, reward_gold, reward_gems, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
        ''', (question, answer, hint, reward_gold, reward_gems))
        # تعطيل الأسئلة السابقة
        conn.execute('UPDATE contests SET is_active = 0 WHERE id < (SELECT MAX(id) FROM contests)')

# ============================================================
# دوال المنشورات والحائط
# ============================================================

def create_post(user_id, username, content, post_type='public', image_path=None):
    """إنشاء منشور جديد على الحائط"""
    with get_db_connection() as conn:
        cursor = conn.execute('''
            INSERT INTO posts (user_id, username, content, post_type, image_path)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, username, content, post_type, image_path))
        return cursor.lastrowid

def get_posts(post_type='public', limit=50):
    """الحصول على منشورات الحائط"""
    with get_db_connection() as conn:
        if post_type == 'public':
            return conn.execute('''
                SELECT p.*, 
                       (SELECT COUNT(*) FROM post_comments WHERE post_id = p.id) as comments_count
                FROM posts p WHERE p.post_type IN ('public', 'news')
                ORDER BY p.is_pinned DESC, p.created_at DESC LIMIT ?
            ''', (limit,)).fetchall()
        else:
            return conn.execute('''
                SELECT p.*, 
                       (SELECT COUNT(*) FROM post_comments WHERE post_id = p.id) as comments_count
                FROM posts p WHERE p.post_type = ?
                ORDER BY p.created_at DESC LIMIT ?
            ''', (post_type, limit)).fetchall()

def add_comment_to_post(post_id, user_id, username, content):
    """إضافة تعليق على منشور"""
    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO post_comments (post_id, user_id, username, content)
            VALUES (?, ?, ?, ?)
        ''', (post_id, user_id, username, content))

# ============================================================
# دوال الإحصائيات
# ============================================================

def get_global_stats():
    """الحصول على إحصائيات عامة للشات"""
    with get_db_connection() as conn:
        total_users = conn.execute('SELECT COUNT(*) as count FROM users').fetchone()['count']
        total_messages = conn.execute('SELECT COUNT(*) as count FROM messages').fetchone()['count']
        online_now = conn.execute('''
            SELECT COUNT(*) as count FROM active_users 
            WHERE last_activity > datetime('now', '-5 minutes')
        ''').fetchone()['count']
        total_gold = conn.execute('SELECT SUM(gold) as total FROM users').fetchone()['total'] or 0
        total_gems = conn.execute('SELECT SUM(gems) as total FROM users').fetchone()['total'] or 0
        
        return {
            'total_users': total_users,
            'total_messages': total_messages,
            'online_now': online_now,
            'total_gold': total_gold,
            'total_gems': total_gems
        }

def get_user_stats(user_id):
    """الحصول على إحصائيات مستخدم محدد"""
    with get_db_connection() as conn:
        user = conn.execute('''
            SELECT username, role, gold, gems, messages_count, created_at, last_seen
            FROM users WHERE id = ?
        ''', (user_id,)).fetchone()
        
        if user:
            # عدد الأصدقاء
            friends_count = conn.execute('SELECT COUNT(*) as count FROM friends WHERE user_id = ?', (user_id,)).fetchone()['count']
            # عدد الهدايا المستلمة
            gifts_received = conn.execute('SELECT COUNT(*) as count FROM sent_gifts WHERE to_user_id = ?', (user_id,)).fetchone()['count']
            
            return {
                'username': user['username'],
                'role': user['role'],
                'gold': user['gold'],
                'gems': user['gems'],
                'messages_count': user['messages_count'],
                'friends_count': friends_count,
                'gifts_received': gifts_received,
                'joined_date': user['created_at'],
                'last_seen': user['last_seen']
            }
    return None

# ============================================================
# دوال الإبلاغ والإدارة
# ============================================================

def report_user(reporter_id, reporter_username, reported_user_id, reason):
    """إبلاغ عن مستخدم"""
    with get_db_connection() as conn:
        conn.execute('''
            INSERT INTO reports (reported_user_id, reporter_user_id, reporter_username, reason)
            VALUES (?, ?, ?, ?)
        ''', (reported_user_id, reporter_id, reporter_username, reason))

def get_pending_reports():
    """الحصول على التقارير المعلقة (للمالك)"""
    with get_db_connection() as conn:
        return conn.execute('''
            SELECT r.*, u.username as reported_username
            FROM reports r
            JOIN users u ON r.reported_user_id = u.id
            WHERE r.status = 'pending'
            ORDER BY r.created_at DESC
        ''').fetchall()

def resolve_report(report_id, status):
    """حل تقرير (قبول أو رفض)"""
    with get_db_connection() as conn:
        conn.execute('UPDATE reports SET status = ? WHERE id = ?', (status, report_id))

# ============================================================
# دوال النسخ الاحتياطي والاستعادة
# ============================================================

def backup_database():
    """إنشاء نسخة احتياطية من قاعدة البيانات"""
    import shutil
    from datetime import datetime
    
    backup_name = f'backups/govchat_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.db'
    os.makedirs('backups', exist_ok=True)
    shutil.copy2(DATABASE, backup_name)
    return backup_name

def get_database_size():
    """الحصول على حجم قاعدة البيانات"""
    import os
    if os.path.exists(DATABASE):
        return os.path.getsize(DATABASE)
    return 0

# ============================================================
# دوال النظام والإعدادات
# ============================================================

def get_system_settings():
    """الحصول على إعدادات النظام"""
    with get_db_connection() as conn:
        # إنشاء جدول الإعدادات إذا لم يكن موجوداً
        conn.execute('''
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        settings = conn.execute('SELECT key, value FROM system_settings').fetchall()
        return {s['key']: s['value'] for s in settings}

def set_system_setting(key, value):
    """تعديل إعداد نظام"""
    with get_db_connection() as conn:
        conn.execute('''
            INSERT OR REPLACE INTO system_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (key, value))

def cleanup_old_data():
    """تنظيف البيانات القديمة (جلسات قديمة، رسائل قديمة، الخ)"""
    with get_db_connection() as conn:
        # حذف الجلسات النشطة القديمة (أكثر من 24 ساعة)
        conn.execute('DELETE FROM active_users WHERE last_activity < datetime("now", "-24 hours")')
        # حذف Stories منتهية الصلاحية
        conn.execute('DELETE FROM stories WHERE expires_at < CURRENT_TIMESTAMP')
        # حذف الإشعارات القديمة (أكثر من 30 يوم)
        conn.execute('DELETE FROM notifications WHERE created_at < datetime("now", "-30 days")')

# ============================================================
# نهاية database.py
# ============================================================
