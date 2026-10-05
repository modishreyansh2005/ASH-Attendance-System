import os
import io
import csv
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, Response, make_response, session
from werkzeug.utils import secure_filename
import cv2
import numpy as np

from database import (
    init_db, get_all_students, get_student_by_id, insert_student,
    update_student, delete_student, reorder_all_students, record_attendance,
    update_attendance_status, get_today_attendance,
    get_dashboard_stats, get_attendance_reports, get_db_connection,
    log_whatsapp_message, get_whatsapp_logs_by_date, get_sent_whatsapp_student_ids,
    get_today_marked_student_ids,
    get_all_holidays, get_holidays_by_month, add_holiday, delete_holiday, get_holiday_by_date,
    get_low_attendance_students,
    log_recognition_event, get_recognition_logs, get_unknown_detection_count,
    get_student_face_samples, get_face_samples_count,
    get_exam_results, bulk_insert_exam_results, delete_exam_result,
    clear_exam_results, get_exam_terms_and_subjects, get_exam_summary_stats,
    get_all_result_grades,
    verify_parent_login, get_student_parent_info, get_student_attendance_summary,
    get_student_monthly_calendar, get_student_attendance_history,
    get_student_exam_results,
    get_sample_parents_for_demo
)
from result_parser import parse_result_file, generate_sample_excel_template
import calendar
import re
import urllib.parse
from face_engine import (
    base64_to_cv2, cv2_to_base64, detect_faces,
    save_student_face_samples, train_face_recognizer,
    analyze_frame_faces, reload_recognizer, TRAINER_PATH,
    robust_decode_image, validate_face_quality, preprocess_face_crop
)

app = Flask(__name__)
app.secret_key = 'ash-edu-smart-attendance-system-key-2026'

# Ensure database and folders exist
init_db()

def get_student_maps():
    """Returns mapping of student_id -> db_id and db_id -> student dict."""
    students = get_all_students()
    s_to_db = {}
    db_to_stu = {}
    for s in students:
        s_to_db[s['student_id']] = s['id']
        db_to_stu[s['id']] = s
    return s_to_db, db_to_stu

# Initial training check on app boot
s_to_db, _ = get_student_maps()
if os.path.exists('static/dataset') and len(os.listdir('static/dataset')) > 0:
    train_face_recognizer(s_to_db)

# ----------------- PAGE ROUTES ----------------- #

@app.context_processor
def inject_global_grade():
    active_grade = session.get('selected_grade', 'All')
    all_students = get_all_students()
    all_grades = sorted(list(set(s['grade'] for s in all_students if s.get('grade'))))
    return {
        'active_grade': active_grade,
        'all_campus_grades': all_grades
    }

@app.route('/set-grade/<path:grade_name>')
def set_active_grade(grade_name):
    """Allows user to switch the active class from anywhere in the application."""
    session['selected_grade'] = grade_name
    ref = request.referrer or url_for('dashboard', grade=grade_name)
    try:
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        u = urlparse(ref)
        qs = parse_qs(u.query)
        qs['grade'] = [grade_name]
        new_query = urlencode(qs, doseq=True)
        ref = urlunparse((u.scheme, u.netloc, u.path, u.params, new_query, u.fragment))
    except Exception:
        pass
    return redirect(ref)

@app.route('/')
def welcome():
    all_students = get_all_students()
    grades_count = {}
    for s in all_students:
        g = s['grade']
        grades_count[g] = grades_count.get(g, 0) + 1

    grade_options = [
        {"id": "All", "name": "All Classes", "desc": "Campus-wide Master Overview", "count": len(all_students)},
        {"id": "Grade 8", "name": "Grade 8", "desc": "Middle School Division", "count": grades_count.get("Grade 8", 0)},
        {"id": "Grade 9", "name": "Grade 9", "desc": "Secondary School Division", "count": grades_count.get("Grade 9", 0)},
        {"id": "Grade 10", "name": "Grade 10", "desc": "Board Examination Division", "count": grades_count.get("Grade 10", 0)},
        {"id": "Grade 11", "name": "Grade 11", "desc": "Senior Secondary Division", "count": grades_count.get("Grade 11", 0)},
        {"id": "Grade 12", "name": "Grade 12", "desc": "Graduating Batch Division", "count": grades_count.get("Grade 12", 0)}
    ]
    return render_template(
        'welcome.html',
        grade_options=grade_options,
        total_students=len(all_students),
        today=date.today().strftime('%A, %d %B %Y')
    )

@app.route('/dashboard')
def dashboard():
    selected_date = request.args.get('date', date.today().isoformat())
    selected_grade = request.args.get('grade', session.get('selected_grade', 'All'))
    session['selected_grade'] = selected_grade

    stats = get_dashboard_stats(selected_date, filter_grade=selected_grade)
    filter_grade = selected_grade if selected_grade != 'All' else None
    students_in_grade = get_all_students(filter_grade=filter_grade)
    all_students = get_all_students()

    all_grades = sorted(list(set(s['grade'] for s in all_students if s.get('grade'))))
    grade_counts = {}
    for s in all_students:
        g = s.get('grade')
        if g:
            grade_counts[g] = grade_counts.get(g, 0) + 1

    return render_template(
        'index.html',
        stats=stats,
        selected_date=selected_date,
        selected_grade=selected_grade,
        total_enrolled=len(students_in_grade),
        all_grades=all_grades,
        grade_counts=grade_counts,
        total_all_students=len(all_students)
    )

# ----------------- PARENT PORTAL ROUTES ----------------- #

@app.route('/parents')
@app.route('/parents/')
def parents_portal():
    """
    Entry point for the Parents Portal.
    If already logged in, redirects directly to the Parent Dashboard.
    If not logged in, opens the Welcome & Login page.
    """
    parent_sid = session.get('parent_student_id')
    if parent_sid:
        return redirect(url_for('parents_dashboard'))
    
    demo_students = get_sample_parents_for_demo()
    return render_template(
        'parents_login.html',
        demo_students=demo_students,
        today=date.today().strftime('%A, %d %B %Y')
    )

@app.route('/parents/login', methods=['GET', 'POST'])
def parents_login():
    """Authenticates parent using Student ID / Roll No and Parent Mobile or DOB."""
    if request.method == 'GET':
        return redirect(url_for('parents_portal'))
        
    student_id = request.form.get('student_id', '').strip()
    phone_or_dob = request.form.get('phone_or_dob', '').strip()
    
    if not student_id or not phone_or_dob:
        flash("Please enter both Student ID / Roll Number and Registered Parent Mobile Number or Date of Birth.", "danger")
        return redirect(url_for('parents_portal'))
        
    student = verify_parent_login(student_id, phone_or_dob)
    if not student:
        flash("Authentication failed. No active student record matches the provided Student ID / Roll Number and Parent Mobile Number / DOB. Please verify and try again.", "danger")
        return redirect(url_for('parents_portal'))
        
    session['parent_student_id'] = student['student_id']
    session['parent_student_name'] = student['full_name']
    flash(f"Welcome to the Parent Portal! Viewing attendance and academic records for {student['full_name']}.", "success")
    return redirect(url_for('parents_dashboard'))

@app.route('/parents/quick-login/<student_id>')
def parents_quick_login(student_id):
    """Allows one-click demo login for authorized active students."""
    student = get_student_by_id(student_id)
    if not student:
        flash("Student profile not found.", "danger")
        return redirect(url_for('parents_portal'))
        
    session['parent_student_id'] = student['student_id']
    session['parent_student_name'] = student['full_name']
    flash(f"Logged in as parent of {student['full_name']} (Grade {student.get('grade', '')}-{student.get('section', '')}).", "success")
    return redirect(url_for('parents_dashboard'))

@app.route('/parents/logout')
def parents_logout():
    """Signs out parent from session and returns to login welcome page."""
    session.pop('parent_student_id', None)
    session.pop('parent_student_name', None)
    flash("You have been signed out of the Parent Portal.", "info")
    return redirect(url_for('parents_portal'))

@app.route('/parents/dashboard')
def parents_dashboard():
    """
    Main Parent Dashboard:
    Features student profile, today's live biometric status, attendance stats,
    interactive monthly calendar with holidays, daily register logs, and examination results & ranks.
    """
    parent_sid = session.get('parent_student_id')
    if not parent_sid:
        flash("Please log in to access the Parent Dashboard.", "warning")
        return redirect(url_for('parents_portal'))
        
    student = get_student_parent_info(parent_sid)
    if not student:
        session.pop('parent_student_id', None)
        flash("Student profile not found or inactive. Please contact school administration.", "danger")
        return redirect(url_for('parents_portal'))

    # Monthly calendar parameters
    year_param = request.args.get('year')
    month_param = request.args.get('month')
    today_dt = date.today()
    try:
        cal_year = int(year_param) if year_param else today_dt.year
        cal_month = int(month_param) if month_param else today_dt.month
    except (ValueError, TypeError):
        cal_year = today_dt.year
        cal_month = today_dt.month
        
    summary = get_student_attendance_summary(parent_sid)
    calendar_data = get_student_monthly_calendar(parent_sid, cal_year, cal_month)
    history_logs = get_student_attendance_history(parent_sid, limit=45)
    exam_results = get_student_exam_results(parent_sid)
    holidays = get_all_holidays()

    # Grade-wise result filtering parameters:
    # Default to the logged-in student's grade (e.g. 'Grade 12')
    student_grade = student.get('grade') or 'Grade 12'
    selected_grade = request.args.get('grade')
    if not selected_grade:
        selected_grade = student_grade

    selected_term = request.args.get('term', 'All')
    selected_subject = request.args.get('subject', 'All')
    res_search = request.args.get('res_search', '').strip()

    filter_grade = selected_grade if selected_grade != 'All' else None
    filter_term = selected_term if selected_term and selected_term != 'All' else None
    filter_subject = selected_subject if selected_subject and selected_subject != 'All' else None

    # All available grades in school system
    all_result_grades = get_all_result_grades()

    # Examination terms & subjects available for this grade
    exam_terms, exam_subjects = get_exam_terms_and_subjects(grade=filter_grade)

    # All grade results (e.g. Grade 12 results) sorted by rank
    grade_exam_results = get_exam_results(
        exam_term=filter_term,
        subject=filter_subject,
        search=res_search if res_search else None,
        sort_by='rank',
        grade=filter_grade
    )

    # Summary performance stats for the selected grade
    grade_stats = get_exam_summary_stats(
        exam_term=filter_term,
        subject=filter_subject,
        grade=filter_grade
    )

    # Mark whether each record belongs to the current student
    curr_sid = (student.get('student_id') or '').strip().lower()
    curr_roll = str(student.get('roll_no') or '').strip().lower()
    curr_name = (student.get('full_name') or '').strip().lower()

    for r in grade_exam_results:
        is_my_child = False
        r_sid = (r.get('student_id') or '').strip().lower()
        r_roll = str(r.get('roll_no') or '').strip().lower()
        r_name = (r.get('student_name') or '').strip().lower()

        if r_sid and r_sid == curr_sid:
            is_my_child = True
        elif curr_roll and r_roll == curr_roll and (r.get('class_grade') == student.get('grade') or r.get('student_grade') == student.get('grade')):
            is_my_child = True
        elif curr_name and r_name == curr_name:
            is_my_child = True

        r['is_my_child'] = is_my_child

    # If individual exam_results was empty, check if we found any for child in grade_exam_results
    if not exam_results:
        matched_child_results = [r for r in grade_exam_results if r.get('is_my_child')]
        if matched_child_results:
            exam_results = matched_child_results

    # Calculate exam average marks if results exist
    exam_avg = 0.0
    if exam_results:
        marks = [r['marks_obtained'] for r in exam_results if r.get('marks_obtained') is not None]
        if marks:
            exam_avg = round(sum(marks) / len(marks), 1)

    # Pagination: exactly 10 students per page for parent result table
    res_per_page = 10
    total_result_records = len(grade_exam_results)
    total_result_pages = max(1, (total_result_records + res_per_page - 1) // res_per_page)

    try:
        res_current_page = int(request.args.get('page', 1))
        if res_current_page < 1:
            res_current_page = 1
        elif res_current_page > total_result_pages:
            res_current_page = total_result_pages
    except (ValueError, TypeError):
        res_current_page = 1

    res_start_index = (res_current_page - 1) * res_per_page
    res_end_index = min(res_start_index + res_per_page, total_result_records)
    paginated_grade_results = grade_exam_results[res_start_index:res_end_index] if total_result_records > 0 else []

    res_start_record = (res_start_index + 1) if total_result_records > 0 else 0
    res_end_record = res_end_index
    res_page_range = get_pagination_window(res_current_page, total_result_pages)

    res_has_prev = res_current_page > 1
    res_has_next = res_current_page < total_result_pages
    res_prev_page = res_current_page - 1
    res_next_page = res_current_page + 1

    # Requested active tab handling:
    # If user accessed via ?page= or ?grade= or tab=results, stay on results tab
    requested_tab = request.args.get('tab')
    if not requested_tab:
        if request.args.get('page') or request.args.get('grade'):
            active_tab = 'results'
        else:
            active_tab = 'calendar'
    else:
        active_tab = requested_tab

    return render_template(
        'parents_dashboard.html',
        student=student,
        summary=summary,
        calendar=calendar_data,
        history_logs=history_logs,
        exam_results=exam_results,
        child_exam_results=exam_results,
        exam_avg=exam_avg,
        grade_exam_results=paginated_grade_results,
        all_grade_results_count=total_result_records,
        res_current_page=res_current_page,
        res_total_pages=total_result_pages,
        res_has_prev=res_has_prev,
        res_has_next=res_has_next,
        res_prev_page=res_prev_page,
        res_next_page=res_next_page,
        res_start_record=res_start_record,
        res_end_record=res_end_record,
        res_page_range=res_page_range,
        grade_stats=grade_stats,
        all_result_grades=all_result_grades,
        exam_terms=exam_terms,
        exam_subjects=exam_subjects,
        selected_grade=selected_grade,
        selected_term=selected_term,
        selected_subject=selected_subject,
        res_search=res_search,
        holidays=holidays,
        today=today_dt.strftime('%A, %d %B %Y'),
        today_iso=today_dt.isoformat(),
        active_tab=active_tab
    )

@app.route('/api/upload-welcome-image', methods=['POST'])
def upload_welcome_image():
    if 'image' not in request.files:
        return jsonify({'success': False, 'message': 'No image file uploaded'}), 400
    file = request.files['image']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No selected file'}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.jpg', '.jpeg', '.png', '.webp', '.bmp']:
        return jsonify({'success': False, 'message': 'Allowed image formats: JPG, PNG, WEBP'}), 400

    save_path = os.path.join(app.root_path, 'static', 'img', 'welcome_mural.jpg')
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    file.save(save_path)
    return jsonify({
        'success': True,
        'message': 'Welcome image updated successfully!',
        'image_url': url_for('static', filename='img/welcome_mural.jpg') + f'?t={int(datetime.now().timestamp())}'
    })

@app.route('/camera')
def camera():
    selected_date = date.today().isoformat()
    selected_grade = request.args.get('grade', session.get('selected_grade', 'All'))
    session['selected_grade'] = selected_grade
    attendance_records = get_today_attendance(selected_date)
    if selected_grade and selected_grade != 'All':
        attendance_records = [r for r in attendance_records if r.get('grade') == selected_grade]
    model_ready = os.path.exists(TRAINER_PATH)
    return render_template(
        'camera.html',
        attendance_records=attendance_records,
        today=selected_date,
        model_ready=model_ready,
        selected_grade=selected_grade
    )

@app.route('/students')
def students_list():
    selected_grade = request.args.get('grade', session.get('selected_grade', 'All'))
    session['selected_grade'] = selected_grade
    search = request.args.get('search', '').strip()
    filter_grade = selected_grade if selected_grade != 'All' else None
    students = get_all_students(filter_grade=filter_grade, search=search if search else None)
    return render_template(
        'students.html',
        students=students,
        selected_grade=selected_grade,
        search=search
    )

@app.route('/register', methods=['GET', 'POST'])
def register_student():
    if request.method == 'POST':
        student_id = request.form.get('student_id', '').strip().upper()
        full_name = request.form.get('full_name', '').strip()
        grade = request.form.get('grade', '').strip()
        section = request.form.get('section', '').strip().upper()
        roll_no = request.form.get('roll_no', '').strip()
        gender = request.form.get('gender', 'Other')
        category = request.form.get('category', 'General').strip() or 'General'
        dob = request.form.get('dob', '').strip()
        guardian_name = request.form.get('guardian_name', '').strip()
        parent_phone = request.form.get('parent_phone', '').strip()
        guardian_phone = request.form.get('guardian_phone', '').strip()

        if not parent_phone and guardian_phone:
            parent_phone = guardian_phone
        if not guardian_phone and parent_phone:
            guardian_phone = parent_phone

        if not student_id or not full_name or not grade or not roll_no:
            flash('Please fill in all required student details (ID, Name, Grade, Roll No).', 'error')
            return redirect(url_for('register_student'))

        # Check duplicate
        if get_student_by_id(student_id):
            flash(f'Student with ID {student_id} already exists.', 'error')
            return redirect(url_for('register_student'))

        # Insert student initial record
        new_db_id = insert_student(
            student_id=student_id,
            full_name=full_name,
            grade=grade,
            section=section,
            roll_no=roll_no,
            gender=gender,
            guardian_name=guardian_name,
            guardian_phone=guardian_phone,
            parent_phone=parent_phone,
            category=category,
            dob=dob
        )

        if not new_db_id:
            flash('Could not create student. Please verify ID is unique.', 'error')
            return redirect(url_for('register_student'))

        # Process face images: either from webcam frames or file upload
        face_images = []

        # 1. Check webcam snapshots sent as JSON array string or separate fields
        webcam_snapshots_raw = request.form.get('captured_faces_json', '')
        if webcam_snapshots_raw:
            import json
            try:
                snapshots_list = json.loads(webcam_snapshots_raw)
                for item in snapshots_list:
                    if item:
                        face_images.append(item)
            except Exception as e:
                print("Error parsing captured faces JSON:", e)

        # 2. Check uploaded file
        if 'photo_file' in request.files:
            file = request.files['photo_file']
            if file and file.filename != '':
                file_bytes = file.read()
                img = robust_decode_image(file_bytes)
                if img is not None:
                    face_images.append(img)

        # Save face samples and get profile image path
        profile_path = None
        if len(face_images) > 0:
            count, profile_path = save_student_face_samples(student_id, new_db_id, face_images)
            if profile_path:
                update_student(
                    student_id, full_name, grade, section, roll_no, gender,
                    guardian_name, guardian_phone, profile_path, parent_phone=parent_phone,
                    category=category, dob=dob
                )

            # Retrain model
            s_map, _ = get_student_maps()
            train_face_recognizer(s_map)
            flash(f'Student {full_name} enrolled successfully with {count} face samples trained!', 'success')
        else:
            flash(f'Student {full_name} registered without camera samples. You can add face data anytime.', 'warning')

        return redirect(url_for('students_list'))

    # Generate suggested next student ID and class roll number
    all_stu = get_all_students()
    existing_ids = set(s['student_id'] for s in all_stu)
    cand_num = 1001 + len(all_stu)
    while f"STU-{cand_num}" in existing_ids:
        cand_num += 1
    next_id = f"STU-{cand_num}"
    suggested_roll = str(len(all_stu) + 1)
    return render_template('register.html', suggested_id=next_id, suggested_roll=suggested_roll)

@app.route('/students/delete/<student_id>', methods=['POST'])
def remove_student(student_id):
    student = get_student_by_id(student_id)
    if student:
        name = student["full_name"]
        delete_student(student_id, auto_reorder=True)
        # Retrain model with updated mapping
        s_map, _ = get_student_maps()
        train_face_recognizer(s_map)
        flash(f'Student {name} removed successfully. Roster order and IDs automatically updated.', 'info')
    return redirect(url_for('students_list'))

@app.route('/students/reorder', methods=['POST', 'GET'])
def reorder_students_route():
    ok, msg = reorder_all_students()
    s_map, _ = get_student_maps()
    train_face_recognizer(s_map)
    flash(f'{msg}', 'success' if ok else 'warning')
    return redirect(url_for('students_list'))

@app.route('/students/edit/<student_id>', methods=['POST'])
def edit_student_profile(student_id):
    student = get_student_by_id(student_id)
    if not student:
        flash('Student not found.', 'error')
        return redirect(url_for('students_list'))

    full_name = request.form.get('full_name', '').strip() or student['full_name']
    grade = request.form.get('grade', '').strip() or student['grade']
    section = request.form.get('section', '').strip().upper() or student['section']
    roll_no = request.form.get('roll_no', '').strip() or student['roll_no']
    gender = request.form.get('gender', student.get('gender', 'Other'))
    category = request.form.get('category', student.get('category', 'General')).strip() or 'General'
    dob = request.form.get('dob', student.get('dob', '')).strip()
    guardian_name = request.form.get('guardian_name', '').strip()
    parent_phone = request.form.get('parent_phone', '').strip()
    guardian_phone = request.form.get('guardian_phone', '').strip()

    if not parent_phone and guardian_phone:
        parent_phone = guardian_phone
    if not guardian_phone and parent_phone:
        guardian_phone = parent_phone

    # Optional photo update
    photo_path = student.get('photo_path')
    if 'photo_file' in request.files:
        file = request.files['photo_file']
        if file and file.filename != '':
            file_bytes = file.read()
            img_cv = robust_decode_image(file_bytes)
            if img_cv is not None:
                ext = '.jpg'
                filename = f"profile_{int(datetime.now().timestamp())}{ext}"
                dest_folder = os.path.join('static', 'dataset', student_id)
                os.makedirs(dest_folder, exist_ok=True)
                save_path = os.path.join(dest_folder, filename)
                cv2.imwrite(save_path, img_cv)
                photo_path = f"/static/dataset/{student_id}/{filename}"
                try:
                    db_id = student['id']
                    save_student_face_samples(student_id, db_id, [img_cv])
                    s_map, _ = get_student_maps()
                    train_face_recognizer(s_map)
                except Exception as e:
                    print("Face retrain error on edit:", e)

    update_student(
        student_id=student_id,
        full_name=full_name,
        grade=grade,
        section=section,
        roll_no=roll_no,
        gender=gender,
        guardian_name=guardian_name,
        guardian_phone=guardian_phone,
        photo_path=photo_path,
        parent_phone=parent_phone,
        category=category,
        dob=dob
    )

    flash(f'Student profile for {full_name} updated and saved successfully!', 'success')
    return redirect(url_for('students_list'))

@app.route('/logs')
def attendance_logs():
    target_date = request.args.get('date', date.today().isoformat())
    grade = request.args.get('grade', session.get('selected_grade', 'All'))
    session['selected_grade'] = grade
    records = get_today_attendance(target_date)

    if grade and grade != 'All':
        records = [r for r in records if r['grade'] == grade]

    absent_count = sum(1 for r in records if r['attendance_status'] != 'Present')
    sent_student_ids = get_sent_whatsapp_student_ids(target_date)
    for r in records:
        r['whatsapp_sent'] = (r['student_id'] in sent_student_ids)

    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()

    return render_template(
        'logs.html',
        records=records,
        selected_date=target_date,
        selected_grade=grade,
        absent_count=absent_count,
        today_date=today_str,
        yesterday_date=yesterday_str
    )

@app.route('/absent-alert')
def absent_alert():
    target_date = request.args.get('date', date.today().isoformat())
    grade = request.args.get('grade', session.get('selected_grade', 'All'))
    session['selected_grade'] = grade
    records = get_today_attendance(target_date)

    if grade and grade != 'All':
        records = [r for r in records if r['grade'] == grade]

    absent_records = [r for r in records if r['attendance_status'] != 'Present']
    sent_student_ids = get_sent_whatsapp_student_ids(target_date)
    for r in absent_records:
        r['whatsapp_sent'] = (r['student_id'] in sent_student_ids)

    recent_wa_logs = get_whatsapp_logs_by_date(target_date)

    return render_template(
        'absent_alert.html',
        records=absent_records,
        selected_date=target_date,
        selected_grade=grade,
        absent_count=len(absent_records),
        recent_logs=recent_wa_logs
    )

def sanitize_phone_for_whatsapp(phone):
    if not phone:
        return ""
    digits = re.sub(r'\D', '', str(phone))
    if not digits:
        return ""
    # Already has country code (12 digits with 91 prefix, or 13 digits with +91)
    if len(digits) == 12 and digits.startswith('91'):
        return digits
    # Standard Indian 10-digit mobile (starts with 6,7,8,9)
    if len(digits) == 10 and digits[0] in ['6', '7', '8', '9']:
        return '91' + digits
    # 11-digit with leading 0 (STD format)
    if len(digits) == 11 and digits.startswith('0'):
        return '91' + digits[1:]
    # Already has 91 in other lengths - return as-is
    if digits.startswith('91') and len(digits) > 10:
        return digits
    return digits

def generate_absent_whatsapp_message(student_name, roll_no, grade, section, target_date):
    return (
        f"🏫 *Ash Education - હાજરી એલર્ટ (Attendance Alert)*\n\n"
        f"આદરણીય વાલીશ્રી,\n\n"
        f"આ *Ash Education* તરફથી હાજરી અંગેનો સત્તાવાર સંદેશ છે.\n"
        f"આપનો પાલ્ય *{student_name}* (રોલ નં: {roll_no}, ધોરણ: {grade} - {section}) આજે તારીખ {target_date} ના રોજ શાળામાં *ગેરહાજર (ABSENT)* નોંધાયેલ છે.\n\n"
        f"જો આપને આ ગેરહાજરી અંગે પૂર્વ જાણ ન હોય અથવા કોઈ કારણ જણાવવાનું બાકી હોય, તો કૃપા કરીને તાત્કાલિક શાળાના વહીવટી વિભાગનો સંપર્ક કરશો.\n\n"
        f"આભાર સહ,\n"
        f"*Ash Education સ્કૂલ વહીવટી વિભાગ*"
    )

def generate_whatsapp_url(phone, message):
    clean_phone = sanitize_phone_for_whatsapp(phone)
    if not clean_phone:
        return ""
    encoded_msg = urllib.parse.quote(message)
    return f"https://api.whatsapp.com/send?phone={clean_phone}&text={encoded_msg}"

def generate_low_attendance_whatsapp_message(student_name, roll_no, grade, section, percentage, present_days, total_days, classes_needed=0, threshold=75.0):
    deficit_line = f"• {threshold:.0f}% હાજરી પૂર્ણ કરવા માટે જરૂરી હાજર દિવસો: *{classes_needed} દિવસ*\n" if classes_needed > 0 else ""
    return (
        f"🏫 *Ash Education - ઓછી હાજરી અંગે ચેતવણી (Attendance Alert Notice)*\n\n"
        f"આદરણીય વાલીશ્રી (*{student_name}* ના વાલી),\n\n"
        f"⚠️ *મહત્વપૂર્ણ ચેતવણી: હાજરીની ઘટ (Attendance Shortage)*\n"
        f"આ આપના પાલ્યની શાળામાં એકંદર હાજરી અંગેની સત્તાવાર સૂચના છે.\n\n"
        f"📋 *વિદ્યાર્થીનો હાજરી અહેવાલ:*\n"
        f"• વિદ્યાર્થીનું નામ: *{student_name}*\n"
        f"• રોલ નં: *{roll_no}* | ધોરણ: *{grade} - {section}*\n"
        f"• હાલની હાજરી: *{percentage}%* (કુલ {total_days} માંથી {present_days} દિવસ હાજર)\n"
        f"• કુલ ગેરહાજરી: *{max(0, total_days - present_days)} દિવસ*\n"
        f"• શાળા નિયમ મુજબ જરૂરી લઘુત્તમ હાજરી: *{threshold:.0f}%*\n"
        f"{deficit_line}\n"
        f"શિક્ષણ અને વાર્ષિક/બોર્ડ પરીક્ષાની પાત્રતા માટે નિયમિત હાજરી ફરજિયાત છે. કૃપા કરીને આપનો પાલ્ય નિયમિત શાળાએ ઉપસ્થિત રહે તેની ખાસ કાળજી લેશો.\n\n"
        f"જો કોઈ તબીબી કારણ (Medical Reason) હોય કે અન્ય રજૂઆત હોય, તો શાળા કાર્યાલયનો તાત્કાલિક સંપર્ક કરશો.\n\n"
        f"આભાર સહ,\n"
        f"*શિક્ષણ વિભાગ / વહીવટી કાર્યાલય*\n"
        f"*Ash Education*"
    )



@app.route('/api/whatsapp/absent-list', methods=['GET'])
def get_whatsapp_absent_list():
    target_date = request.args.get('date', date.today().isoformat())
    grade = request.args.get('grade', 'All')
    records = get_today_attendance(target_date)
    if grade and grade != 'All':
        records = [r for r in records if r['grade'] == grade]

    absent_records = [r for r in records if r['attendance_status'] != 'Present']
    sent_student_ids = get_sent_whatsapp_student_ids(target_date)

    items = []
    for r in absent_records:
        raw_phone = r.get('parent_phone') or r.get('guardian_phone') or ''
        clean_phone = sanitize_phone_for_whatsapp(raw_phone)
        msg = generate_absent_whatsapp_message(
            student_name=r['full_name'],
            roll_no=r.get('roll_no', '--'),
            grade=r.get('grade', '--'),
            section=r.get('section', '--'),
            target_date=target_date
        )
        url = generate_whatsapp_url(clean_phone, msg)
        items.append({
            'student_id': r['student_id'],
            'full_name': r['full_name'],
            'roll_no': r.get('roll_no', '--'),
            'grade': r.get('grade', '--'),
            'section': r.get('section', '--'),
            'photo_path': r.get('photo_path', ''),
            'parent_phone': raw_phone,
            'clean_phone': clean_phone,
            'message': msg,
            'whatsapp_url': url,
            'already_sent': r['student_id'] in sent_student_ids
        })

    return jsonify({
        'success': True,
        'date': target_date,
        'total_absent': len(items),
        'absent_students': items
    })

@app.route('/api/whatsapp/log-sent', methods=['POST'])
def log_whatsapp_sent():
    data = request.get_json(silent=True) or {}
    student_id = data.get('student_id', '')
    student_name = data.get('student_name', '')
    parent_phone = data.get('parent_phone', '')
    msg = data.get('message', '')
    target_date = data.get('date', date.today().isoformat())

    if not student_id:
        return jsonify({'success': False, 'message': 'Missing student_id'}), 400

    log_id = log_whatsapp_message(student_id, parent_phone, student_name, msg, target_date)
    return jsonify({'success': True, 'log_id': log_id, 'message': f'WhatsApp alert logged for {student_name}'})

@app.route('/api/whatsapp/send-all-absent', methods=['POST'])
def send_all_whatsapp_absent():
    data = request.get_json(silent=True) or {}
    target_date = data.get('date', date.today().isoformat())
    grade = data.get('grade', 'All')
    custom_template = data.get('custom_message', '')

    records = get_today_attendance(target_date)
    if grade and grade != 'All':
        records = [r for r in records if r['grade'] == grade]

    absent_records = [r for r in records if r['attendance_status'] != 'Present']
    dispatched = []

    for r in absent_records:
        raw_phone = r.get('parent_phone') or r.get('guardian_phone') or ''
        clean_phone = sanitize_phone_for_whatsapp(raw_phone)
        if custom_template:
            msg = custom_template.replace('{student_name}', r['full_name'])\
                                 .replace('{roll_no}', str(r.get('roll_no', '')))\
                                 .replace('{grade}', str(r.get('grade', '')))\
                                 .replace('{section}', str(r.get('section', '')))\
                                 .replace('{date}', target_date)
        else:
            msg = generate_absent_whatsapp_message(
                student_name=r['full_name'],
                roll_no=r.get('roll_no', '--'),
                grade=r.get('grade', '--'),
                section=r.get('section', '--'),
                target_date=target_date
            )

        url = generate_whatsapp_url(clean_phone, msg)
        log_id = log_whatsapp_message(r['student_id'], raw_phone, r['full_name'], msg, target_date)
        dispatched.append({
            'student_id': r['student_id'],
            'full_name': r['full_name'],
            'parent_phone': raw_phone,
            'clean_phone': clean_phone,
            'whatsapp_url': url,
            'message': msg,
            'log_id': log_id
        })

    return jsonify({
        'success': True,
        'date': target_date,
        'count': len(dispatched),
        'dispatched': dispatched,
        'message': f'Prepared and logged {len(dispatched)} WhatsApp alerts for absent students.'
    })

@app.route('/reports')
def reports():
    start_date = request.args.get('start_date', (date.today().replace(day=1)).isoformat())
    end_date = request.args.get('end_date', date.today().isoformat())
    grade = request.args.get('grade', session.get('selected_grade', 'All'))
    session['selected_grade'] = grade
    
    records = get_attendance_reports(start_date=start_date, end_date=end_date, grade=grade)
    
    # Calculate summary metrics
    total_logs = len(records)
    present_cnt = sum(1 for r in records if r['status'] == 'Present')
    late_cnt = sum(1 for r in records if r['status'] == 'Late')
    excused_cnt = sum(1 for r in records if r['status'] == 'Excused')
    absent_cnt = sum(1 for r in records if r['status'] == 'Absent')
    boys_present = sum(1 for r in records if r.get('status') in ('Present', 'Late') and str(r.get('gender', '')).lower() in ('male', 'boy', 'm'))
    girls_present = sum(1 for r in records if r.get('status') in ('Present', 'Late') and str(r.get('gender', '')).lower() in ('female', 'girl', 'f'))

    return render_template(
        'reports.html',
        records=records,
        start_date=start_date,
        end_date=end_date,
        selected_grade=grade,
        total_logs=total_logs,
        present_cnt=present_cnt,
        late_cnt=late_cnt,
        excused_cnt=excused_cnt,
        absent_cnt=absent_cnt,
        boys_present=boys_present,
        girls_present=girls_present
    )

@app.route('/low-attendance')
def low_attendance_view():
    """Defaulter & low attendance tracking hub with WhatsApp parent alerts."""
    try:
        threshold = float(request.args.get('threshold', 75.0))
    except (ValueError, TypeError):
        threshold = 75.0

    grade = request.args.get('grade', session.get('selected_grade', 'All'))
    session['selected_grade'] = grade
    section = request.args.get('section', 'All')
    view_mode = request.args.get('view_mode', 'defaulters')  # 'defaulters' or 'all'
    search_query = request.args.get('q', '').strip().lower()
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    students, summary = get_low_attendance_students(
        threshold=threshold,
        grade=grade,
        section=section,
        start_date=start_date if start_date else None,
        end_date=end_date if end_date else None
    )

    # Attach customized WhatsApp messages and URLs to each student
    for s in students:
        clean_phone = sanitize_phone_for_whatsapp(s['effective_phone'])
        msg = generate_low_attendance_whatsapp_message(
            student_name=s['full_name'],
            roll_no=s['roll_no'],
            grade=s['grade'],
            section=s['section'],
            percentage=s['percentage'],
            present_days=s['present_days'],
            total_days=s['total_days'],
            classes_needed=s['classes_needed'],
            threshold=threshold
        )
        s['clean_phone'] = clean_phone
        s['whatsapp_message'] = msg
        s['whatsapp_url'] = generate_whatsapp_url(clean_phone, msg)

    # Filter according to view_mode
    if view_mode == 'defaulters':
        display_students = [s for s in students if s['is_defaulter']]
    else:
        display_students = students

    # Filter by search keyword if provided
    if search_query:
        display_students = [
            s for s in display_students
            if search_query in s['full_name'].lower() or search_query in s['roll_no'].lower() or search_query in s['student_id'].lower()
        ]

    return render_template(
        'low_attendance.html',
        students=display_students,
        all_students_count=len(students),
        summary=summary,
        threshold=threshold,
        selected_grade=grade,
        selected_section=section,
        view_mode=view_mode,
        search_query=search_query,
        start_date=start_date,
        end_date=end_date
    )

low_attendance = low_attendance_view

@app.route('/api/whatsapp/low-attendance-list', methods=['GET'])
def get_whatsapp_low_attendance_list():
    try:
        threshold = float(request.args.get('threshold', 75.0))
    except (ValueError, TypeError):
        threshold = 75.0
    grade = request.args.get('grade', 'All')

    students, summary = get_low_attendance_students(threshold=threshold, grade=grade)
    defaulters = [s for s in students if s['is_defaulter']]

    for s in defaulters:
        clean_phone = sanitize_phone_for_whatsapp(s['effective_phone'])
        msg = generate_low_attendance_whatsapp_message(
            student_name=s['full_name'],
            roll_no=s['roll_no'],
            grade=s['grade'],
            section=s['section'],
            percentage=s['percentage'],
            present_days=s['present_days'],
            total_days=s['total_days'],
            classes_needed=s['classes_needed'],
            threshold=threshold
        )
        s['clean_phone'] = clean_phone
        s['whatsapp_message'] = msg
        s['whatsapp_url'] = generate_whatsapp_url(clean_phone, msg)

    return jsonify({
        'success': True,
        'threshold': threshold,
        'total_defaulters': len(defaulters),
        'defaulters': defaulters
    })

@app.route('/api/whatsapp/low-attendance-send', methods=['POST'])
def send_low_attendance_whatsapp():
    data = request.get_json(silent=True) or {}
    student_id = data.get('student_id', '')
    student_name = data.get('student_name', '')
    parent_phone = data.get('parent_phone', '')
    msg = data.get('message', '')
    today_str = date.today().isoformat()

    if not student_id:
        return jsonify({'success': False, 'message': 'Missing student_id'}), 400

    log_id = log_whatsapp_message(
        student_id=student_id,
        parent_phone=parent_phone,
        student_name=student_name,
        message=msg,
        sent_date=today_str,
        status='Low Attendance Warning'
    )
    return jsonify({
        'success': True,
        'log_id': log_id,
        'message': f'Low attendance notice recorded for {student_name}'
    })

@app.route('/api/whatsapp/low-attendance-send-all', methods=['POST'])
def send_all_low_attendance_whatsapp():
    data = request.get_json(silent=True) or {}
    try:
        threshold = float(data.get('threshold', 75.0))
    except (ValueError, TypeError):
        threshold = 75.0
    grade = data.get('grade', 'All')

    students, summary = get_low_attendance_students(threshold=threshold, grade=grade)
    defaulters = [s for s in students if s['is_defaulter']]

    today_str = date.today().isoformat()
    dispatched = []

    for s in defaulters:
        clean_phone = sanitize_phone_for_whatsapp(s['effective_phone'])
        msg = generate_low_attendance_whatsapp_message(
            student_name=s['full_name'],
            roll_no=s['roll_no'],
            grade=s['grade'],
            section=s['section'],
            percentage=s['percentage'],
            present_days=s['present_days'],
            total_days=s['total_days'],
            classes_needed=s['classes_needed'],
            threshold=threshold
        )
        url = generate_whatsapp_url(clean_phone, msg)
        log_whatsapp_message(
            student_id=s['student_id'],
            parent_phone=s['effective_phone'],
            student_name=s['full_name'],
            message=msg,
            sent_date=today_str,
            status='Low Attendance Warning'
        )
        dispatched.append({
            'student_id': s['student_id'],
            'full_name': s['full_name'],
            'clean_phone': clean_phone,
            'whatsapp_url': url
        })

    return jsonify({
        'success': True,
        'count': len(dispatched),
        'dispatched': dispatched,
        'message': f'Prepared and recorded {len(dispatched)} low attendance notices.'
    })

@app.route('/holidays')
def holidays_view():
    """Monthly academic & gazetted school holidays calendar."""
    today = date.today()
    try:
        req_year = int(request.args.get('year', today.year))
        req_month = int(request.args.get('month', today.month))
        if req_month < 1 or req_month > 12:
            req_month = today.month
    except (ValueError, TypeError):
        req_year = today.year
        req_month = today.month

    # Previous and next month calculation
    if req_month == 1:
        prev_month = 12
        prev_year = req_year - 1
    else:
        prev_month = req_month - 1
        prev_year = req_year

    if req_month == 12:
        next_month = 1
        next_year = req_year + 1
    else:
        next_month = req_month + 1
        next_year = req_year

    month_name = calendar.month_name[req_month]
    month_name_full = f"{month_name} {req_year}"

    # Month calendar grid: Sunday first (firstweekday=6)
    cal = calendar.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(req_year, req_month)

    # Fetch holidays for this month from database
    month_holidays = get_holidays_by_month(req_year, req_month)

    # Map day number -> list of holidays
    holiday_by_day = {}
    for h in month_holidays:
        try:
            day_num = int(h['holiday_date'].split('-')[2])
            if day_num not in holiday_by_day:
                holiday_by_day[day_num] = []
            holiday_by_day[day_num].append(h)
        except Exception:
            pass

    # Total days in month
    _, total_days_in_month = calendar.monthrange(req_year, req_month)

    # Count Sundays
    sundays_count = 0
    for day in range(1, total_days_in_month + 1):
        if calendar.weekday(req_year, req_month, day) == 6:
            sundays_count += 1

    holidays_count = len(month_holidays)

    # Count weekday holidays
    weekday_holidays = 0
    for h in month_holidays:
        try:
            d = int(h['holiday_date'].split('-')[2])
            if calendar.weekday(req_year, req_month, d) != 6:
                weekday_holidays += 1
        except Exception:
            weekday_holidays += 1

    working_days = max(0, total_days_in_month - sundays_count - weekday_holidays)

    # All holidays in current year for quick reference
    all_year_holidays = get_all_holidays(req_year)

    national_count = sum(1 for h in month_holidays if h.get('holiday_type') == 'National')
    festival_count = sum(1 for h in month_holidays if h.get('holiday_type') in ['Festival', 'Religious'])
    academic_count = sum(1 for h in month_holidays if h.get('holiday_type') in ['Academic', 'Special'])

    return render_template(
        'holidays.html',
        current_year=req_year,
        current_month=req_month,
        month_name=month_name,
        month_name_full=month_name_full,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month,
        month_days=month_days,
        month_holidays=month_holidays,
        holiday_by_day=holiday_by_day,
        total_holidays=holidays_count,
        sundays_count=sundays_count,
        working_days=working_days,
        total_days_in_month=total_days_in_month,
        national_count=national_count,
        festival_count=festival_count,
        academic_count=academic_count,
        all_year_holidays=all_year_holidays,
        today_date=today.isoformat(),
        today_year=today.year,
        today_month=today.month,
        today_day=today.day
    )

@app.route('/api/holidays/add', methods=['POST'])
def api_add_holiday():
    title = request.form.get('title', '').strip()
    holiday_date = request.form.get('holiday_date', '').strip()
    holiday_type = request.form.get('holiday_type', 'National').strip()
    description = request.form.get('description', '').strip()

    if not title or not holiday_date:
        flash('Holiday Title and Date are required.', 'error')
        return redirect(request.referrer or url_for('holidays_view'))

    add_holiday(title, holiday_date, holiday_type, description)
    flash(f'Holiday "{title}" successfully added to academic calendar!', 'success')

    try:
        parts = holiday_date.split('-')
        return redirect(url_for('holidays_view', year=parts[0], month=int(parts[1])))
    except Exception:
        return redirect(url_for('holidays_view'))

@app.route('/api/holidays/delete/<int:holiday_id>', methods=['POST'])
def api_delete_holiday(holiday_id):
    delete_holiday(holiday_id)
    flash('Holiday removed from academic calendar.', 'success')
    return redirect(request.referrer or url_for('holidays_view'))

# ----------------- REST & CAMERA APIS ----------------- #

@app.route('/api/validate-uploaded-photo', methods=['POST'])
def api_validate_uploaded_photo():
    """
    Real-time face detection and biometric quality validation for uploaded student photos.
    Decodes image with automatic EXIF orientation handling, detects face(s),
    evaluates quality score, and returns an annotated preview and cropped face avatar.
    """
    img_bgr = None
    if 'photo_file' in request.files:
        file = request.files['photo_file']
        if file and file.filename != '':
            img_bgr = robust_decode_image(file.read())
    elif request.is_json:
        data = request.get_json(silent=True) or {}
        img_raw = data.get('image', '')
        if img_raw:
            img_bgr = robust_decode_image(img_raw)

    if img_bgr is None or img_bgr.size == 0:
        return jsonify({'success': False, 'face_count': 0, 'message': 'Could not read image file. Please provide a valid JPG or PNG.'}), 400

    h_img, w_img = img_bgr.shape[:2]
    faces = detect_faces(img_bgr, high_sensitivity=True)

    if len(faces) == 0:
        # Check if the uploaded image might already be a tight face crop
        if w_img >= 45 and h_img >= 45:
            is_q, q_score, q_reason = validate_face_quality(img_bgr, (0, 0, w_img, h_img), is_upload=True)
            if is_q:
                annotated = img_bgr.copy()
                cv2.rectangle(annotated, (2, 2), (w_img - 2, h_img - 2), (60, 179, 113), 2)
                preview_b64 = cv2_to_base64(annotated)
                crop_b64 = cv2_to_base64(img_bgr)
                return jsonify({
                    'success': True,
                    'face_count': 1,
                    'quality_score': q_score,
                    'quality_reason': q_reason,
                    'preview_b64': preview_b64,
                    'crop_b64': crop_b64,
                    'message': 'Face detected (Close-up portrait)'
                })
        return jsonify({
            'success': False,
            'face_count': 0,
            'message': 'No face detected. Please ensure the student is facing the camera with good lighting and no heavy obstruction.'
        })

    # Primary face (largest)
    faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
    x, y, w, h = faces[0]
    is_q, q_score, q_reason = validate_face_quality(img_bgr, (x, y, w, h), is_upload=True)

    # Annotate preview
    annotated = img_bgr.copy()
    box_color = (60, 179, 113) if is_q else (0, 165, 255)
    cv2.rectangle(annotated, (x, y), (x + w, y + h), box_color, 2)
    badge_label = f"Face Detected ({q_score}%)" if is_q else f"Quality Alert ({q_score}%)"
    cv2.rectangle(annotated, (x, max(0, y - 30)), (x + w, y), box_color, -1)
    cv2.putText(annotated, badge_label, (x + 6, max(18, y - 9)), cv2.FONT_HERSHEY_DUPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)

    # Extract cropped face with 12% margin
    pad_y = int(h * 0.12)
    pad_x = int(w * 0.12)
    y1 = max(0, y - pad_y)
    y2 = min(h_img, y + h + pad_y)
    x1 = max(0, x - pad_x)
    x2 = min(w_img, x + w + pad_x)
    face_crop = img_bgr[y1:y2, x1:x2]

    preview_b64 = cv2_to_base64(annotated)
    crop_b64 = cv2_to_base64(face_crop)

    return jsonify({
        'success': True,
        'face_count': len(faces),
        'quality_score': q_score,
        'quality_reason': q_reason,
        'preview_b64': preview_b64,
        'crop_b64': crop_b64,
        'message': f"{len(faces)} face{'s' if len(faces) > 1 else ''} detected with {q_score}% biometric clarity."
    })

@app.route('/api/process-frame', methods=['POST'])
def process_frame():
    """
    Receives webcam frame or static photo in base64.
    Runs 5-state validation pipeline:
    1. Face Quality Validation (Section 2.4)
    2. LBPH Biometric Recognition with Calibrated Threshold (Section 2.1 & 2.3)
    3. Multi-Frame Confirmation (Section 2.2): Requires 3 consecutive confirmations before marking attendance.
    4. 30-Second Cooldown & Single Daily Check-in (Section 2.8)
    5. Audit Event Logging (Section 11 & Section 15)
    """
    data = request.get_json(force=True, silent=True)
    if not data or 'image' not in data:
        return jsonify({'success': False, 'message': 'No image provided'}), 400

    img_bgr = base64_to_cv2(data['image'])
    if img_bgr is None:
        return jsonify({'success': False, 'message': 'Invalid image format'}), 400

    auto_mark = data.get('auto_mark', True)
    is_confirmed = data.get('is_confirmed', False) or data.get('is_static', False)
    confirm_count = int(data.get('confirm_count', 1))
    camera_source = data.get('camera_id', 'webcam-1')

    _, db_to_stu = get_student_maps()

    today_str = date.today().isoformat()
    already_marked_ids = get_today_marked_student_ids(today_str)

    analysis = analyze_frame_faces(img_bgr, db_to_stu, distance_threshold=80.0, exclude_student_ids=already_marked_ids)

    marked_events = []
    now_time = datetime.now().strftime('%H:%M:%S')

    for face in analysis.get('faces', []):
        code = face.get('code')
        stu = face.get('student')
        conf = face.get('confidence', 0.0)

        if code == 'poor_quality':
            log_recognition_event('NONE', 0.0, 'POOR FACE QUALITY', camera_id=camera_source)
        elif code == 'low_confidence':
            cand_id = stu.get('student_id') if stu else 'UNKNOWN'
            log_recognition_event(cand_id, conf, 'LOW CONFIDENCE', camera_id=camera_source)
        elif code == 'unknown':
            log_recognition_event('UNKNOWN', conf, 'UNKNOWN', camera_id=camera_source)
        elif code == 'candidate' and stu:
            student_id = stu['student_id']

            if student_id in already_marked_ids:
                # Already marked today
                log_recognition_event(student_id, conf, 'ALREADY LOGGED', camera_id=camera_source)
                continue

            # Multi-frame confirmation check (Section 2.2)
            if auto_mark and (is_confirmed or confirm_count >= 3):
                ok, msg = record_attendance(
                    student_id=student_id,
                    status='Present',
                    method='Camera-OpenCV',
                    confidence=conf,
                    notes='Multi-Frame Confirmed Biometric Match'
                )
                if ok:
                    already_marked_ids.add(student_id)
                    marked_events.append({
                        'student_id': student_id,
                        'full_name': stu['full_name'],
                        'grade': stu['grade'],
                        'section': stu['section'],
                        'roll_no': stu['roll_no'],
                        'photo_path': stu['photo_path'],
                        'time': now_time,
                        'confidence': conf,
                        'already_logged': False
                    })
                    log_recognition_event(student_id, conf, 'MATCHED', camera_id=camera_source)
                else:
                    marked_events.append({
                        'student_id': student_id,
                        'full_name': stu['full_name'],
                        'grade': stu['grade'],
                        'section': stu['section'],
                        'roll_no': stu['roll_no'],
                        'photo_path': stu['photo_path'],
                        'time': now_time,
                        'confidence': conf,
                        'already_logged': True,
                        'status_msg': msg
                    })
                    log_recognition_event(student_id, conf, 'ALREADY LOGGED', camera_id=camera_source)
            else:
                # Candidate identified, verification frame in progress (Section 2.2)
                log_recognition_event(student_id, conf, f'VERIFYING (Frame {confirm_count}/3)', camera_id=camera_source)

    # Format structured results matching frontend camera.js
    results = []
    for face in analysis.get('faces', []):
        code = face.get('code')
        stu = face.get('student')
        is_rec = face.get('is_recognized', False)
        is_marked = False
        already_logged = face.get('already_logged', False)
        event_time = now_time

        if stu:
            if stu['student_id'] in already_marked_ids:
                already_logged = True
            for ev in marked_events:
                if ev['student_id'] == stu['student_id']:
                    is_marked = not ev.get('already_logged', False)
                    event_time = ev.get('time', now_time)
                    break

        results.append({
            'bbox': face.get('box', [0, 0, 0, 0]),
            'status': face.get('status', 'UNKNOWN'),
            'code': code,
            'student': stu,
            'confidence': face.get('confidence', 0.0),
            'marked': is_marked,
            'already_logged': already_logged,
            'quality_ok': face.get('quality_ok', True),
            'quality_reason': face.get('quality_reason', ''),
            'time': event_time
        })

    return jsonify({
        'success': True,
        'detected_count': analysis['detected_count'],
        'faces': analysis['faces'],
        'results': results,
        'marked_events': marked_events,
        'annotated_b64': analysis.get('annotated_b64')
    })

@app.route('/api/audit-logs', methods=['GET'])
def get_audit_logs():
    """Returns recent recognition audit logs for safety auditing (Section 11)."""
    target_date = request.args.get('date', date.today().isoformat())
    limit = int(request.args.get('limit', 100))
    logs = get_recognition_logs(target_date=target_date, limit=limit)
    unknown_count = get_unknown_detection_count(target_date)
    return jsonify({
        'success': True,
        'date': target_date,
        'total_logs': len(logs),
        'unknown_count': unknown_count,
        'logs': logs
    })

@app.route('/api/mark-status', methods=['POST'])
def mark_status_manual():
    """Manual status toggle by teacher (Present, Late, Excused, Absent)."""
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({'success': False, 'message': 'No data'}), 400

    student_id = data.get('student_id')
    status = data.get('status', 'Present')
    target_date = data.get('date', date.today().isoformat())
    notes = data.get('notes', 'Marked manually by instructor')

    if not student_id:
        return jsonify({'success': False, 'message': 'Student ID required'}), 400

    ok = update_attendance_status(student_id, target_date, status, notes)
    if not ok:
        return jsonify({'success': False, 'message': f'Student {student_id} not found'}), 404
    return jsonify({'success': True, 'message': f'Status updated to {status}'})

@app.route('/api/mark-all-present', methods=['POST'])
def mark_all_present():
    """Batch marks all active students (optionally in a grade) as Present for a given date."""
    data = request.get_json(force=True, silent=True) or {}
    target_date = data.get('date', date.today().isoformat())
    grade = data.get('grade', 'All')
    students = get_all_students()
    if grade and grade != 'All':
        students = [s for s in students if s['grade'] == grade]

    count = 0
    for s in students:
        update_attendance_status(s['student_id'], target_date, 'Present', 'Batch fill present')
        count += 1
    return jsonify({'success': True, 'count': count, 'message': f'Marked {count} students present for {target_date}'})

@app.route('/api/retrain', methods=['POST'])
def trigger_retrain():
    """Rebuilds the OpenCV LBPH training model."""
    s_map, _ = get_student_maps()
    ok, msg = train_face_recognizer(s_map)
    return jsonify({'success': ok, 'message': msg})

@app.route('/api/export-csv')
def export_csv():
    """Exports attendance records to CSV."""
    start_date = request.args.get('start_date', date.today().isoformat())
    end_date = request.args.get('end_date', date.today().isoformat())
    grade = request.args.get('grade', session.get('selected_grade', 'All'))

    records = get_attendance_reports(start_date=start_date, end_date=end_date, grade=grade)

    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(['Date', 'Time', 'Student ID', 'Full Name', 'Grade', 'Section', 'Roll No', 'Status', 'Method', 'Confidence %', 'Guardian Phone'])

    for r in records:
        writer.writerow([
            r['date'],
            r['time'],
            r['student_id'],
            r['full_name'],
            r['grade'],
            r['section'],
            r['roll_no'],
            r['status'],
            r['method'],
            f"{r['confidence']}%" if r.get('confidence') else "N/A",
            r['guardian_phone'] or 'N/A'
        ])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=attendance_report_{start_date}_to_{end_date}.csv"
    output.headers["Content-type"] = "text/csv"
    return output

# ----------------- EXAMINATION RESULTS & RANKINGS ----------------- #

def get_pagination_window(current_page, total_pages, window=2):
    """Generates a clean list of page numbers and ellipsis for pagination buttons."""
    if total_pages <= 7:
        return list(range(1, total_pages + 1))
    pages = [1]
    start = max(2, current_page - window)
    end = min(total_pages - 1, current_page + window)
    if start > 2:
        pages.append('...')
    for p in range(start, end + 1):
        pages.append(p)
    if end < total_pages - 1:
        pages.append('...')
    pages.append(total_pages)
    return pages

@app.route('/results', methods=['GET'])
def exam_results_view():
    req_grade = request.args.get('grade')
    if req_grade:
        session['selected_grade'] = req_grade
        selected_grade = req_grade
    else:
        selected_grade = session.get('selected_grade', 'All')

    term = request.args.get('term', '')
    subject = request.args.get('subject', '')
    search = request.args.get('search', '').strip()
    sort_by = request.args.get('sort', 'rank')

    filter_grade = selected_grade if selected_grade != 'All' else None
    filter_term = term if term and term != 'All' else None
    filter_subject = subject if subject and subject != 'All' else None

    terms, subjects = get_exam_terms_and_subjects(grade=filter_grade)
    all_grades = get_all_result_grades()

    all_results = get_exam_results(
        exam_term=filter_term,
        subject=filter_subject,
        search=search if search else None,
        sort_by=sort_by,
        grade=filter_grade
    )

    stats = get_exam_summary_stats(
        exam_term=filter_term,
        subject=filter_subject,
        grade=filter_grade
    )

    # Pagination: exactly 10 students per page
    per_page = 10
    total_records = len(all_results)
    total_pages = max(1, (total_records + per_page - 1) // per_page)

    try:
        current_page = int(request.args.get('page', 1))
        if current_page < 1:
            current_page = 1
        elif current_page > total_pages:
            current_page = total_pages
    except (ValueError, TypeError):
        current_page = 1

    start_index = (current_page - 1) * per_page
    end_index = min(start_index + per_page, total_records)
    paginated_results = all_results[start_index:end_index] if total_records > 0 else []

    start_record = (start_index + 1) if total_records > 0 else 0
    end_record = end_index
    page_range = get_pagination_window(current_page, total_pages)

    return render_template(
        'results.html',
        results=paginated_results,
        all_results_count=total_records,
        current_page=current_page,
        total_pages=total_pages,
        per_page=per_page,
        start_record=start_record,
        end_record=end_record,
        has_prev=(current_page > 1),
        has_next=(current_page < total_pages),
        prev_page=(current_page - 1),
        next_page=(current_page + 1),
        page_range=page_range,
        stats=stats,
        terms=terms,
        subjects=subjects,
        selected_term=term or 'All',
        selected_subject=subject or 'All',
        selected_grade=selected_grade,
        all_grades=all_grades,
        search=search,
        sort_by=sort_by
    )

@app.route('/results/upload', methods=['POST'])
def upload_exam_results():
    file = request.files.get('result_file') or request.files.get('file')
    if not file or not file.filename:
        flash("No file was selected for upload. Please choose an Excel (.xlsx, .xls, .csv) or PDF (.pdf) file.", "danger")
        return redirect(url_for('exam_results_view'))

    exam_term = request.form.get('exam_term', '').strip() or "Annual Examination 2026"
    default_subject = request.form.get('default_subject', '').strip() or "General"
    target_grade = request.form.get('target_grade', '').strip()
    if not target_grade or target_grade == 'All':
        target_grade = session.get('selected_grade', '')
        if target_grade == 'All':
            target_grade = ''

    allowed_exts = {'.xlsx', '.xls', '.csv', '.pdf'}
    _, ext = os.path.splitext(file.filename.lower())
    if ext not in allowed_exts:
        flash(f"Unsupported file format '{ext}'. Please upload an Excel (.xlsx, .xls, .csv) or PDF (.pdf) file.", "danger")
        return redirect(url_for('exam_results_view'))

    try:
        records = parse_result_file(
            file,
            filename=file.filename,
            default_term=exam_term,
            default_subject=default_subject,
            default_grade=target_grade
        )

        if not records:
            flash("Could not detect any valid student rows in the uploaded file. Please verify columns include: Student Name, Roll No, Subject, and Marks.", "warning")
            return redirect(url_for('exam_results_view'))

        inserted_count = bulk_insert_exam_results(records)
        flash(f"Successfully converted and published {inserted_count} student examination results with automatic rank calculations!", "success")
        return redirect(url_for('exam_results_view', term=exam_term, grade=target_grade if target_grade else None))

    except Exception as e:
        flash(f"Error parsing uploaded file: {str(e)}", "danger")
        return redirect(url_for('exam_results_view'))

@app.route('/results/template', methods=['GET'])
def download_sample_template():
    try:
        target_grade = request.args.get('grade') or session.get('selected_grade', 'Grade 10')
        if target_grade == 'All':
            target_grade = 'Grade 10'
        content = generate_sample_excel_template(target_grade=target_grade)
        response = make_response(content)
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        clean_tag = target_grade.replace(' ', '_')
        response.headers['Content-Disposition'] = f'attachment; filename=Student_Exam_Results_Sample_Template_{clean_tag}.xlsx'
        return response
    except Exception as e:
        flash(f"Error generating template: {str(e)}", "danger")
        return redirect(url_for('exam_results_view'))

@app.route('/results/delete/<int:result_id>', methods=['POST'])
def delete_result(result_id):
    try:
        delete_exam_result(result_id)
        flash("Examination result record deleted successfully.", "info")
    except Exception as e:
        flash(f"Error deleting result: {str(e)}", "danger")
    return redirect(request.referrer or url_for('exam_results_view'))

@app.route('/results/clear', methods=['POST'])
def clear_results():
    term = request.form.get('term', '')
    subject = request.form.get('subject', '')
    grade = request.form.get('grade', '') or session.get('selected_grade', 'All')
    try:
        filter_term = term if term and term != 'All' else None
        filter_sub = subject if subject and subject != 'All' else None
        filter_grade = grade if grade and grade != 'All' else None
        clear_exam_results(exam_term=filter_term, subject=filter_sub, grade=filter_grade)
        flash("Examination results cleared successfully.", "info")
    except Exception as e:
        flash(f"Error clearing results: {str(e)}", "danger")
    return redirect(url_for('exam_results_view', grade=filter_grade))

@app.route('/api/results/export-csv', methods=['GET'])
def export_results_csv():
    grade = request.args.get('grade') or session.get('selected_grade', 'All')
    term = request.args.get('term', '')
    subject = request.args.get('subject', '')
    search = request.args.get('search', '').strip()
    sort_by = request.args.get('sort', 'rank')

    filter_grade = grade if grade and grade != 'All' else None

    results = get_exam_results(
        exam_term=term if term and term != 'All' else None,
        subject=subject if subject and subject != 'All' else None,
        search=search if search else None,
        sort_by=sort_by,
        grade=filter_grade
    )

    si = io.StringIO()
    writer = csv.writer(si)
    # Required order: Student Name, Roll No, Subject, Marks, Rank
    writer.writerow(['Student Name', 'Roll No', 'Class / Grade', 'Subject', 'Marks Obtained', 'Max Marks', 'Rank', 'Grade', 'Exam Term', 'Exam Date'])
    for r in results:
        writer.writerow([
            r['student_name'],
            r['roll_no'],
            r.get('display_grade') or r.get('class_grade') or '',
            r['subject'],
            r['marks_obtained'],
            r['max_marks'],
            r['rank'],
            r['grade'],
            r['exam_term'],
            r['exam_date'] or ''
        ])

    response = make_response(si.getvalue())
    clean_grade = (grade or 'all').replace(' ', '_')
    clean_term = (term or 'results').replace(' ', '_').replace('/', '_')
    response.headers['Content-Disposition'] = f"attachment; filename=exam_results_{clean_grade}_{clean_term}.csv"
    response.headers['Content-Type'] = 'text/csv'
    return response

if __name__ == '__main__':
    print("=======================================================")
    print("  Ash Education Online Camera Capture Attendance System")
    print("  Starting Flask Server at http://127.0.0.1:5000")
    print("=======================================================")
    app.run(host='0.0.0.0', port=5000, debug=True)
