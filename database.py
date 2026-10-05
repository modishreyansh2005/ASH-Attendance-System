import sqlite3
import os
import re
import shutil
from datetime import datetime, date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ORIGINAL_DB_PATH = os.path.join(BASE_DIR, 'attendance.db')

# On Vercel or read-only filesystem environments, copy DB to /tmp for write access
if os.environ.get('VERCEL') or not os.access(BASE_DIR, os.W_OK):
    TMP_DIR = '/tmp'
    DB_PATH = os.path.join(TMP_DIR, 'attendance.db')
    if os.path.exists(ORIGINAL_DB_PATH) and not os.path.exists(DB_PATH):
        try:
            shutil.copy2(ORIGINAL_DB_PATH, DB_PATH)
        except Exception as e:
            print(f"Error copying DB to /tmp: {e}")
else:
    DB_PATH = ORIGINAL_DB_PATH


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        grade TEXT NOT NULL,
        section TEXT NOT NULL,
        roll_no TEXT NOT NULL,
        gender TEXT DEFAULT 'Other',
        category TEXT DEFAULT 'General',
        dob TEXT DEFAULT '',
        guardian_name TEXT,
        parent_phone TEXT,
        guardian_phone TEXT,
        photo_path TEXT,
        status TEXT DEFAULT 'Active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Migration: ensure parent_phone, category, and dob columns exist
    cursor.execute("PRAGMA table_info(students)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'parent_phone' not in columns:
        cursor.execute("ALTER TABLE students ADD COLUMN parent_phone TEXT")
        cursor.execute("UPDATE students SET parent_phone = guardian_phone WHERE parent_phone IS NULL")
    if 'category' not in columns:
        cursor.execute("ALTER TABLE students ADD COLUMN category TEXT DEFAULT 'General'")
    if 'dob' not in columns:
        cursor.execute("ALTER TABLE students ADD COLUMN dob TEXT DEFAULT ''")

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Present',
        method TEXT NOT NULL DEFAULT 'Camera-OpenCV',
        confidence REAL DEFAULT 0.0,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(student_id, date),
        FOREIGN KEY (student_id) REFERENCES students (student_id) ON DELETE CASCADE
    )
    ''')

    # Index for fast daily query lookups
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_student_grade ON students(grade, section)')

    # Table for tracking automated WhatsApp messages sent to parents
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS whatsapp_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL,
        student_name TEXT,
        parent_phone TEXT NOT NULL,
        message TEXT,
        status TEXT DEFAULT 'Sent',
        sent_date TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_whatsapp_date ON whatsapp_logs(sent_date)')

    # Table for School Monthly Holidays & Academic Calendar
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS holidays (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        holiday_date TEXT NOT NULL,
        holiday_type TEXT DEFAULT 'National',
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_holidays_date ON holidays(holiday_date)')

    # Table for storing individual biometric face training samples (Section 15)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS face_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL,
        image_path TEXT NOT NULL,
        capture_angle TEXT DEFAULT 'Front',
        quality_score REAL DEFAULT 100.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id) REFERENCES students (student_id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_face_samples_sid ON face_samples(student_id)')

    # Table for recognition audit logs (Section 11 & Section 15)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS recognition_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        detected_label TEXT,
        confidence REAL DEFAULT 0.0,
        result TEXT NOT NULL,
        camera_id TEXT DEFAULT 'webcam-1'
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_rec_logs_time ON recognition_logs(timestamp)')

    # Table for examination results and rank tracking
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS exam_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT,
        student_name TEXT NOT NULL,
        roll_no TEXT NOT NULL,
        class_grade TEXT DEFAULT '',
        subject TEXT NOT NULL,
        marks_obtained REAL NOT NULL,
        max_marks REAL DEFAULT 100.0,
        rank INTEGER DEFAULT 0,
        exam_term TEXT DEFAULT 'Annual Exam 2026',
        grade TEXT DEFAULT '',
        remarks TEXT DEFAULT '',
        exam_date TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_exam_results_term ON exam_results(exam_term)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_exam_results_subject ON exam_results(subject)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_exam_results_roll ON exam_results(roll_no)')

    # Migration check for exam_results columns and nullability
    cursor.execute("PRAGMA table_info(exam_results)")
    er_info = {row[1]: row for row in cursor.fetchall()}
    er_cols = list(er_info.keys())
    if 'student_name' not in er_cols:
        cursor.execute("ALTER TABLE exam_results ADD COLUMN student_name TEXT DEFAULT ''")
    if 'roll_no' not in er_cols:
        cursor.execute("ALTER TABLE exam_results ADD COLUMN roll_no TEXT DEFAULT ''")
    if 'class_grade' not in er_cols:
        cursor.execute("ALTER TABLE exam_results ADD COLUMN class_grade TEXT DEFAULT ''")
    if 'rank' not in er_cols:
        cursor.execute("ALTER TABLE exam_results ADD COLUMN rank INTEGER DEFAULT 0")

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_exam_results_class ON exam_results(class_grade)')

    # If student_id has strict NOT NULL constraint or FK enforcement, recreate cleanly
    if 'student_id' in er_info and er_info['student_id'][3] == 1:
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS exam_results_migration (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT DEFAULT '',
            student_name TEXT NOT NULL,
            roll_no TEXT NOT NULL,
            class_grade TEXT DEFAULT '',
            subject TEXT NOT NULL,
            marks_obtained REAL NOT NULL,
            max_marks REAL DEFAULT 100.0,
            rank INTEGER DEFAULT 0,
            exam_term TEXT DEFAULT 'Annual Exam 2026',
            grade TEXT DEFAULT '',
            remarks TEXT DEFAULT '',
            exam_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        cursor.execute('''
        INSERT INTO exam_results_migration (id, student_id, student_name, roll_no, class_grade, subject, marks_obtained, max_marks, rank, exam_term, grade, remarks, exam_date, created_at)
        SELECT id, COALESCE(student_id, ''), COALESCE(student_name, ''), COALESCE(roll_no, ''), COALESCE(class_grade, ''), COALESCE(subject, 'General'), marks_obtained, max_marks, COALESCE(rank, 0), exam_term, grade, remarks, exam_date, created_at
        FROM exam_results
        ''')
        cursor.execute("DROP TABLE exam_results")
        cursor.execute("ALTER TABLE exam_results_migration RENAME TO exam_results")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_exam_results_term ON exam_results(exam_term)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_exam_results_subject ON exam_results(subject)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_exam_results_roll ON exam_results(roll_no)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_exam_results_class ON exam_results(class_grade)')

    # Table for Parent Online Absence & Leave Applications
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS parent_leaves (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id TEXT NOT NULL,
        leave_type TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        reason TEXT NOT NULL,
        status TEXT DEFAULT 'Submitted',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id) REFERENCES students (student_id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_parent_leaves_sid ON parent_leaves(student_id)')

    # Seed default academic & gazetted holidays if empty
    cursor.execute('SELECT COUNT(*) FROM holidays')
    if cursor.fetchone()[0] == 0:
        default_holidays = [
            ("Republic Day", "2026-01-26", "National", "Celebration of the Constitution of India"),
            ("Maha Shivratri", "2026-02-15", "Festival", "Festival dedicated to Lord Shiva"),
            ("Holi (Festival of Colors)", "2026-03-04", "Festival", "Spring festival of joy, unity and colors"),
            ("Id-ul-Fitr (Ramadan)", "2026-03-20", "Religious", "Islamic festival of breaking the fast"),
            ("Mahavir Jayanti", "2026-03-31", "Religious", "Birth anniversary of Lord Mahavira"),
            ("Good Friday", "2026-04-03", "Religious", "Christian observance of Easter weekend"),
            ("Dr. B.R. Ambedkar Jayanti", "2026-04-14", "National", "Birth anniversary of the architect of the Indian Constitution"),
            ("Buddha Purnima", "2026-05-01", "Religious", "Birth anniversary of Gautama Buddha"),
            ("Summer Recess (Academic Break)", "2026-05-15", "Academic", "Annual summer school vacation begins"),
            ("Bakrid / Eid al-Adha", "2026-05-27", "Religious", "Feast of the Sacrifice"),
            ("Muharram", "2026-06-26", "Religious", "Islamic New Year observance"),
            ("Independence Day", "2026-08-15", "National", "Commemoration of India's Independence"),
            ("Raksha Bandhan", "2026-08-28", "Festival", "Celebration of sibling bonds"),
            ("Janmashtami", "2026-09-04", "Festival", "Birth celebration of Lord Krishna"),
            ("Milad-un-Nabi (Id-e-Milad)", "2026-09-05", "Religious", "Prophet Muhammad's Birthday"),
            ("Gandhi Jayanti", "2026-10-02", "National", "Birthday of Mahatma Gandhi (Father of the Nation)"),
            ("Maha Ashtami / Durga Puja", "2026-10-18", "Festival", "Durga Puja festival celebration"),
            ("Dussehra (Vijayadashami)", "2026-10-20", "Festival", "Victory of good over evil"),
            ("Diwali (Deepavali)", "2026-11-08", "Festival", "Festival of Lights and prosperity"),
            ("Govardhan Puja", "2026-11-09", "Festival", "Post-Diwali traditional worship"),
            ("Bhai Dooj", "2026-11-10", "Festival", "Auspicious celebration of brother-sister bond"),
            ("Guru Nanak Jayanti", "2026-11-24", "Religious", "Birth celebration of Guru Nanak Dev Ji"),
            ("Christmas Day", "2026-12-25", "Religious", "Joyous celebration of Christmas"),
            ("Winter Vacation Break", "2026-12-28", "Academic", "Annual winter school recess")
        ]
        cursor.executemany('''
        INSERT INTO holidays (title, holiday_date, holiday_type, description)
        VALUES (?, ?, ?, ?)
        ''', default_holidays)

    conn.commit()
    conn.close()

def get_all_students(filter_grade=None, search=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = '''
    SELECT s.*,
           COALESCE((SELECT COUNT(*) FROM face_samples fs WHERE fs.student_id = s.student_id), 0) AS db_samples_count
    FROM students s
    WHERE s.status = "Active"
    '''
    params = []

    if filter_grade:
        query += ' AND s.grade = ?'
        params.append(filter_grade)

    if search:
        query += ' AND (s.full_name LIKE ? OR s.student_id LIKE ? OR s.roll_no LIKE ?)'
        wildcard = f'%{search}%'
        params.extend([wildcard, wildcard, wildcard])

    query += ' ORDER BY s.grade, s.section, CAST(s.roll_no AS INTEGER), s.roll_no, s.full_name'
    cursor.execute(query, params)
    students = cursor.fetchall()
    conn.close()
    
    result = []
    dataset_base = os.path.join(os.path.dirname(__file__), 'static', 'dataset')
    for s in students:
        d = dict(s)
        # Check files on disk if db_samples_count is 0
        disk_count = 0
        s_dir = os.path.join(dataset_base, str(d['student_id']))
        if os.path.isdir(s_dir):
            disk_count = len([f for f in os.listdir(s_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
        d['samples_count'] = max(d.get('db_samples_count', 0), disk_count)
        d['biometric_enrolled'] = d['samples_count'] > 0
        result.append(d)
    return result

def get_student_by_id(student_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT s.*,
           COALESCE((SELECT COUNT(*) FROM face_samples fs WHERE fs.student_id = s.student_id), 0) AS db_samples_count
    FROM students s
    WHERE s.student_id = ?
    ''', (student_id,))
    student = cursor.fetchone()
    conn.close()
    if not student:
        return None
    d = dict(student)
    dataset_base = os.path.join(os.path.dirname(__file__), 'static', 'dataset')
    s_dir = os.path.join(dataset_base, str(student_id))
    disk_count = 0
    if os.path.isdir(s_dir):
        disk_count = len([f for f in os.listdir(s_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
    d['samples_count'] = max(d.get('db_samples_count', 0), disk_count)
    d['biometric_enrolled'] = d['samples_count'] > 0
    return d

def get_student_by_db_id(pk_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM students WHERE id = ?', (pk_id,))
    student = cursor.fetchone()
    conn.close()
    return dict(student) if student else None

def insert_student(student_id, full_name, grade, section, roll_no, gender='Other', guardian_name='', guardian_phone='', photo_path='', parent_phone='', category='General', dob=''):
    conn = get_db_connection()
    cursor = conn.cursor()
    if not parent_phone and guardian_phone:
        parent_phone = guardian_phone
    if not guardian_phone and parent_phone:
        guardian_phone = parent_phone
    if not category:
        category = 'General'
    if not dob:
        dob = ''
    try:
        cursor.execute('''
        INSERT INTO students (student_id, full_name, grade, section, roll_no, gender, category, dob, guardian_name, parent_phone, guardian_phone, photo_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (student_id, full_name, grade, section, roll_no, gender, category, dob, guardian_name, parent_phone, guardian_phone, photo_path))
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        return new_id
    except sqlite3.IntegrityError:
        conn.close()
        return None

def update_student(student_id, full_name, grade, section, roll_no, gender, guardian_name, guardian_phone, photo_path=None, parent_phone='', category='General', dob=''):
    conn = get_db_connection()
    cursor = conn.cursor()
    if not parent_phone and guardian_phone:
        parent_phone = guardian_phone
    if not guardian_phone and parent_phone:
        guardian_phone = parent_phone
    if not category:
        category = 'General'
    if not dob:
        dob = ''
    if photo_path:
        cursor.execute('''
        UPDATE students SET full_name=?, grade=?, section=?, roll_no=?, gender=?, category=?, dob=?, guardian_name=?, parent_phone=?, guardian_phone=?, photo_path=?
        WHERE student_id=?
        ''', (full_name, grade, section, roll_no, gender, category, dob, guardian_name, parent_phone, guardian_phone, photo_path, student_id))
    else:
        cursor.execute('''
        UPDATE students SET full_name=?, grade=?, section=?, roll_no=?, gender=?, category=?, dob=?, guardian_name=?, parent_phone=?, guardian_phone=?
        WHERE student_id=?
        ''', (full_name, grade, section, roll_no, gender, category, dob, guardian_name, parent_phone, guardian_phone, student_id))
    conn.commit()
    conn.close()

def reorder_all_students(base_id=1001):
    """
    Automatically re-sequences student IDs (STU-1001, STU-1002, ...) and class roll numbers (1, 2, 3...)
    without gaps whenever a student is removed from between or upon manual trigger.
    Updates all associated database tables, dataset directories, and profile photos.
    """
    import shutil
    import uuid
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, student_id, full_name, grade, section, roll_no, photo_path
        FROM students
        WHERE status = "Active"
        ORDER BY grade ASC, section ASC, CAST(roll_no AS INTEGER) ASC, roll_no ASC, id ASC
    ''')
    students = [dict(r) for r in cursor.fetchall()]
    
    if not students:
        conn.close()
        return True, "No active students to reorder."
        
    class_counts = {}
    needed_changes = []
    base_dir = os.path.dirname(__file__)
    
    for idx, s in enumerate(students):
        tgt_id = f"STU-{base_id + idx}"
        key = (s.get('grade') or '', s.get('section') or '')
        class_counts[key] = class_counts.get(key, 0) + 1
        tgt_roll = str(class_counts[key])
        
        if s['student_id'] != tgt_id or str(s.get('roll_no', '')) != tgt_roll:
            needed_changes.append({
                'id': s['id'],
                'current_id': s['student_id'],
                'current_roll': s.get('roll_no', ''),
                'target_id': tgt_id,
                'target_roll': tgt_roll,
                'current_photo': s.get('photo_path', '')
            })
            
    if not needed_changes:
        conn.close()
        return True, "All students are already in sequential order."
        
    # Phase 1: Temporary rename to prevent any collisions or unique constraint failures
    for item in needed_changes:
        if item['current_id'] != item['target_id']:
            temp_id = f"TEMP_{item['id']}_{uuid.uuid4().hex[:6]}"
            item['temp_id'] = temp_id
            
            # DB updates to temp_id
            cursor.execute('UPDATE students SET student_id = ? WHERE id = ?', (temp_id, item['id']))
            cursor.execute('UPDATE attendance SET student_id = ? WHERE student_id = ?', (temp_id, item['current_id']))
            cursor.execute('UPDATE face_samples SET student_id = ? WHERE student_id = ?', (temp_id, item['current_id']))
            cursor.execute('UPDATE whatsapp_logs SET student_id = ? WHERE student_id = ?', (temp_id, item['current_id']))
            cursor.execute('UPDATE exam_results SET student_id = ? WHERE student_id = ?', (temp_id, item['current_id']))
            cursor.execute('UPDATE recognition_logs SET detected_label = ? WHERE detected_label = ?', (temp_id, item['current_id']))
            
            # Filesystem rename to temp_id
            old_ds = os.path.join(base_dir, 'static', 'dataset', item['current_id'])
            temp_ds = os.path.join(base_dir, 'static', 'dataset', temp_id)
            if os.path.exists(old_ds):
                if os.path.exists(temp_ds):
                    shutil.rmtree(temp_ds, ignore_errors=True)
                os.rename(old_ds, temp_ds)
                
            old_prof = os.path.join(base_dir, 'static', 'uploads', 'profiles', f"{item['current_id']}.jpg")
            temp_prof = os.path.join(base_dir, 'static', 'uploads', 'profiles', f"{temp_id}.jpg")
            if os.path.exists(old_prof):
                if os.path.exists(temp_prof):
                    try: os.remove(temp_prof)
                    except: pass
                os.rename(old_prof, temp_prof)
        else:
            item['temp_id'] = item['current_id']
            
    # Phase 2: Assign target student_id and target roll_no
    for item in needed_changes:
        interm_id = item['temp_id']
        tgt_id = item['target_id']
        tgt_roll = item['target_roll']
        
        # Filesystem target rename
        temp_ds = os.path.join(base_dir, 'static', 'dataset', interm_id)
        tgt_ds = os.path.join(base_dir, 'static', 'dataset', tgt_id)
        if os.path.exists(temp_ds):
            if os.path.exists(tgt_ds) and temp_ds != tgt_ds:
                shutil.rmtree(tgt_ds, ignore_errors=True)
            os.rename(temp_ds, tgt_ds)
            
        temp_prof = os.path.join(base_dir, 'static', 'uploads', 'profiles', f"{interm_id}.jpg")
        tgt_prof = os.path.join(base_dir, 'static', 'uploads', 'profiles', f"{tgt_id}.jpg")
        if os.path.exists(temp_prof):
            if os.path.exists(tgt_prof) and temp_prof != tgt_prof:
                try: os.remove(tgt_prof)
                except: pass
            os.rename(temp_prof, tgt_prof)
            new_photo_path = f"/static/uploads/profiles/{tgt_id}.jpg"
        else:
            curr_photo = item.get('current_photo', '') or ''
            new_photo_path = curr_photo.replace(item['current_id'], tgt_id)
            
        # Update DB to target_id and target_roll
        cursor.execute('UPDATE students SET student_id = ?, roll_no = ?, photo_path = ? WHERE id = ?', (tgt_id, tgt_roll, new_photo_path, item['id']))
        cursor.execute('UPDATE attendance SET student_id = ? WHERE student_id = ?', (tgt_id, interm_id))
        cursor.execute('UPDATE face_samples SET student_id = ? WHERE student_id = ?', (tgt_id, interm_id))
        cursor.execute("UPDATE face_samples SET image_path = REPLACE(image_path, ?, ?) WHERE student_id = ?", (f"/{item['current_id']}/", f"/{tgt_id}/", tgt_id))
        cursor.execute("UPDATE face_samples SET image_path = REPLACE(image_path, ?, ?) WHERE student_id = ?", (f"\\{item['current_id']}\\", f"\\{tgt_id}\\", tgt_id))
        cursor.execute('UPDATE whatsapp_logs SET student_id = ? WHERE student_id = ?', (tgt_id, interm_id))
        cursor.execute('UPDATE exam_results SET student_id = ? WHERE student_id = ?', (tgt_id, interm_id))
        cursor.execute('UPDATE recognition_logs SET detected_label = ? WHERE detected_label = ?', (tgt_id, interm_id))

    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()
    
    # Retrain facial recognizer model with updated student ID mappings
    try:
        from face_engine import train_face_recognizer
        conn2 = get_db_connection()
        c2 = conn2.cursor()
        c2.execute('SELECT student_id, id FROM students WHERE status="Active"')
        s_map = {row['student_id']: row['id'] for row in c2.fetchall()}
        conn2.close()
        train_face_recognizer(s_map)
    except Exception as retrain_err:
        print("Model retrain notice during reorder:", retrain_err)
        
    return True, f"Successfully reordered {len(needed_changes)} students sequentially."

def delete_student(student_id, auto_reorder=True):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM students WHERE student_id = ?', (student_id,))
    cursor.execute('DELETE FROM attendance WHERE student_id = ?', (student_id,))
    cursor.execute('DELETE FROM face_samples WHERE student_id = ?', (student_id,))
    cursor.execute('DELETE FROM exam_results WHERE student_id = ?', (student_id,))
    cursor.execute('DELETE FROM parent_leaves WHERE student_id = ?', (student_id,))
    cursor.execute('DELETE FROM whatsapp_logs WHERE student_id = ?', (student_id,))
    conn.commit()
    conn.close()
    
    # Remove dataset folder & profile image
    base_dir = os.path.dirname(__file__)
    folder = os.path.join(base_dir, 'static', 'dataset', student_id)
    if os.path.exists(folder):
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
        
    profile = os.path.join(base_dir, 'static', 'uploads', 'profiles', f"{student_id}.jpg")
    if os.path.exists(profile):
        try:
            os.remove(profile)
        except:
            pass
            
    # Automatically reorder all remaining students if enabled
    if auto_reorder:
        reorder_all_students()

def record_attendance(student_id, status='Present', method='Camera-OpenCV', confidence=0.0, notes='', custom_date=None, custom_time=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    target_date = custom_date or date.today().isoformat()
    target_time = custom_time or datetime.now().strftime('%H:%M:%S')

    # If already recorded today, do not overwrite unless manual update
    cursor.execute('SELECT id, status FROM attendance WHERE student_id = ? AND date = ?', (student_id, target_date))
    existing = cursor.fetchone()

    if existing:
        conn.close()
        return False, f"Attendance already logged today for this student ({existing['status']})."

    try:
        cursor.execute('''
        INSERT INTO attendance (student_id, date, time, status, method, confidence, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (student_id, target_date, target_time, status, method, confidence, notes))
        conn.commit()
        conn.close()
        return True, "Attendance recorded successfully."
    except Exception as e:
        conn.close()
        return False, str(e)

def update_attendance_status(student_id, target_date, status, notes=""):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM students WHERE student_id = ?', (student_id,))
    if not cursor.fetchone():
        conn.close()
        return False

    target_time = datetime.now().strftime('%H:%M:%S')
    try:
        cursor.execute('''
        INSERT INTO attendance (student_id, date, time, status, method, notes)
        VALUES (?, ?, ?, ?, 'Manual', ?)
        ON CONFLICT(student_id, date) DO UPDATE SET
            status = excluded.status,
            time = excluded.time,
            notes = excluded.notes,
            method = 'Manual'
        ''', (student_id, target_date, target_time, status, notes))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        conn.close()
        return False

def get_today_attendance(target_date=None):
    if not target_date:
        target_date = date.today().isoformat()
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = '''
    SELECT 
        s.student_id,
        s.full_name,
        s.grade,
        s.section,
        s.roll_no,
        s.photo_path,
        s.gender,
        s.category,
        s.dob,
        s.guardian_name,
        COALESCE(s.parent_phone, s.guardian_phone, '') AS parent_phone,
        s.guardian_phone,
        COALESCE(a.status, 'Absent') AS attendance_status,
        a.time,
        a.method,
        a.confidence,
        a.notes,
        a.date,
        COALESCE((
            SELECT ROUND(
                CAST(COALESCE(SUM(CASE WHEN a2.status IN ('Present', 'Late') THEN 1 ELSE 0 END), 0) AS REAL) * 100.0 / 
                MAX(1, (SELECT COUNT(DISTINCT date) FROM attendance)),
                1
            )
            FROM attendance a2 
            WHERE a2.student_id = s.student_id
        ), 0.0) AS attendance_percentage
    FROM students s
    LEFT JOIN attendance a ON s.student_id = a.student_id AND a.date = ?
    WHERE s.status = 'Active'
    ORDER BY s.grade, s.section, s.roll_no
    '''
    cursor.execute(query, (target_date,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_today_marked_student_ids(target_date=None):
    """Returns a set of student_ids already marked Present or Late for the given date."""
    if not target_date:
        target_date = date.today().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT a.student_id 
        FROM attendance a
        JOIN students s ON a.student_id = s.student_id
        WHERE a.date = ? AND a.status IN ("Present", "Late") AND s.status = "Active"
    ''', (target_date,))
    rows = cursor.fetchall()
    conn.close()
    return set(r['student_id'] for r in rows)

def get_dashboard_stats(target_date=None, filter_grade=None):
    if not target_date:
        target_date = date.today().isoformat()

    conn = get_db_connection()
    cursor = conn.cursor()

    grade_clause = ""
    grade_params = []
    if filter_grade and filter_grade != 'All':
        grade_clause = " AND grade = ?"
        grade_params = [filter_grade]

    cursor.execute(f'''
    SELECT 
        COUNT(*) as total,
        COUNT(CASE WHEN LOWER(TRIM(COALESCE(gender, ''))) IN ('male', 'boy', 'm') THEN 1 END) as boys_total,
        COUNT(CASE WHEN LOWER(TRIM(COALESCE(gender, ''))) IN ('female', 'girl', 'f') THEN 1 END) as girls_total,
        COUNT(CASE WHEN LOWER(TRIM(COALESCE(gender, ''))) NOT IN ('male', 'boy', 'm', 'female', 'girl', 'f') OR gender IS NULL THEN 1 END) as others_total
    FROM students 
    WHERE status = "Active"{grade_clause}
    ''', grade_params)
    student_totals = cursor.fetchone()
    total_students = student_totals['total'] or 0
    boys_total = student_totals['boys_total'] or 0
    girls_total = student_totals['girls_total'] or 0
    others_total = student_totals['others_total'] or 0

    if filter_grade and filter_grade != 'All':
        cursor.execute('''
        SELECT 
            COUNT(CASE WHEN a.status = 'Present' THEN 1 END) as present_count,
            COUNT(CASE WHEN a.status = 'Late' THEN 1 END) as late_count,
            COUNT(CASE WHEN a.status = 'Excused' THEN 1 END) as excused_count,
            COUNT(CASE WHEN a.method = 'Camera-OpenCV' THEN 1 END) as camera_count,
            COUNT(CASE WHEN a.method = 'Manual' THEN 1 END) as manual_count,
            AVG(CASE WHEN a.confidence > 0 THEN a.confidence END) as avg_confidence,

            -- Boys attendance breakdown
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('male', 'boy', 'm') AND a.status = 'Present' THEN 1 END) as boys_present,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('male', 'boy', 'm') AND a.status = 'Late' THEN 1 END) as boys_late,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('male', 'boy', 'm') AND a.status = 'Excused' THEN 1 END) as boys_excused,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('male', 'boy', 'm') AND a.method = 'Camera-OpenCV' THEN 1 END) as boys_camera,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('male', 'boy', 'm') AND a.method = 'Manual' THEN 1 END) as boys_manual,

            -- Girls attendance breakdown
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('female', 'girl', 'f') AND a.status = 'Present' THEN 1 END) as girls_present,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('female', 'girl', 'f') AND a.status = 'Late' THEN 1 END) as girls_late,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('female', 'girl', 'f') AND a.status = 'Excused' THEN 1 END) as girls_excused,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('female', 'girl', 'f') AND a.method = 'Camera-OpenCV' THEN 1 END) as girls_camera,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('female', 'girl', 'f') AND a.method = 'Manual' THEN 1 END) as girls_manual
        FROM attendance a
        JOIN students s ON a.student_id = s.student_id
        WHERE a.date = ? AND s.grade = ? AND s.status = 'Active'
        ''', (target_date, filter_grade))
    else:
        cursor.execute('''
        SELECT 
            COUNT(CASE WHEN a.status = 'Present' THEN 1 END) as present_count,
            COUNT(CASE WHEN a.status = 'Late' THEN 1 END) as late_count,
            COUNT(CASE WHEN a.status = 'Excused' THEN 1 END) as excused_count,
            COUNT(CASE WHEN a.method = 'Camera-OpenCV' THEN 1 END) as camera_count,
            COUNT(CASE WHEN a.method = 'Manual' THEN 1 END) as manual_count,
            AVG(CASE WHEN a.confidence > 0 THEN a.confidence END) as avg_confidence,

            -- Boys attendance breakdown
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('male', 'boy', 'm') AND a.status = 'Present' THEN 1 END) as boys_present,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('male', 'boy', 'm') AND a.status = 'Late' THEN 1 END) as boys_late,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('male', 'boy', 'm') AND a.status = 'Excused' THEN 1 END) as boys_excused,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('male', 'boy', 'm') AND a.method = 'Camera-OpenCV' THEN 1 END) as boys_camera,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('male', 'boy', 'm') AND a.method = 'Manual' THEN 1 END) as boys_manual,

            -- Girls attendance breakdown
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('female', 'girl', 'f') AND a.status = 'Present' THEN 1 END) as girls_present,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('female', 'girl', 'f') AND a.status = 'Late' THEN 1 END) as girls_late,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('female', 'girl', 'f') AND a.status = 'Excused' THEN 1 END) as girls_excused,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('female', 'girl', 'f') AND a.method = 'Camera-OpenCV' THEN 1 END) as girls_camera,
            COUNT(CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('female', 'girl', 'f') AND a.method = 'Manual' THEN 1 END) as girls_manual
        FROM attendance a
        JOIN students s ON a.student_id = s.student_id
        WHERE a.date = ? AND s.status = 'Active'
        ''', (target_date,))
    att_stats = cursor.fetchone()

    present_count = att_stats['present_count'] or 0
    late_count = att_stats['late_count'] or 0
    excused_count = att_stats['excused_count'] or 0
    camera_count = att_stats['camera_count'] or 0
    manual_count = att_stats['manual_count'] or 0
    raw_conf = att_stats['avg_confidence']
    avg_confidence = round(raw_conf, 1) if raw_conf is not None else 0.0

    marked_total = present_count + late_count + excused_count
    absent_count = max(0, total_students - marked_total)
    rate = round((marked_total / total_students * 100), 1) if total_students > 0 else 0.0

    # Separated Boys metrics
    boys_present = att_stats['boys_present'] or 0
    boys_late = att_stats['boys_late'] or 0
    boys_excused = att_stats['boys_excused'] or 0
    boys_camera = att_stats['boys_camera'] or 0
    boys_manual = att_stats['boys_manual'] or 0
    boys_marked = boys_present + boys_late + boys_excused
    boys_absent = max(0, boys_total - boys_marked)
    boys_rate = round((boys_marked / boys_total * 100), 1) if boys_total > 0 else 0.0

    # Separated Girls metrics
    girls_present = att_stats['girls_present'] or 0
    girls_late = att_stats['girls_late'] or 0
    girls_excused = att_stats['girls_excused'] or 0
    girls_camera = att_stats['girls_camera'] or 0
    girls_manual = att_stats['girls_manual'] or 0
    girls_marked = girls_present + girls_late + girls_excused
    girls_absent = max(0, girls_total - girls_marked)
    girls_rate = round((girls_marked / girls_total * 100), 1) if girls_total > 0 else 0.0

    # Grade distribution breakdown: If specific grade selected, show its section breakdown; else show all grades
    if filter_grade and filter_grade != 'All':
        cursor.execute('''
        SELECT 
            (s.grade || ' - ' || s.section) as grade,
            COUNT(DISTINCT s.student_id) as total,
            COUNT(DISTINCT CASE WHEN a.status IN ('Present', 'Late') THEN a.student_id END) as present,
            COUNT(DISTINCT CASE WHEN a.method = 'Camera-OpenCV' THEN a.student_id END) as camera_count,
            COUNT(DISTINCT CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('male', 'boy', 'm') THEN s.student_id END) as boys_total,
            COUNT(DISTINCT CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('male', 'boy', 'm') AND a.status IN ('Present', 'Late') THEN a.student_id END) as boys_present,
            COUNT(DISTINCT CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('female', 'girl', 'f') THEN s.student_id END) as girls_total,
            COUNT(DISTINCT CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('female', 'girl', 'f') AND a.status IN ('Present', 'Late') THEN a.student_id END) as girls_present
        FROM students s
        LEFT JOIN attendance a ON s.student_id = a.student_id AND a.date = ?
        WHERE s.status = 'Active' AND s.grade = ?
        GROUP BY s.section
        ORDER BY s.section
        ''', (target_date, filter_grade))
    else:
        cursor.execute('''
        SELECT 
            s.grade,
            COUNT(DISTINCT s.student_id) as total,
            COUNT(DISTINCT CASE WHEN a.status IN ('Present', 'Late') THEN a.student_id END) as present,
            COUNT(DISTINCT CASE WHEN a.method = 'Camera-OpenCV' THEN a.student_id END) as camera_count,
            COUNT(DISTINCT CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('male', 'boy', 'm') THEN s.student_id END) as boys_total,
            COUNT(DISTINCT CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('male', 'boy', 'm') AND a.status IN ('Present', 'Late') THEN a.student_id END) as boys_present,
            COUNT(DISTINCT CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('female', 'girl', 'f') THEN s.student_id END) as girls_total,
            COUNT(DISTINCT CASE WHEN LOWER(TRIM(COALESCE(s.gender, ''))) IN ('female', 'girl', 'f') AND a.status IN ('Present', 'Late') THEN a.student_id END) as girls_present
        FROM students s
        LEFT JOIN attendance a ON s.student_id = a.student_id AND a.date = ?
        WHERE s.status = 'Active'
        GROUP BY s.grade
        ORDER BY s.grade
        ''', (target_date,))
    grade_rows = cursor.fetchall()
    grade_distribution = []
    for gr in grade_rows:
        g_total = gr['total'] or 0
        g_present = gr['present'] or 0
        g_absent = max(0, g_total - g_present)
        g_rate = round((g_present / g_total * 100), 1) if g_total > 0 else 0.0

        b_total = gr['boys_total'] or 0
        b_pres = gr['boys_present'] or 0
        b_abs = max(0, b_total - b_pres)
        b_rate = round((b_pres / b_total * 100), 1) if b_total > 0 else 0.0

        g_gtotal = gr['girls_total'] or 0
        g_gpres = gr['girls_present'] or 0
        g_gabs = max(0, g_gtotal - g_gpres)
        g_grate = round((g_gpres / g_gtotal * 100), 1) if g_gtotal > 0 else 0.0

        grade_distribution.append({
            'grade': gr['grade'],
            'total': g_total,
            'present': g_present,
            'absent': g_absent,
            'rate': g_rate,
            'camera_count': gr['camera_count'] or 0,
            'boys_total': b_total,
            'boys_present': b_pres,
            'boys_absent': b_abs,
            'boys_rate': b_rate,
            'girls_total': g_gtotal,
            'girls_present': g_gpres,
            'girls_absent': g_gabs,
            'girls_rate': g_grate
        })

    # Hourly distribution of check-ins (scoped to selected grade if filtered)
    hourly_query = '''
    SELECT 
        strftime('%H', a.time) as hour,
        COUNT(*) as count
    FROM attendance a
    JOIN students s ON a.student_id = s.student_id
    WHERE a.date = ?
    '''
    hourly_params = [target_date]
    if filter_grade and filter_grade != 'All':
        hourly_query += ' AND s.grade = ?'
        hourly_params.append(filter_grade)
    hourly_query += ' GROUP BY hour ORDER BY hour'
    cursor.execute(hourly_query, hourly_params)
    hourly_distribution = [dict(r) for r in cursor.fetchall()]

    # Recent attendance records
    recent_query = '''
    SELECT a.*, s.full_name, s.grade, s.section, s.roll_no, s.photo_path, s.gender,
           COALESCE(s.parent_phone, s.guardian_phone, '') AS parent_phone
    FROM attendance a
    JOIN students s ON a.student_id = s.student_id
    WHERE a.date = ?
    '''
    recent_params = [target_date]
    if filter_grade and filter_grade != 'All':
        recent_query += ' AND s.grade = ?'
        recent_params.append(filter_grade)
    recent_query += ' ORDER BY a.time DESC LIMIT 10'
    cursor.execute(recent_query, recent_params)
    recent_logs = [dict(r) for r in cursor.fetchall()]

    # Earliest & latest check-in times (scoped to selected grade)
    if filter_grade and filter_grade != 'All':
        cursor.execute('''
        SELECT MIN(a.time) as first_time, MAX(a.time) as last_time 
        FROM attendance a
        JOIN students s ON a.student_id = s.student_id
        WHERE a.date = ? AND s.grade = ? AND s.status = 'Active'
        ''', (target_date, filter_grade))
    else:
        cursor.execute('''
        SELECT MIN(a.time) as first_time, MAX(a.time) as last_time 
        FROM attendance a
        JOIN students s ON a.student_id = s.student_id
        WHERE a.date = ? AND s.status = 'Active'
        ''', (target_date,))
    time_row = cursor.fetchone()
    first_checkin = time_row['first_time'] if time_row and time_row['first_time'] else None
    last_checkin = time_row['last_time'] if time_row and time_row['last_time'] else None

    # Unknown detection count (Section 8)
    cursor.execute('''
    SELECT COUNT(*) as unknown_cnt
    FROM recognition_logs
    WHERE date(timestamp) = ? AND result IN ('UNKNOWN', 'LOW CONFIDENCE')
    ''', (target_date,))
    unknown_row = cursor.fetchone()
    unknown_detections = unknown_row['unknown_cnt'] if unknown_row else 0

    conn.close()

    return {
        'total_students': total_students,
        'present_count': present_count,
        'late_count': late_count,
        'excused_count': excused_count,
        'absent_count': absent_count,
        'attendance_rate': rate,
        'camera_count': camera_count,
        'manual_count': manual_count,
        'avg_confidence': avg_confidence,
        'first_checkin': first_checkin,
        'last_checkin': last_checkin,
        'grade_distribution': grade_distribution,
        'hourly_distribution': hourly_distribution,
        'recent_logs': recent_logs,
        'unknown_detections': unknown_detections,
        'unknown_count': unknown_detections,
        'date': target_date,

        # Boys & Girls separated attendance stats
        'boys_total': boys_total,
        'boys_present': boys_present,
        'boys_late': boys_late,
        'boys_excused': boys_excused,
        'boys_marked': boys_marked,
        'boys_absent': boys_absent,
        'boys_rate': boys_rate,
        'boys_camera_count': boys_camera,
        'boys_manual_count': boys_manual,

        'girls_total': girls_total,
        'girls_present': girls_present,
        'girls_late': girls_late,
        'girls_excused': girls_excused,
        'girls_marked': girls_marked,
        'girls_absent': girls_absent,
        'girls_rate': girls_rate,
        'girls_camera_count': girls_camera,
        'girls_manual_count': girls_manual,

        'others_total': others_total
    }

def log_recognition_event(detected_label, confidence, result, camera_id='webcam-1'):
    """Logs facial recognition events for debugging, audit trails, and safety metrics (Section 11)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
        INSERT INTO recognition_logs (detected_label, confidence, result, camera_id)
        VALUES (?, ?, ?, ?)
        ''', (detected_label or 'UNKNOWN', float(confidence or 0.0), result, camera_id))
        conn.commit()
        last_id = cursor.lastrowid
        conn.close()
        return last_id
    except Exception as e:
        print(f"Notice: Failed to log recognition event: {e}")
        conn.close()
        return None

def get_recognition_logs(target_date=None, limit=100):
    """Retrieves recent recognition audit logs for teacher and admin review (Section 11)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if target_date:
        cursor.execute('''
        SELECT id, timestamp, detected_label, confidence, result, camera_id
        FROM recognition_logs
        WHERE date(timestamp) = ?
        ORDER BY id DESC
        LIMIT ?
        ''', (target_date, limit))
    else:
        cursor.execute('''
        SELECT id, timestamp, detected_label, confidence, result, camera_id
        FROM recognition_logs
        ORDER BY id DESC
        LIMIT ?
        ''', (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_unknown_detection_count(target_date=None):
    """Counts unknown face detection events for a given date (Section 8)."""
    if not target_date:
        target_date = date.today().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT COUNT(*) as count
    FROM recognition_logs
    WHERE date(timestamp) = ? AND result IN ('UNKNOWN', 'LOW CONFIDENCE')
    ''', (target_date,))
    row = cursor.fetchone()
    conn.close()
    return row['count'] if row else 0

def insert_face_sample(student_id, image_path, capture_angle='Front', quality_score=100.0):
    """Stores biometric sample metadata in face_samples table (Section 15)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
        INSERT INTO face_samples (student_id, image_path, capture_angle, quality_score)
        VALUES (?, ?, ?, ?)
        ''', (student_id, image_path, capture_angle, float(quality_score)))
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        return new_id
    except Exception as e:
        print(f"Error inserting face sample: {e}")
        conn.close()
        return None

def get_student_face_samples(student_id):
    """Fetches registered biometric samples for a student."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    SELECT * FROM face_samples WHERE student_id = ? ORDER BY id ASC
    ''', (student_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_face_samples_count(student_id=None):
    """Returns count of registered face samples, optionally filtered by student_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if student_id:
        cursor.execute('SELECT COUNT(*) as count FROM face_samples WHERE student_id = ?', (student_id,))
    else:
        cursor.execute('SELECT COUNT(*) as count FROM face_samples')
    row = cursor.fetchone()
    conn.close()
    return row['count'] if row else 0


def get_attendance_reports(start_date=None, end_date=None, grade=None):
    conn = get_db_connection()
    cursor = conn.cursor()

    query = '''
    SELECT a.date, a.time, a.status, a.method, a.confidence,
           s.student_id, s.full_name, s.grade, s.section, s.roll_no, s.gender, s.guardian_phone
    FROM attendance a
    JOIN students s ON a.student_id = s.student_id
    WHERE 1=1
    '''
    params = []
    if start_date:
        query += ' AND a.date >= ?'
        params.append(start_date)
    if end_date:
        query += ' AND a.date <= ?'
        params.append(end_date)
    if grade and grade != 'All':
        query += ' AND s.grade = ?'
        params.append(grade)

    query += ' ORDER BY a.date DESC, a.time DESC'
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def log_whatsapp_message(student_id, parent_phone, student_name='', message='', sent_date=None, status='Sent'):
    if not sent_date:
        sent_date = date.today().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO whatsapp_logs (student_id, student_name, parent_phone, message, status, sent_date)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (student_id, student_name, parent_phone, message, status, sent_date))
    conn.commit()
    log_id = cursor.lastrowid
    conn.close()
    return log_id

def get_whatsapp_logs_by_date(sent_date):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM whatsapp_logs WHERE sent_date = ? ORDER BY created_at DESC', (sent_date,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_sent_whatsapp_student_ids(sent_date):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT student_id FROM whatsapp_logs WHERE sent_date = ?', (sent_date,))
    rows = cursor.fetchall()
    conn.close()
    return set(r['student_id'] for r in rows)

# ----------------- HOLIDAY FUNCTIONS ----------------- #

def get_all_holidays(year=None):
    """Returns all holidays sorted chronologically, optionally filtered by year."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if year:
        cursor.execute("SELECT * FROM holidays WHERE holiday_date LIKE ? ORDER BY holiday_date ASC", (f"{year}-%",))
    else:
        cursor.execute("SELECT * FROM holidays ORDER BY holiday_date ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_holidays_by_month(year, month):
    """Returns holidays for a specific month (e.g. 2026, 10)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    month_pattern = f"{int(year):04d}-{int(month):02d}-%"
    cursor.execute("SELECT * FROM holidays WHERE holiday_date LIKE ? ORDER BY holiday_date ASC", (month_pattern,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_holiday(title, holiday_date, holiday_type="National", description=""):
    """Inserts a new school holiday."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO holidays (title, holiday_date, holiday_type, description)
    VALUES (?, ?, ?, ?)
    ''', (title.strip(), holiday_date.strip(), holiday_type.strip(), description.strip()))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id

def delete_holiday(holiday_id):
    """Deletes a holiday by its ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM holidays WHERE id = ?", (holiday_id,))
    conn.commit()
    conn.close()
    return True

def get_holiday_by_date(date_str):
    """Checks if a given date string (YYYY-MM-DD) is a registered holiday."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM holidays WHERE holiday_date = ?", (date_str,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# ----------------- LOW ATTENDANCE & DEFAULTER TRACKING ----------------- #

def get_low_attendance_students(threshold=75.0, grade='All', section='All', start_date=None, end_date=None):
    """
    Analyzes attendance records and returns a comprehensive list of students
    with their attendance rates, risk classifications, and deficit targets.
    """
    import math
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Determine evaluated working dates
    date_query = "SELECT DISTINCT date FROM attendance WHERE 1=1"
    date_params = []
    if start_date:
        date_query += " AND date >= ?"
        date_params.append(start_date)
    if end_date:
        date_query += " AND date <= ?"
        date_params.append(end_date)
    cursor.execute(date_query, date_params)
    distinct_dates = [r['date'] for r in cursor.fetchall()]
    total_evaluated_days = len(distinct_dates)

    # 2. Query active students
    student_query = "SELECT * FROM students WHERE status = 'Active'"
    student_params = []
    if grade and grade != 'All':
        student_query += " AND grade = ?"
        student_params.append(grade)
    if section and section != 'All':
        student_query += " AND section = ?"
        student_params.append(section)
    student_query += " ORDER BY grade ASC, section ASC, roll_no ASC"
    cursor.execute(student_query, student_params)
    student_rows = [dict(r) for r in cursor.fetchall()]

    # 3. Query all WhatsApp alerts logged today
    today_str = date.today().isoformat()
    cursor.execute(
        "SELECT student_id, message, created_at, status FROM whatsapp_logs WHERE sent_date = ? OR status LIKE '%Low Attendance%'",
        (today_str,)
    )
    wa_logs = cursor.fetchall()
    wa_sent_map = {}
    for w in wa_logs:
        wa_sent_map[w['student_id']] = {
            'logged_at': w['created_at'],
            'status': w['status']
        }

    results = []
    total_percentage_sum = 0.0

    for s in student_rows:
        st_id = s['student_id']

        # Count attendance statuses
        att_query = "SELECT status, COUNT(*) as cnt FROM attendance WHERE student_id = ?"
        att_params = [st_id]
        if start_date:
            att_query += " AND date >= ?"
            att_params.append(start_date)
        if end_date:
            att_query += " AND date <= ?"
            att_params.append(end_date)
        att_query += " GROUP BY status"
        cursor.execute(att_query, att_params)
        counts = {r['status']: r['cnt'] for r in cursor.fetchall()}

        present_days = counts.get('Present', 0) + counts.get('Late', 0)
        absent_days = counts.get('Absent', 0)

        # If there are total dates recorded, unrecorded days also count as absences
        if total_evaluated_days > 0:
            total_absences = max(absent_days, total_evaluated_days - present_days)
            percentage = round((present_days / total_evaluated_days) * 100.0, 1)
        else:
            total_absences = 0
            percentage = 100.0

        total_percentage_sum += percentage

        # Calculate consecutive days needed to reach threshold
        is_defaulter = percentage < float(threshold)
        classes_needed = 0
        if is_defaulter and total_evaluated_days > 0:
            t_frac = float(threshold) / 100.0
            if t_frac < 1.0:
                needed = math.ceil((t_frac * total_evaluated_days - present_days) / (1.0 - t_frac))
                classes_needed = max(1, int(needed))

        # Risk level classification
        if percentage < 50.0:
            risk_level = 'Critical'
            risk_color = '#ef4444'
            risk_bg = '#fef2f2'
            risk_border = '#fca5a5'
        elif percentage < 65.0:
            risk_level = 'High Risk'
            risk_color = '#f97316'
            risk_bg = '#fff7ed'
            risk_border = '#fed7aa'
        elif percentage < float(threshold):
            risk_level = 'Warning'
            risk_color = '#eab308'
            risk_bg = '#fefce8'
            risk_border = '#fef08a'
        else:
            risk_level = 'Safe'
            risk_color = '#10b981'
            risk_bg = '#f0fdf4'
            risk_border = '#bbf7d0'

        phone_num = s.get('parent_phone') or s.get('guardian_phone') or ''
        sent_info = wa_sent_map.get(st_id)

        item = {
            'student_id': s['student_id'],
            'full_name': s['full_name'],
            'roll_no': s.get('roll_no', '--'),
            'grade': s.get('grade', '--'),
            'section': s.get('section', '--'),
            'gender': s.get('gender', 'Other'),
            'guardian_name': s.get('guardian_name', 'Parent/Guardian'),
            'guardian_phone': s.get('guardian_phone', ''),
            'parent_phone': s.get('parent_phone', ''),
            'effective_phone': phone_num,
            'photo_path': s.get('photo_path', ''),
            'total_days': total_evaluated_days,
            'present_days': present_days,
            'absent_days': total_absences,
            'percentage': percentage,
            'is_defaulter': is_defaulter,
            'classes_needed': classes_needed,
            'risk_level': risk_level,
            'risk_color': risk_color,
            'risk_bg': risk_bg,
            'risk_border': risk_border,
            'whatsapp_sent': (sent_info is not None),
            'whatsapp_sent_at': sent_info['logged_at'] if sent_info else None
        }
        results.append(item)

    conn.close()

    # Sort students: lowest attendance percentage first (defaulters at the top)
    results.sort(key=lambda x: (x['percentage'], x['full_name']))

    total_students = len(results)
    defaulters_count = sum(1 for r in results if r['is_defaulter'])
    critical_count = sum(1 for r in results if r['risk_level'] == 'Critical')
    high_risk_count = sum(1 for r in results if r['risk_level'] == 'High Risk')
    warning_count = sum(1 for r in results if r['risk_level'] == 'Warning')
    safe_count = sum(1 for r in results if r['risk_level'] == 'Safe')
    avg_attendance = round(total_percentage_sum / total_students, 1) if total_students > 0 else 0.0

    summary = {
        'total_students': total_students,
        'defaulters_count': defaulters_count,
        'critical_count': critical_count,
        'high_risk_count': high_risk_count,
        'warning_count': warning_count,
        'safe_count': safe_count,
        'avg_attendance': avg_attendance,
        'threshold': float(threshold),
        'total_school_days': total_evaluated_days
    }

    return results, summary

# ----------------- EXAMINATION RESULTS & RANKING FUNCTIONS ----------------- #

def insert_exam_result(student_name, roll_no, subject, marks_obtained, max_marks=100.0, rank=0, exam_term='Annual Exam 2026', student_id=None, exam_date=None, grade='', remarks='', class_grade=''):
    conn = get_db_connection()
    cursor = conn.cursor()
    if not exam_date:
        exam_date = date.today().isoformat()
    if not grade:
        pct = (float(marks_obtained) / float(max_marks or 100.0)) * 100
        if pct >= 90: grade = 'A+'
        elif pct >= 80: grade = 'A'
        elif pct >= 70: grade = 'B'
        elif pct >= 60: grade = 'C'
        elif pct >= 50: grade = 'D'
        else: grade = 'F'

    cursor.execute('''
    INSERT INTO exam_results (student_id, student_name, roll_no, class_grade, subject, marks_obtained, max_marks, rank, exam_term, grade, remarks, exam_date)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (student_id or '', student_name, str(roll_no), class_grade or '', float(marks_obtained), float(max_marks or 100.0), int(rank or 0), exam_term, grade, remarks, exam_date))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id

def bulk_insert_exam_results(records_list):
    """
    Bulk inserts a list of parsed result dicts into exam_results.
    Each dict should have: student_name, roll_no, class_grade, subject, marks_obtained, max_marks, rank, exam_term, grade, remarks.
    """
    if not records_list:
        return 0

    conn = get_db_connection()
    cursor = conn.cursor()
    today_str = date.today().isoformat()

    tuples = []
    for r in records_list:
        marks = float(r.get('marks_obtained', 0.0))
        max_m = float(r.get('max_marks', 100.0) or 100.0)
        grade = r.get('grade', '')
        if not grade:
            pct = (marks / max_m) * 100 if max_m > 0 else 0
            if pct >= 90: grade = 'A+'
            elif pct >= 80: grade = 'A'
            elif pct >= 70: grade = 'B'
            elif pct >= 60: grade = 'C'
            elif pct >= 50: grade = 'D'
            else: grade = 'F'

        tuples.append((
            r.get('student_id') or '',
            r.get('student_name', 'Student').strip(),
            str(r.get('roll_no', '')).strip(),
            r.get('class_grade') or r.get('student_grade') or '',
            r.get('subject', 'General').strip(),
            marks,
            max_m,
            int(r.get('rank', 0)),
            r.get('exam_term', 'Annual Exam 2026').strip(),
            grade,
            r.get('remarks', ''),
            r.get('exam_date') or today_str
        ))

    cursor.executemany('''
    INSERT INTO exam_results (student_id, student_name, roll_no, class_grade, subject, marks_obtained, max_marks, rank, exam_term, grade, remarks, exam_date)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', tuples)
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count

def get_exam_results(exam_term=None, subject=None, search=None, sort_by='rank', grade=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = '''
        SELECT r.*,
               COALESCE(NULLIF(r.class_grade, ''), s.grade, '') as display_grade,
               COALESCE(s.photo_path, '') as student_photo,
               COALESCE(s.grade, '') as student_grade,
               COALESCE(s.section, '') as student_section
        FROM exam_results r
        LEFT JOIN students s ON (
            r.student_id = s.student_id
            OR (
                r.roll_no = s.roll_no
                AND (r.class_grade = '' OR r.class_grade = s.grade OR r.class_grade IS NULL)
                AND r.student_id = ''
            )
        )
        WHERE 1=1
    '''
    params = []
    if grade and grade != 'All':
        query += " AND COALESCE(NULLIF(r.class_grade, ''), s.grade, '') = ?"
        params.append(grade)
    if exam_term and exam_term != 'All':
        query += ' AND r.exam_term = ?'
        params.append(exam_term)
    if subject and subject != 'All':
        query += ' AND r.subject = ?'
        params.append(subject)
    if search:
        query += ' AND (r.student_name LIKE ? OR r.roll_no LIKE ? OR r.subject LIKE ?)'
        wildcard = f'%{search}%'
        params.extend([wildcard, wildcard, wildcard])

    if sort_by == 'rank':
        query += ' ORDER BY COALESCE(NULLIF(r.class_grade, ""), s.grade, "") ASC, r.exam_term ASC, r.subject ASC, r.rank ASC, r.marks_obtained DESC'
    elif sort_by == 'name':
        query += ' ORDER BY r.student_name ASC'
    elif sort_by == 'roll':
        query += ' ORDER BY CAST(r.roll_no AS INTEGER) ASC, r.roll_no ASC'
    else:
        query += ' ORDER BY r.rank ASC'

    cursor.execute(query, params)
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results

def delete_exam_result(result_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM exam_results WHERE id = ?', (result_id,))
    conn.commit()
    conn.close()

def clear_exam_results(exam_term=None, subject=None, grade=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if grade and grade != 'All':
        query = '''
            DELETE FROM exam_results 
            WHERE id IN (
                SELECT r.id 
                FROM exam_results r 
                LEFT JOIN students s ON (r.student_id = s.student_id OR r.roll_no = s.roll_no)
                WHERE COALESCE(NULLIF(r.class_grade, ''), s.grade, '') = ?
        '''
        params = [grade]
        if exam_term and exam_term != 'All':
            query += ' AND r.exam_term = ?'
            params.append(exam_term)
        if subject and subject != 'All':
            query += ' AND r.subject = ?'
            params.append(subject)
        query += ')'
        cursor.execute(query, params)
    elif exam_term and subject and exam_term != 'All' and subject != 'All':
        cursor.execute('DELETE FROM exam_results WHERE exam_term = ? AND subject = ?', (exam_term, subject))
    elif exam_term and exam_term != 'All':
        cursor.execute('DELETE FROM exam_results WHERE exam_term = ?', (exam_term,))
    else:
        cursor.execute('DELETE FROM exam_results')
    conn.commit()
    conn.close()

def get_exam_terms_and_subjects(grade=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    where = "WHERE 1=1"
    params = []
    if grade and grade != 'All':
        where += " AND COALESCE(NULLIF(r.class_grade, ''), s.grade, '') = ?"
        params.append(grade)

    cursor.execute(f'''
        SELECT DISTINCT r.exam_term 
        FROM exam_results r
        LEFT JOIN students s ON (r.student_id = s.student_id OR r.roll_no = s.roll_no)
        {where}
        ORDER BY r.exam_term
    ''', params)
    terms = [r[0] for r in cursor.fetchall() if r[0]]

    cursor.execute(f'''
        SELECT DISTINCT r.subject 
        FROM exam_results r
        LEFT JOIN students s ON (r.student_id = s.student_id OR r.roll_no = s.roll_no)
        {where}
        ORDER BY r.subject
    ''', params)
    subjects = [r[0] for r in cursor.fetchall() if r[0]]
    conn.close()
    return terms, subjects

def get_exam_summary_stats(exam_term=None, subject=None, grade=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = '''
        SELECT r.marks_obtained, r.max_marks, r.rank, r.student_name 
        FROM exam_results r
        LEFT JOIN students s ON (r.student_id = s.student_id OR r.roll_no = s.roll_no)
        WHERE 1=1
    '''
    params = []
    if grade and grade != 'All':
        query += " AND COALESCE(NULLIF(r.class_grade, ''), s.grade, '') = ?"
        params.append(grade)
    if exam_term and exam_term != 'All':
        query += ' AND r.exam_term = ?'
        params.append(exam_term)
    if subject and subject != 'All':
        query += ' AND r.subject = ?'
        params.append(subject)

    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not rows:
        return {
            'total_students': 0,
            'topper_name': 'N/A',
            'topper_marks': 0,
            'avg_marks': 0.0,
            'pass_rate': 0.0,
            'highest_marks': 0,
            'lowest_marks': 0
        }

    total = len(rows)
    marks = [r['marks_obtained'] for r in rows]
    highest = max(marks)
    lowest = min(marks)
    avg_marks = round(sum(marks) / total, 1)

    # Passing (>= 35% or >= 35 marks)
    passing_count = sum(1 for r in rows if (r['marks_obtained'] / (r['max_marks'] or 100.0)) >= 0.35)
    pass_rate = round((passing_count / total) * 100, 1)

    topper = next((r['student_name'] for r in rows if r['marks_obtained'] == highest), 'N/A')

    return {
        'total_students': total,
        'topper_name': topper,
        'topper_marks': highest,
        'avg_marks': avg_marks,
        'pass_rate': pass_rate,
        'highest_marks': highest,
        'lowest_marks': lowest
    }

def get_all_result_grades():
    """Returns all available distinct class grades across students and exam results."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT COALESCE(NULLIF(r.class_grade, ''), s.grade, '') as g
        FROM exam_results r
        LEFT JOIN students s ON (r.student_id = s.student_id OR r.roll_no = s.roll_no)
        WHERE g != ''
        UNION
        SELECT DISTINCT grade as g FROM students WHERE grade != ''
        ORDER BY g
    ''')
    grades = [r[0] for r in cursor.fetchall() if r[0]]
    conn.close()
    default_grades = ['Grade 8', 'Grade 9', 'Grade 10', 'Grade 11', 'Grade 12']
    merged = sorted(list(set(grades + default_grades)), key=lambda x: [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', x)])
    return merged


# =========================================================================
# PARENT PORTAL HELPER FUNCTIONS
# =========================================================================

def verify_parent_login(student_identifier, phone_or_dob):
    """
    Verifies credentials for Parent Portal login.
    student_identifier: Student ID (e.g. STU-1001) or Roll Number (e.g. 1)
    phone_or_dob: Parent/Guardian phone number or student Date of Birth (YYYY-MM-DD)
    """
    if not student_identifier or not phone_or_dob:
        return None
        
    s_ident = str(student_identifier).strip().upper()
    phone_raw = str(phone_or_dob).strip()
    digits_only = re.sub(r'\D', '', phone_raw)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT s.*,
               COALESCE((SELECT COUNT(*) FROM face_samples fs WHERE fs.student_id = s.student_id), 0) AS db_samples_count
        FROM students s
        WHERE s.status = 'Active' AND (UPPER(s.student_id) = ? OR s.roll_no = ?)
    ''', (s_ident, str(student_identifier).strip()))
    candidates = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    for stu in candidates:
        # Check Date of Birth match (exact or substring)
        stu_dob = (stu.get('dob') or '').strip().lower()
        if stu_dob and (phone_raw.lower() == stu_dob or phone_raw.lower() in stu_dob):
            return stu
            
        # Check Phone match across parent_phone and guardian_phone
        for p_field in ['parent_phone', 'guardian_phone']:
            val = (stu.get(p_field) or '').strip()
            p_digits = re.sub(r'\D', '', val)
            if digits_only and p_digits:
                # Match full or last 7-10 digits (handling country codes)
                if digits_only == p_digits or digits_only in p_digits or p_digits.endswith(digits_only) or digits_only.endswith(p_digits):
                    return stu
            elif val and phone_raw == val:
                return stu
                
    return None

def get_student_parent_info(student_id):
    """Returns student profile details and parent contact information."""
    return get_student_by_id(student_id)

def get_student_attendance_summary(student_id):
    """
    Calculates overall attendance metrics and today's status for a specific student.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(DISTINCT date) FROM attendance')
    total_school_days = cursor.fetchone()[0] or 0
    if total_school_days == 0:
        total_school_days = 1
        
    cursor.execute('''
        SELECT 
            COUNT(CASE WHEN status IN ('Present', 'Late') THEN 1 END) as present_count,
            COUNT(CASE WHEN status = 'Late' THEN 1 END) as late_count,
            COUNT(CASE WHEN status = 'Absent' THEN 1 END) as absent_marked,
            COUNT(CASE WHEN status = 'Excused' THEN 1 END) as excused_count
        FROM attendance
        WHERE student_id = ?
    ''', (student_id,))
    row = cursor.fetchone()
    present_days = row['present_count'] or 0
    late_days = row['late_count'] or 0
    excused_days = row['excused_count'] or 0
    
    cursor.execute('SELECT COUNT(DISTINCT date) FROM attendance WHERE student_id = ?', (student_id,))
    student_total_logged = cursor.fetchone()[0] or 0
    
    working_days = max(total_school_days, student_total_logged, 1)
    absent_days = max(0, working_days - present_days - excused_days)
    attendance_rate = round((present_days / working_days) * 100, 1)
    
    # Today's attendance record
    today_iso = date.today().isoformat()
    cursor.execute('SELECT * FROM attendance WHERE student_id = ? AND date = ?', (student_id, today_iso))
    today_rec = cursor.fetchone()
    today_dict = dict(today_rec) if today_rec else None
    
    # Check if today is a school holiday
    cursor.execute('SELECT * FROM holidays WHERE holiday_date = ?', (today_iso,))
    today_holiday = cursor.fetchone()
    today_holiday_dict = dict(today_holiday) if today_holiday else None
    
    conn.close()
    
    return {
        'total_working_days': working_days,
        'present_days': present_days,
        'absent_days': absent_days,
        'late_days': late_days,
        'excused_days': excused_days,
        'attendance_rate': attendance_rate,
        'today_attendance': today_dict,
        'today_holiday': today_holiday_dict
    }

def get_student_monthly_calendar(student_id, year=None, month=None):
    """
    Generates a full monthly calendar grid with daily attendance status, holidays, and weekends.
    """
    import calendar
    today = date.today()
    try:
        year = int(year) if year else today.year
        month = int(month) if month else today.month
        if month < 1 or month > 12:
            month = today.month
        if year < 2000 or year > 2100:
            year = today.year
    except (ValueError, TypeError):
        year = today.year
        month = today.month

    month_name = calendar.month_name[month]
    first_weekday, num_days = calendar.monthrange(year, month)
    # Convert Monday=0 to Sunday=0 convention
    sunday_first_start = (first_weekday + 1) % 7

    start_date = f"{year:04d}-{month:02d}-01"
    end_date = f"{year:04d}-{month:02d}-{num_days:02d}"

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT date, time, status, method, confidence, notes
        FROM attendance
        WHERE student_id = ? AND date BETWEEN ? AND ?
    ''', (student_id, start_date, end_date))
    att_by_date = {r['date']: dict(r) for r in cursor.fetchall()}

    cursor.execute('''
        SELECT holiday_date, title, holiday_type, description
        FROM holidays
        WHERE holiday_date BETWEEN ? AND ?
    ''', (start_date, end_date))
    holidays_by_date = {r['holiday_date']: dict(r) for r in cursor.fetchall()}

    conn.close()

    days = []
    
    # Previous month padding for standard 7-day grid alignment
    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12
    _, prev_num_days = calendar.monthrange(prev_year, prev_month)
    for pad_day in range(prev_num_days - sunday_first_start + 1, prev_num_days + 1):
        pad_date = f"{prev_year:04d}-{prev_month:02d}-{pad_day:02d}"
        days.append({
            'day': pad_day,
            'date': pad_date,
            'is_current_month': False,
            'status': 'other_month'
        })

    month_present = 0
    month_absent = 0
    month_late = 0
    month_holidays = 0

    for day in range(1, num_days + 1):
        day_date_str = f"{year:04d}-{month:02d}-{day:02d}"
        day_date = date(year, month, day)
        is_today = (day_date == today)
        is_future = (day_date > today)
        is_sunday = (day_date.weekday() == 6)

        holiday_info = holidays_by_date.get(day_date_str)
        att_info = att_by_date.get(day_date_str)

        if is_future:
            status = 'future'
        elif holiday_info:
            status = 'holiday'
            month_holidays += 1
        elif is_sunday:
            status = 'weekend'
        elif att_info:
            raw_status = att_info.get('status', 'Present').lower()
            if 'late' in raw_status:
                status = 'late'
                month_late += 1
                month_present += 1
            elif 'present' in raw_status:
                status = 'present'
                month_present += 1
            else:
                status = 'absent'
                month_absent += 1
        else:
            status = 'absent'
            month_absent += 1

        days.append({
            'day': day,
            'date': day_date_str,
            'is_current_month': True,
            'is_today': is_today,
            'is_future': is_future,
            'is_sunday': is_sunday,
            'status': status,
            'attendance': att_info,
            'holiday': holiday_info
        })

    # Next month padding to round off full weeks
    total_cells = len(days)
    next_pad_needed = (7 - (total_cells % 7)) % 7
    next_year = year if month < 12 else year + 1
    next_month = month + 1 if month < 12 else 1
    for pad_day in range(1, next_pad_needed + 1):
        pad_date = f"{next_year:04d}-{next_month:02d}-{pad_day:02d}"
        days.append({
            'day': pad_day,
            'date': pad_date,
            'is_current_month': False,
            'status': 'other_month'
        })

    weeks = [days[i:i + 7] for i in range(0, len(days), 7)]

    month_school_days = month_present + month_absent
    month_rate = round((month_present / month_school_days * 100), 1) if month_school_days > 0 else 100.0

    return {
        'year': year,
        'month': month,
        'month_name': month_name,
        'weeks': weeks,
        'month_present': month_present,
        'month_absent': month_absent,
        'month_late': month_late,
        'month_holidays': month_holidays,
        'month_rate': month_rate,
        'prev_year': prev_year,
        'prev_month': prev_month,
        'next_year': next_year,
        'next_month': next_month
    }

def get_student_attendance_history(student_id, limit=60):
    """Returns chronological attendance records for a specific student."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT a.*, 
               strftime('%w', a.date) as day_of_week
        FROM attendance a
        WHERE a.student_id = ?
        ORDER BY a.date DESC, a.time DESC
        LIMIT ?
    ''', (student_id, limit))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    weekday_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    for r in rows:
        try:
            dow = int(r.get('day_of_week', 0))
            r['weekday_name'] = weekday_names[dow]
        except (ValueError, TypeError):
            r['weekday_name'] = ""
    return rows

def submit_parent_leave(student_id, leave_type, start_date, end_date, reason):
    """Submits a student absence / leave application from a parent."""
    if not student_id or not leave_type or not start_date or not reason:
        return False, "Please fill all required leave application fields."
    if not end_date:
        end_date = start_date
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO parent_leaves (student_id, leave_type, start_date, end_date, reason, status)
            VALUES (?, ?, ?, ?, ?, 'Submitted')
        ''', (student_id, leave_type, start_date, end_date, reason))
        conn.commit()
        conn.close()
        return True, "Leave application submitted successfully. School authorities have been notified."
    except Exception as e:
        conn.close()
        return False, str(e)

def get_parent_leaves(student_id):
    """Retrieves leave applications submitted for this student."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM parent_leaves
        WHERE student_id = ?
        ORDER BY id DESC
    ''', (student_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_student_exam_results(student_id):
    """Retrieves examination results and rank for a specific student."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT r.*
        FROM exam_results r
        LEFT JOIN students s ON (r.student_id = s.student_id OR r.roll_no = s.roll_no)
        WHERE r.student_id = ? OR s.student_id = ?
        ORDER BY r.id DESC
    ''', (student_id, student_id))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_student_whatsapp_alerts(student_id):
    """Retrieves automated WhatsApp alerts dispatched to this student's parent."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM whatsapp_logs
        WHERE student_id = ?
        ORDER BY id DESC
        LIMIT 10
    ''', (student_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_sample_parents_for_demo():
    """Returns sample students for one-click demo login on the welcome page."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT student_id, full_name, grade, section, roll_no, 
               COALESCE(NULLIF(parent_phone, ''), guardian_phone, '9054620347') as phone,
               COALESCE(NULLIF(guardian_name, ''), 'Guardian') as guardian_name,
               photo_path, dob
        FROM students
        WHERE status = 'Active'
        ORDER BY id ASC
        LIMIT 4
    ''')
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows



