import os
import re
import io
import csv
import pandas as pd

def normalize_text(text):
    if text is None:
        return ""
    return str(text).strip()

def clean_marks(val):
    """Parses marks into a (marks_float, max_float_or_None) tuple always."""
    # Safe isna check that handles non-scalar types (numpy arrays, lists, etc.)
    try:
        is_na = val is None or (not isinstance(val, (list, dict)) and pd.isna(val))
    except (TypeError, ValueError):
        is_na = False
    if is_na:
        return 0.0, None
    s = str(val).strip()
    if not s:
        return 0.0, None
    # Match fractional notation e.g. "95/100"
    m_frac = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*/\s*([0-9]+(?:\.[0-9]+)?)$", s)
    if m_frac:
        return float(m_frac.group(1)), float(m_frac.group(2))
    # Match percentage or plain number e.g. "88%" or "88"
    s_clean = re.sub(r"[^\d.]", "", s)
    try:
        return float(s_clean), None
    except (ValueError, TypeError):
        return 0.0, None

def match_column_key(col_name):
    """Classifies a header column name into canonical keys."""
    if not col_name:
        return None
    c = str(col_name).lower().strip()
    c_clean = re.sub(r"[_\-\s]+", " ", c)

    # Roll Number
    if any(k in c_clean for k in ['roll no', 'roll number', 'rollno', 'roll_no', 'roll #', 'seat no', 'seat', 'roll']):
        return 'roll_no'

    # Student Name
    if any(k in c_clean for k in ['student name', 'candidate name', 'full name', 'student_name', 'name', 'student']):
        return 'student_name'

    # Subject
    if any(k in c_clean for k in ['subject name', 'subject', 'course', 'paper', 'sub']):
        return 'subject'

    # Max Marks
    if any(k in c_clean for k in ['max marks', 'maximum marks', 'out of', 'max_marks', 'total marks', 'max marks']):
        return 'max_marks'

    # Marks
    if any(k in c_clean for k in ['marks obtained', 'marks', 'score', 'mark', 'obtained', 'points', 'total']):
        return 'marks_obtained'

    # Class / Grade
    if any(k in c_clean for k in ['class grade', 'student grade', 'class_grade', 'grade', 'class', 'standard', 'std']):
        return 'class_grade'

    # Term / Exam
    if any(k in c_clean for k in ['exam term', 'exam', 'term', 'examination']):
        return 'exam_term'

    return None

def normalize_grade(val):
    """Normalizes class/grade inputs like '8', '8th', 'class 8', 'grade 8' into 'Grade 8'."""
    if val is None:
        return ""
    # Safe isna check for non-scalar types
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(val).strip()
    if not s:
        return ""
    m = re.match(r"^(?:grade|class|std)?\s*([0-9]+)(?:th|st|nd|rd)?$", s, re.IGNORECASE)
    if m:
        return f"Grade {m.group(1)}"
    return s

def calculate_ranks(records):
    """
    Groups records by (class_grade, exam_term, subject) and assigns competition ranks (1, 2, 2, 4...)
    based on marks_obtained in descending order strictly WITHIN each grade/class.
    8th grade students compete against 8th grade; 10th grade against 10th grade.
    """
    if not records:
        return []

    # Group by (class_grade, exam_term, subject)
    groups = {}
    for idx, r in enumerate(records):
        c_grade = r.get('class_grade') or 'All Classes'
        key = (c_grade, r.get('exam_term') or 'Annual Exam', r.get('subject') or 'General')
        if key not in groups:
            groups[key] = []
        groups[key].append((idx, r))

    ranked_records = list(records)

    for key, items in groups.items():
        # Sort items descending by marks_obtained
        items.sort(key=lambda x: x[1].get('marks_obtained', 0.0), reverse=True)

        current_rank = 1
        for i, (orig_idx, item) in enumerate(items):
            if i > 0:
                prev_marks = items[i - 1][1].get('marks_obtained', 0.0)
                curr_marks = item.get('marks_obtained', 0.0)
                if curr_marks < prev_marks:
                    current_rank = i + 1

            item['rank'] = current_rank
            max_m = item.get('max_marks', 100.0) or 100.0
            pct = (item.get('marks_obtained', 0.0) / max_m) * 100 if max_m > 0 else 0
            
            if pct >= 90: grade = 'A+'
            elif pct >= 80: grade = 'A'
            elif pct >= 70: grade = 'B'
            elif pct >= 60: grade = 'C'
            elif pct >= 50: grade = 'D'
            else: grade = 'F'
            item['grade'] = grade

            ranked_records[orig_idx] = item

    return ranked_records

def link_existing_students(records):
    """
    Attempts to link each record with registered student IDs from the database.
    Matches by roll_no or student_name.
    """
    try:
        from database import get_all_students
        students = get_all_students()
        
        roll_map = {}
        name_map = {}
        for s in students:
            r_str = str(s.get('roll_no', '')).strip().lower()
            if r_str:
                roll_map[r_str] = s
            n_str = str(s.get('full_name', '')).strip().lower()
            if n_str:
                name_map[n_str] = s

        for r in records:
            r_roll = str(r.get('roll_no', '')).strip().lower()
            r_name = str(r.get('student_name', '')).strip().lower()

            matched = roll_map.get(r_roll) or name_map.get(r_name)
            if matched:
                r['student_id'] = matched.get('student_id')
                if not r.get('student_name'):
                    r['student_name'] = matched.get('full_name')
                if not r.get('roll_no'):
                    r['roll_no'] = matched.get('roll_no')
                r['student_photo'] = matched.get('photo_path', '')
                r['student_grade'] = matched.get('grade', '')
                r['student_section'] = matched.get('section', '')
                if not r.get('class_grade') and matched.get('grade'):
                    r['class_grade'] = matched.get('grade')
    except Exception as e:
        print("Notice: student linking skipped:", e)

    return records

def parse_excel_or_csv(file_bytes_or_path, filename="", default_term="Annual Examination 2026", default_subject="General", default_grade=""):
    """
    Parses an Excel (.xlsx, .xls) or CSV file into a list of normalized result dictionaries.
    """
    ext = os.path.splitext(filename)[1].lower() if filename else ".xlsx"
    
    if ext == ".csv":
        if isinstance(file_bytes_or_path, (bytes, bytearray)):
            try:
                df = pd.read_csv(io.BytesIO(file_bytes_or_path), encoding='utf-8')
            except:
                df = pd.read_csv(io.BytesIO(file_bytes_or_path), encoding='latin1')
        else:
            try:
                df = pd.read_csv(file_bytes_or_path, encoding='utf-8')
            except:
                df = pd.read_csv(file_bytes_or_path, encoding='latin1')
    else:
        if isinstance(file_bytes_or_path, (bytes, bytearray)):
            df = pd.read_excel(io.BytesIO(file_bytes_or_path))
        else:
            df = pd.read_excel(file_bytes_or_path)

    # Drop fully empty rows
    df = df.dropna(how='all')
    if df.empty:
        return []

    # Map headers
    col_mapping = {}
    for col in df.columns:
        canonical = match_column_key(col)
        if canonical and canonical not in col_mapping.values():
            col_mapping[col] = canonical

    records = []

    # Check if this is a standard flat table with Marks column
    has_marks_col = any(v == 'marks_obtained' for v in col_mapping.values())

    if has_marks_col:
        # Standard flat format: [Student Name, Roll No, Class/Grade, Subject, Marks]
        for row_idx, (_, row) in enumerate(df.iterrows()):
            name = ""
            roll = ""
            c_grade = default_grade
            subj = default_subject
            marks = 0.0
            max_m = 100.0
            term = default_term

            for orig_col, canon in col_mapping.items():
                val = row[orig_col]
                if canon == 'student_name':
                    name = normalize_text(val)
                elif canon == 'roll_no':
                    roll = normalize_text(val)
                elif canon == 'class_grade':
                    cg = normalize_grade(val)
                    if cg: c_grade = cg
                elif canon == 'subject':
                    s_val = normalize_text(val)
                    if s_val: subj = s_val
                elif canon == 'marks_obtained':
                    m_val, max_opt = clean_marks(val)
                    marks = m_val
                    if max_opt: max_m = max_opt
                elif canon == 'max_marks':
                    try: max_m = float(val)
                    except: pass
                elif canon == 'exam_term':
                    t_val = normalize_text(val)
                    if t_val: term = t_val

            if not name and not roll:
                continue

            if not roll:
                roll = str(row_idx + 1)
            if not name:
                name = f"Student {roll}"

            records.append({
                'student_name': name,
                'roll_no': roll,
                'class_grade': c_grade,
                'subject': subj,
                'marks_obtained': marks,
                'max_marks': max_m,
                'exam_term': term
            })
    else:
        # Multi-subject wide format: [Student Name, Roll No, Class, Math, Science, English...]
        subject_cols = []
        name_col = next((c for c, k in col_mapping.items() if k == 'student_name'), None)
        roll_col = next((c for c, k in col_mapping.items() if k == 'roll_no'), None)
        grade_col = next((c for c, k in col_mapping.items() if k == 'class_grade'), None)

        for col in df.columns:
            if col in [name_col, roll_col, grade_col]:
                continue
            sample_vals = df[col].dropna().head(5)
            if len(sample_vals) > 0 and pd.to_numeric(sample_vals, errors='coerce').notnull().all():
                subject_cols.append(col)

        if not subject_cols and len(df.columns) >= 3:
            name_col = df.columns[0]
            roll_col = df.columns[1]
            subject_cols = [c for c in df.columns[2:] if c != grade_col]

        for row_idx, (_, row) in enumerate(df.iterrows()):
            name = normalize_text(row.get(name_col)) if name_col else ""
            roll = normalize_text(row.get(roll_col)) if roll_col else ""
            c_grade = normalize_grade(row.get(grade_col)) if grade_col else default_grade

            if not name and not roll:
                continue
            if not roll:
                roll = str(row_idx + 1)
            if not name:
                name = f"Student {roll}"

            for sub_col in subject_cols:
                m_val, max_opt = clean_marks(row.get(sub_col))
                records.append({
                    'student_name': name,
                    'roll_no': roll,
                    'class_grade': c_grade,
                    'subject': str(sub_col).strip(),
                    'marks_obtained': m_val,
                    'max_marks': max_opt or 100.0,
                    'exam_term': default_term
                })

    records = link_existing_students(records)
    for r in records:
        if not r.get('class_grade') and default_grade:
            r['class_grade'] = default_grade
    records = calculate_ranks(records)
    return records

def parse_pdf_results(file_bytes_or_path, default_term="Annual Examination 2026", default_subject="General", default_grade=""):
    """
    Extracts examination result tables from a PDF using pdfplumber / PyMuPDF.
    """
    records = []
    detected_grade = default_grade

    # Read PDF tables with pdfplumber
    if isinstance(file_bytes_or_path, (bytes, bytearray)):
        pdf_file = io.BytesIO(file_bytes_or_path)
    else:
        pdf_file = file_bytes_or_path

    try:
        import pdfplumber
        with pdfplumber.open(pdf_file) as pdf:
            all_rows = []
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                # Attempt to detect class/grade from page header text e.g. "Grade 8", "Class 10", "8th Grade"
                if not detected_grade:
                    m_g = re.search(r"\b(?:grade|class|standard|std)\s*[:\-]?\s*([0-9]+(?:th|st|nd|rd)?)\b", page_text, re.IGNORECASE)
                    if m_g:
                        detected_grade = normalize_grade(m_g.group(1))

                tables = page.extract_tables()
                for table in tables:
                    for r in table:
                        if r and any(cell and str(cell).strip() for cell in r):
                            all_rows.append([str(c).strip() if c is not None else "" for c in r])

            if all_rows:
                # Find header row
                header_idx = -1
                for i, row in enumerate(all_rows[:5]):
                    row_keys = [match_column_key(cell) for cell in row]
                    if any(k in ['student_name', 'roll_no', 'marks_obtained', 'subject'] for k in row_keys):
                        header_idx = i
                        break

                if header_idx != -1 and header_idx + 1 < len(all_rows):
                    header = all_rows[header_idx]
                    data_rows = all_rows[header_idx + 1:]
                    
                    df = pd.DataFrame(data_rows, columns=header)
                    col_mapping = {}
                    for col in df.columns:
                        canonical = match_column_key(col)
                        if canonical and canonical not in col_mapping.values():
                            col_mapping[col] = canonical

                    for row_idx, (_, row) in enumerate(df.iterrows()):
                        name = ""
                        roll = ""
                        c_grade = detected_grade or default_grade
                        subj = default_subject
                        marks = 0.0
                        max_m = 100.0

                        for orig_col, canon in col_mapping.items():
                            val = row[orig_col]
                            if canon == 'student_name': name = normalize_text(val)
                            elif canon == 'roll_no': roll = normalize_text(val)
                            elif canon == 'class_grade':
                                cg = normalize_grade(val)
                                if cg: c_grade = cg
                            elif canon == 'subject':
                                s_v = normalize_text(val)
                                if s_v: subj = s_v
                            elif canon == 'marks_obtained':
                                m_v, mx = clean_marks(val)
                                marks = m_v
                                if mx: max_m = mx
                            elif canon == 'max_marks':
                                try: max_m = float(val)
                                except: pass

                        if not name and not roll:
                            continue
                        if not roll: roll = str(row_idx + 1)
                        if not name: name = f"Student {roll}"

                        records.append({
                            'student_name': name,
                            'roll_no': roll,
                            'class_grade': c_grade,
                            'subject': subj,
                            'marks_obtained': marks,
                            'max_marks': max_m,
                            'exam_term': default_term
                        })
    except Exception as pdf_err:
        print("pdfplumber table parse notice:", pdf_err)

    # Fallback: if table parser produced no rows, try regex text parsing with PyMuPDF (fitz)
    if not records:
        try:
            import fitz
            if isinstance(file_bytes_or_path, (bytes, bytearray)):
                doc = fitz.open(stream=file_bytes_or_path, filetype="pdf")
            else:
                doc = fitz.open(file_bytes_or_path)

            full_text = ""
            for page in doc:
                full_text += page.get_text() + "\n"

            if not detected_grade:
                m_g = re.search(r"\b(?:grade|class|standard|std)\s*[:\-]?\s*([0-9]+(?:th|st|nd|rd)?)\b", full_text, re.IGNORECASE)
                if m_g:
                    detected_grade = normalize_grade(m_g.group(1))

            lines = full_text.splitlines()
            for line_idx, line in enumerate(lines):
                line = line.strip()
                if not line: continue
                # Match patterns like: "1  Rajvi  Mathematics  96" or "101  Aarav Sharma  Physics  92"
                m1 = re.search(r"(\d+)\s+([A-Za-z\s]+?)\s+([A-Za-z]+)\s+([0-9]+(?:\.[0-9]+)?)", line)
                if m1:
                    records.append({
                        'roll_no': m1.group(1).strip(),
                        'student_name': m1.group(2).strip(),
                        'class_grade': detected_grade or default_grade,
                        'subject': m1.group(3).strip(),
                        'marks_obtained': float(m1.group(4)),
                        'max_marks': 100.0,
                        'exam_term': default_term
                    })
        except Exception as fitz_err:
            print("PyMuPDF fallback parse notice:", fitz_err)

    records = link_existing_students(records)
    for r in records:
        if not r.get('class_grade') and (detected_grade or default_grade):
            r['class_grade'] = detected_grade or default_grade
    records = calculate_ranks(records)
    return records

def parse_result_file(file_storage_or_path, filename="", default_term="Annual Examination 2026", default_subject="General", default_grade=""):
    """
    Master file router: Accepts file upload or file path, parses into ranked student results.
    """
    if hasattr(file_storage_or_path, 'read'):
        file_bytes = file_storage_or_path.read()
        fname = getattr(file_storage_or_path, 'filename', '') or filename
    elif isinstance(file_storage_or_path, (bytes, bytearray)):
        file_bytes = file_storage_or_path
        fname = filename
    else:
        with open(file_storage_or_path, 'rb') as f:
            file_bytes = f.read()
        fname = os.path.basename(file_storage_or_path) if not filename else filename

    ext = os.path.splitext(fname)[1].lower()

    if ext in ['.xlsx', '.xls', '.csv']:
        return parse_excel_or_csv(file_bytes, filename=fname, default_term=default_term, default_subject=default_subject, default_grade=default_grade)
    elif ext == '.pdf':
        return parse_pdf_results(file_bytes, default_term=default_term, default_subject=default_subject, default_grade=default_grade)
    else:
        raise ValueError(f"Unsupported file format '{ext}'. Please upload an Excel (.xlsx, .xls, .csv) or PDF (.pdf) file.")

def generate_sample_excel_template(target_grade="Grade 10"):
    """
    Creates a pre-formatted Excel workbook (.xlsx) containing realistic sample student results with Grade column.
    """
    try:
        from database import get_all_students
        students = get_all_students()
    except:
        students = []

    rows = []
    if students:
        for s in students:
            rows.append({
                "Student Name": s.get('full_name', ''),
                "Roll No": s.get('roll_no', ''),
                "Class / Grade": s.get('grade', target_grade or 'Grade 10'),
                "Subject": "Mathematics",
                "Marks": 92,
                "Max Marks": 100
            })
    else:
        rows = [
            {"Student Name": "Aarav Sharma", "Roll No": "1", "Class / Grade": target_grade or "Grade 8", "Subject": "Mathematics", "Marks": 95, "Max Marks": 100},
            {"Student Name": "Bhavya Joshi", "Roll No": "2", "Class / Grade": target_grade or "Grade 8", "Subject": "Mathematics", "Marks": 91, "Max Marks": 100},
            {"Student Name": "Chirag Patel", "Roll No": "3", "Class / Grade": target_grade or "Grade 8", "Subject": "Mathematics", "Marks": 88, "Max Marks": 100},
            {"Student Name": "Divya Shah", "Roll No": "4", "Class / Grade": target_grade or "Grade 8", "Subject": "Mathematics", "Marks": 82, "Max Marks": 100}
        ]

    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Exam Results')
    output.seek(0)
    return output.getvalue()
