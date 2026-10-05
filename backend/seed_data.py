import os
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from database import init_db, insert_student, record_attendance, get_all_students
from face_engine import PROFILES_DIR, DATASET_DIR, train_face_recognizer
from datetime import date, datetime, timedelta

def create_student_avatar(full_name, student_id, bg_color=(235, 245, 255), text_color=(37, 99, 235)):
    """Create a crisp student avatar with their initials and save to profiles."""
    os.makedirs(PROFILES_DIR, exist_ok=True)
    img_size = (300, 300)
    img = Image.new('RGB', img_size, color=bg_color)
    draw = ImageDraw.Draw(img)

    # Draw soft outer circle
    draw.ellipse([20, 20, 280, 280], outline=text_color, width=4)
    
    # Initials
    parts = full_name.split()
    initials = "".join([p[0].upper() for p in parts[:2]]) if parts else "ST"

    try:
        font = ImageFont.truetype("arial.ttf", 90)
    except:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), initials, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    draw.text(((300 - w) / 2, (290 - h) / 2), initials, fill=text_color, font=font)

    # Draw school badge at bottom
    draw.rectangle([80, 235, 220, 265], fill=text_color)
    try:
        small_font = ImageFont.truetype("arial.ttf", 16)
    except:
        small_font = ImageFont.load_default()
    badge_bbox = draw.textbbox((0, 0), student_id, font=small_font)
    bw = badge_bbox[2] - badge_bbox[0]
    draw.text(((300 - bw) / 2, 242), student_id, fill=(255, 255, 255), font=small_font)

    avatar_path = os.path.join(PROFILES_DIR, f"{student_id}.jpg")
    img.save(avatar_path, quality=95)
    return f"/static/uploads/profiles/{student_id}.jpg"

def seed_database():
    init_db()
    print("Database tables initialized.")

    students_data = [
        {
            "student_id": "STU-1001",
            "full_name": "Aarav Sharma",
            "grade": "Grade 10",
            "section": "A",
            "roll_no": "1001",
            "gender": "Male",
            "guardian_name": "Rajesh Sharma",
            "guardian_phone": "+1 (555) 234-5678",
            "bg": (238, 242, 255),
            "text": (67, 56, 202)
        },
        {
            "student_id": "STU-1002",
            "full_name": "Sophia Martinez",
            "grade": "Grade 10",
            "section": "A",
            "roll_no": "1002",
            "gender": "Female",
            "guardian_name": "Elena Martinez",
            "guardian_phone": "+1 (555) 345-6789",
            "bg": (254, 242, 242),
            "text": (225, 29, 72)
        },
        {
            "student_id": "STU-1003",
            "full_name": "Ethan Walker",
            "grade": "Grade 10",
            "section": "B",
            "roll_no": "1003",
            "gender": "Male",
            "guardian_name": "David Walker",
            "guardian_phone": "+1 (555) 456-7890",
            "bg": (240, 253, 244),
            "text": (22, 163, 74)
        },
        {
            "student_id": "STU-1004",
            "full_name": "Priya Patel",
            "grade": "Grade 9",
            "section": "A",
            "roll_no": "9001",
            "gender": "Female",
            "guardian_name": "Sanjay Patel",
            "guardian_phone": "+1 (555) 567-8901",
            "bg": (254, 243, 199),
            "text": (217, 119, 6)
        },
        {
            "student_id": "STU-1005",
            "full_name": "Lucas Chen",
            "grade": "Grade 9",
            "section": "B",
            "roll_no": "9002",
            "gender": "Male",
            "guardian_name": "Wei Chen",
            "guardian_phone": "+1 (555) 678-9012",
            "bg": (240, 249, 255),
            "text": (2, 132, 199)
        },
        {
            "student_id": "STU-1006",
            "full_name": "Maya Johnson",
            "grade": "Grade 11",
            "section": "A",
            "roll_no": "1101",
            "gender": "Female",
            "guardian_name": "Sarah Johnson",
            "guardian_phone": "+1 (555) 789-0123",
            "bg": (245, 243, 255),
            "text": (124, 58, 237)
        }
    ]

    for stu in students_data:
        photo_url = create_student_avatar(stu["full_name"], stu["student_id"], stu["bg"], stu["text"])
        insert_student(
            student_id=stu["student_id"],
            full_name=stu["full_name"],
            grade=stu["grade"],
            section=stu["section"],
            roll_no=stu["roll_no"],
            gender=stu["gender"],
            guardian_name=stu["guardian_name"],
            guardian_phone=stu["guardian_phone"],
            photo_path=photo_url
        )

    # Seed initial training face samples for seed students
    all_students = get_all_students()
    s_to_db = {s['student_id']: s['id'] for s in all_students}

    for s in all_students:
        s_dir = os.path.join(DATASET_DIR, s['student_id'])
        os.makedirs(s_dir, exist_ok=True)
        for i in range(1, 6):
            face = np.ones((200, 200), dtype=np.uint8) * 175
            cv2.circle(face, (70, 80), 18, 45, -1)
            cv2.circle(face, (130, 80), 18, 45, -1)
            cv2.line(face, (100, 95), (100, 125), 35, 3)
            cv2.ellipse(face, (100, 145), (35, 15), 0, 0, 180, 45, 4)
            noise = np.random.randint(-12, 12, (200, 200), dtype=np.int16)
            face_noisy = np.clip(face.astype(np.int16) + noise, 0, 255).astype(np.uint8)
            cv2.imwrite(os.path.join(s_dir, f'sample_{i}.jpg'), face_noisy)

    # Train model
    ok, msg = train_face_recognizer(s_to_db)
    print(f"Face Model Training: {msg}")

    # Seed some realistic sample attendance logs for today
    today_str = date.today().isoformat()
    now = datetime.now()
    
    record_attendance("STU-1001", "Present", "Camera-OpenCV", 96.4, "Scanned at Main Hallway Camera", today_str, (now - timedelta(minutes=45)).strftime('%H:%M:%S'))
    record_attendance("STU-1002", "Present", "Camera-OpenCV", 94.2, "Scanned at Classroom Entrance", today_str, (now - timedelta(minutes=38)).strftime('%H:%M:%S'))
    record_attendance("STU-1003", "Late", "Manual", 0.0, "Bus transit delay", today_str, (now - timedelta(minutes=15)).strftime('%H:%M:%S'))
    record_attendance("STU-1004", "Present", "Camera-OpenCV", 97.8, "Scanned at Lab Entrance", today_str, (now - timedelta(minutes=10)).strftime('%H:%M:%S'))

    print("Seed students, face datasets, and attendance successfully initialized!")

if __name__ == '__main__':
    seed_database()
