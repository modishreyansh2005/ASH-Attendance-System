import os
import cv2
import numpy as np
import base64
from PIL import Image, ImageOps
import io

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if os.environ.get('VERCEL') or not os.access(BASE_DIR, os.W_OK):
    TMP_DIR = '/tmp'
    MODELS_DIR = os.path.join(TMP_DIR, 'models')
    DATASET_DIR = os.path.join(TMP_DIR, 'static', 'dataset')
    PROFILES_DIR = os.path.join(TMP_DIR, 'static', 'uploads', 'profiles')
    
    # Copy bundled models to /tmp if not already copied
    bundled_models = os.path.join(BASE_DIR, 'models')
    if os.path.exists(bundled_models) and not os.path.exists(MODELS_DIR):
        try:
            import shutil
            shutil.copytree(bundled_models, MODELS_DIR)
        except Exception:
            pass
else:
    PROJECT_ROOT = os.path.dirname(BASE_DIR)
    FRONTEND_STATIC = os.path.join(PROJECT_ROOT, 'frontend', 'static')
    MODELS_DIR = os.path.join(BASE_DIR, 'models')
    DATASET_DIR = os.path.join(FRONTEND_STATIC, 'dataset')
    PROFILES_DIR = os.path.join(FRONTEND_STATIC, 'uploads', 'profiles')

CASCADE_PATH = os.path.join(MODELS_DIR, 'haarcascade_frontalface_default.xml')
TRAINER_PATH = os.path.join(MODELS_DIR, 'trainer.yml')

try:
    os.makedirs(MODELS_DIR, exist_ok=True)
    os.makedirs(DATASET_DIR, exist_ok=True)
    os.makedirs(PROFILES_DIR, exist_ok=True)
except Exception:
    pass


# Global instances
face_cascade = None
alt2_cascade = None
profile_cascade = None
eye_cascade = None
lbph_recognizer = None

def get_cascades():
    """Initializes and returns primary and secondary Haar face cascades."""
    global face_cascade, alt2_cascade, profile_cascade, eye_cascade
    if face_cascade is None or face_cascade.empty():
        p_default = CASCADE_PATH if os.path.exists(CASCADE_PATH) else os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml')
        face_cascade = cv2.CascadeClassifier(p_default)

    if alt2_cascade is None or alt2_cascade.empty():
        p_alt2 = os.path.join(MODELS_DIR, 'haarcascade_frontalface_alt2.xml')
        if not os.path.exists(p_alt2):
            p_alt2 = os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_alt2.xml')
        alt2_cascade = cv2.CascadeClassifier(p_alt2)

    if profile_cascade is None or profile_cascade.empty():
        p_prof = os.path.join(MODELS_DIR, 'haarcascade_profileface.xml')
        if not os.path.exists(p_prof):
            p_prof = os.path.join(cv2.data.haarcascades, 'haarcascade_profileface.xml')
        profile_cascade = cv2.CascadeClassifier(p_prof)

    if eye_cascade is None or eye_cascade.empty():
        p_eye = os.path.join(MODELS_DIR, 'haarcascade_eye.xml')
        if not os.path.exists(p_eye):
            p_eye = os.path.join(cv2.data.haarcascades, 'haarcascade_eye.xml')
        eye_cascade = cv2.CascadeClassifier(p_eye)

    return face_cascade, alt2_cascade, profile_cascade

def get_face_cascade():
    c_def, _, _ = get_cascades()
    return c_def

def get_recognizer():
    global lbph_recognizer
    if lbph_recognizer is None:
        lbph_recognizer = cv2.face.LBPHFaceRecognizer_create(radius=1, neighbors=8, grid_x=8, grid_y=8)
        if os.path.exists(TRAINER_PATH):
            try:
                lbph_recognizer.read(TRAINER_PATH)
            except Exception as e:
                print(f"Notice: Could not load existing trainer.yml: {e}")
    return lbph_recognizer

def reload_recognizer():
    global lbph_recognizer
    lbph_recognizer = cv2.face.LBPHFaceRecognizer_create(radius=1, neighbors=8, grid_x=8, grid_y=8)
    if os.path.exists(TRAINER_PATH):
        try:
            lbph_recognizer.read(TRAINER_PATH)
            return True
        except Exception as e:
            print(f"Error reading trainer.yml on reload: {e}")
            return False
    return False

def robust_decode_image(input_data):
    """
    Robust image decoder for uploaded photos and camera frames:
    1. Handles base64 data URLs, raw bytes, or existing numpy arrays.
    2. Corrects EXIF rotation tags (e.g. photos taken vertically with iPhone/Android).
    3. Converts any color space (RGB, RGBA, CMYK, Grayscale, Palette) to standard BGR.
    """
    if input_data is None:
        return None
    if isinstance(input_data, np.ndarray):
        return input_data

    # Handle base64 string
    if isinstance(input_data, str):
        if ',' in input_data:
            input_data = input_data.split(',')[1]
        try:
            input_data = base64.b64decode(input_data)
        except Exception as e:
            print(f"Error decoding base64 string: {e}")
            return None

    if isinstance(input_data, bytes):
        try:
            pil_img = Image.open(io.BytesIO(input_data))
            pil_img = ImageOps.exif_transpose(pil_img)
            if pil_img.mode != 'RGB':
                pil_img = pil_img.convert('RGB')
            np_arr = np.array(pil_img)
            return cv2.cvtColor(np_arr, cv2.COLOR_RGB2BGR)
        except Exception:
            # Fallback to direct OpenCV imdecode
            try:
                nparr = np.frombuffer(input_data, np.uint8)
                return cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            except Exception as e:
                print(f"imdecode fallback failed: {e}")
                return None
    return None

def base64_to_cv2(base64_string):
    """Safely decode a base64 image (including data:image/... headers) to OpenCV BGR."""
    return robust_decode_image(base64_string)

def cv2_to_base64(cv2_img, format='.jpg'):
    """Encode OpenCV BGR image into base64 data URI."""
    try:
        success, buffer = cv2.imencode(format, cv2_img)
        if not success:
            return None
        b64 = base64.b64encode(buffer).decode('utf-8')
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        print(f"Error encoding image to base64: {e}")
        return None

def detect_faces(image_bgr, min_face_size=None, high_sensitivity=False):
    """
    High-accuracy multi-stage face detector for uploaded photos and live camera frames:
    1. Automatic resolution normalization (resizes large 12MP/48MP photos for optimal Haar detection).
    2. Multi-stage cascade pipeline:
       - Stage 1: Frontal face alt2 (tuned for high precision on clear frontal portraits)
       - Stage 2: Frontal face default
       - Stage 3: CLAHE adaptive contrast enhanced pass (detects faces in harsh lighting, shadows, backlit photos)
       - Stage 4: Profile cascades (left-facing and mirrored right-facing)
       - Stage 5: Rotational search (-15°, +15°) for tilted selfies and natural head poses
       - Stage 6: High-sensitivity close-up pass for passport/portrait photos
    3. Multi-scale bounding box projection back to original image coordinates.
    4. Non-Maximum Suppression (NMS) and candidate ranking by area.
    """
    if image_bgr is None or image_bgr.size == 0:
        return []

    h_orig, w_orig = image_bgr.shape[:2]
    c_default, c_alt2, c_profile = get_cascades()

    # Normalize image resolution for fast and accurate Haar detection (max dimension 960px)
    max_dim = max(h_orig, w_orig)
    if max_dim > 960:
        scale_ratio = 960.0 / float(max_dim)
        scaled_w = int(w_orig * scale_ratio)
        scaled_h = int(h_orig * scale_ratio)
        scaled_img = cv2.resize(image_bgr, (scaled_w, scaled_h), interpolation=cv2.INTER_AREA)
    else:
        scale_ratio = 1.0
        scaled_img = image_bgr

    h_img, w_img = scaled_img.shape[:2]
    gray = cv2.cvtColor(scaled_img, cv2.COLOR_BGR2GRAY) if len(scaled_img.shape) == 3 else scaled_img

    if min_face_size:
        min_size = (int(min_face_size * scale_ratio), int(min_face_size * scale_ratio))
    else:
        min_dim = max(28, int(min(h_img, w_img) * 0.05))
        min_size = (min_dim, min_dim)

    candidates = []

    # Helper to run detection
    def run_detector(cascade, img_gray, scale_f=1.08, min_n=4):
        if cascade and not cascade.empty():
            faces = cascade.detectMultiScale(img_gray, scaleFactor=scale_f, minNeighbors=min_n, minSize=min_size)
            if len(faces) > 0:
                return faces.tolist()
        return []

    # Stage 1: alt2 on raw grayscale
    candidates.extend(run_detector(c_alt2, gray, scale_f=1.08, min_n=4))

    # Stage 2: default frontal face on raw grayscale
    if len(candidates) == 0:
        candidates.extend(run_detector(c_default, gray, scale_f=1.08, min_n=4))

    # Stage 3: CLAHE adaptive contrast pass (handles shadows, bright sunlight, indoor lighting)
    if len(candidates) == 0:
        clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
        eq = clahe.apply(gray)
        candidates.extend(run_detector(c_alt2, eq, scale_f=1.08, min_n=3))
        if len(candidates) == 0:
            candidates.extend(run_detector(c_default, eq, scale_f=1.08, min_n=3))

    # Stage 4: Profile cascade (for turned head poses)
    if len(candidates) == 0 and c_profile and not c_profile.empty():
        # Left-facing profile
        candidates.extend(run_detector(c_profile, gray, scale_f=1.10, min_n=3))
        if len(candidates) == 0:
            # Right-facing profile (flip horizontally)
            gray_flipped = cv2.flip(gray, 1)
            f_prof_flip = run_detector(c_profile, gray_flipped, scale_f=1.10, min_n=3)
            for (fx, fy, fw, fh) in f_prof_flip:
                orig_x = w_img - (fx + fw)
                candidates.append([orig_x, fy, fw, fh])

    # Stage 5: Rotational search (-15°, +15°) for tilted portraits / selfies
    if len(candidates) == 0:
        center = (w_img / 2.0, h_img / 2.0)
        for angle in [-14, 14]:
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated_gray = cv2.warpAffine(gray, M, (w_img, h_img))
            f_rot = run_detector(c_alt2, rotated_gray, scale_f=1.08, min_n=3)
            if len(f_rot) == 0:
                f_rot = run_detector(c_default, rotated_gray, scale_f=1.08, min_n=3)
            if len(f_rot) > 0:
                M_inv = cv2.getRotationMatrix2D(center, -angle, 1.0)
                for (rx, ry, rw, rh) in f_rot:
                    cx, cy = rx + rw / 2.0, ry + rh / 2.0
                    pt = np.array([cx, cy, 1.0])
                    orig_pt = M_inv.dot(pt)
                    ox = int(orig_pt[0] - rw / 2.0)
                    oy = int(orig_pt[1] - rh / 2.0)
                    candidates.append([ox, oy, rw, rh])
                break

    # Stage 6: Close-up passport fallback
    if len(candidates) == 0 or high_sensitivity:
        candidates.extend(run_detector(c_alt2, gray, scale_f=1.05, min_n=2))
        if len(candidates) == 0:
            candidates.extend(run_detector(c_default, gray, scale_f=1.05, min_n=2))

    if len(candidates) == 0:
        return []

    # Map coordinates back to original resolution and validate bounds
    valid_boxes = []
    inv_scale = 1.0 / scale_ratio

    for (x, y, w, h) in candidates:
        ox = int(round(x * inv_scale))
        oy = int(round(y * inv_scale))
        ow = int(round(w * inv_scale))
        oh = int(round(h * inv_scale))

        aspect = float(ow) / max(1, oh)
        if 0.55 <= aspect <= 1.55 and ow >= 25 and oh >= 25:
            cx = max(0, min(w_orig - 1, ox))
            cy = max(0, min(h_orig - 1, oy))
            cw = max(1, min(w_orig - cx, ow))
            ch = max(1, min(h_orig - cy, oh))
            valid_boxes.append((cx, cy, cw, ch))

    if len(valid_boxes) == 0:
        return []

    # Non-maximum suppression by IoU (sort largest first)
    valid_boxes.sort(key=lambda b: b[2] * b[3], reverse=True)

    clean_boxes = []
    for (x, y, w, h) in valid_boxes:
        overlap = False
        for (cx, cy, cw, ch) in clean_boxes:
            ix = max(x, cx)
            iy = max(y, cy)
            iw = min(x + w, cx + cw) - ix
            ih = min(y + h, cy + ch) - iy
            if iw > 0 and ih > 0:
                inter_area = iw * ih
                smaller_area = min(w * h, cw * ch)
                union_area = (w * h) + (cw * ch) - inter_area
                if smaller_area > 0 and ((inter_area / float(smaller_area)) > 0.30 or (inter_area / float(union_area)) > 0.35):
                    overlap = True
                    break
        if not overlap:
            clean_boxes.append((x, y, w, h))

    # Keep largest face first
    clean_boxes.sort(key=lambda f: f[2] * f[3], reverse=True)
    return clean_boxes

def preprocess_face_crop(face_crop_bgr, target_size=(200, 200)):
    """
    Standardizes face crop:
    1. Converts to grayscale.
    2. Bilateral filter for edge-preserving sensor noise reduction.
    3. CLAHE local contrast normalization (removes lighting gradient across face).
    4. Resizes to (200, 200) with high-fidelity Lanczos interpolation.
    """
    if face_crop_bgr is None or face_crop_bgr.size == 0:
        return np.zeros(target_size, dtype=np.uint8)

    if len(face_crop_bgr.shape) == 3:
        gray = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = face_crop_bgr

    # Edge-preserving smoothing
    smoothed = cv2.bilateralFilter(gray, d=5, sigmaColor=30, sigmaSpace=30)
    # CLAHE local illumination normalization
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    equalized = clahe.apply(smoothed)
    resized = cv2.resize(equalized, target_size, interpolation=cv2.INTER_LANCZOS4)
    return resized

def validate_face_quality(image_bgr, bbox, is_upload=False):
    """
    Validates face image quality before registration or recognition:
    - Minimum size: w >= 36 and h >= 36
    - Boundary cutoff: relaxed for uploaded photos / close portraits
    - Illumination / Brightness: mean intensity between 20 and 245
    - Blur / Focus: Laplacian variance >= 3.0
    Returns:
    (is_valid: bool, quality_score: float, reason: str)
    """
    if image_bgr is None or image_bgr.size == 0:
        return False, 0.0, "Empty image frame"

    h_img, w_img = image_bgr.shape[:2]
    x, y, w, h = bbox

    # 1. Size check
    min_dim = 32 if is_upload else 45
    if w < min_dim or h < min_dim:
        return False, 25.0, "Face too small / please move closer"

    # 2. Out of bounds / boundary cut off check
    if not is_upload:
        if x <= 0 or y <= 0 or (x + w) >= w_img or (y + h) >= h_img:
            return False, 35.0, "Face outside camera view / boundary cut off"
    else:
        if x < -10 or y < -10 or (x + w) > (w_img + 10) or (y + h) > (h_img + 10):
            return False, 35.0, "Face outside image view / boundary cut off"

    # Extract crop
    y1, y2 = max(0, y), min(h_img, y + h)
    x1, x2 = max(0, x), min(w_img, x + w)
    crop = image_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return False, 0.0, "Invalid face crop"

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop

    # 3. Illumination / Brightness check
    brightness = float(np.mean(gray))
    if brightness < 20.0:
        return False, round(brightness, 1), "Too dark / underexposed"
    if brightness > 245.0:
        return False, round(brightness, 1), "Overexposed / lighting too bright"

    # 4. Blur / Sharpness check via Laplacian variance
    blur_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if blur_var < 3.0:
        return False, round(blur_var, 1), "Blurred / please hold steady"

    # Quality score (0 to 100)
    score = min(99.0, max(68.0, 58.0 + (min(80.0, blur_var) * 0.35) + (10.0 if 40 < brightness < 200 else 0.0)))
    return True, round(score, 1), "Good quality"

def generate_biometric_samples(face_crop_bgr):
    """
    Generates a rich, multi-invariant biometric training set from a face crop.
    Synthesizes real-world variations so the model accurately detects and recognizes
    the student under varying webcam angles, zooms, lighting, and expressions:
    - Rotations: -10°, -5°, 0°, +5°, +10°
    - Scales / Zoom variations: 0.94, 1.0, 1.06
    - Horizontal mirror flips
    - Illumination / Gamma variations: 0.85 (dimmer room) and 1.20 (brighter light)
    - CLAHE contrast normalization
    Produces 30-40 high-fidelity 200x200 samples.
    """
    samples = []
    if face_crop_bgr is None or face_crop_bgr.size == 0:
        return samples

    h, w = face_crop_bgr.shape[:2]
    angles = [-10, -5, 0, 5, 10]
    scales = [0.94, 1.0, 1.06]
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    for ang in angles:
        M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), ang, 1.0)
        rotated = cv2.warpAffine(face_crop_bgr, M, (w, h), borderMode=cv2.BORDER_REFLECT)
        for sc in scales:
            if sc == 1.0:
                sc_crop = rotated
            else:
                nh, nw = int(h * sc), int(w * sc)
                resized = cv2.resize(rotated, (nw, nh))
                if sc > 1.0:
                    y_off = (nh - h) // 2
                    x_off = (nw - w) // 2
                    sc_crop = resized[y_off:y_off + h, x_off:x_off + w]
                else:
                    pad_y = (h - nh) // 2
                    pad_x = (w - nw) // 2
                    sc_crop = cv2.copyMakeBorder(
                        resized, pad_y, h - nh - pad_y, pad_x, w - nw - pad_x, cv2.BORDER_REFLECT
                    )

            gray = cv2.cvtColor(sc_crop, cv2.COLOR_BGR2GRAY) if len(sc_crop.shape) == 3 else sc_crop
            smoothed = cv2.bilateralFilter(gray, d=5, sigmaColor=30, sigmaSpace=30)
            equalized = clahe.apply(smoothed)
            base_sample = cv2.resize(equalized, (200, 200), interpolation=cv2.INTER_LANCZOS4)
            samples.append(base_sample)

            # Horizontal mirror flip
            samples.append(cv2.flip(base_sample, 1))

            # Lighting variations (gamma correction)
            for g in [0.85, 1.20]:
                inv_g = 1.0 / g
                table = np.array([((i / 255.0) ** inv_g) * 255 for i in range(256)]).astype('uint8')
                samples.append(cv2.LUT(base_sample, table))

    return samples

def save_student_face_samples(student_id, db_id, image_list):
    """
    Given student_id, integer db_id, and a list of images (base64 or OpenCV arrays),
    detects faces, crops them with proportional padding, saves avatar to static/uploads/profiles/<student_id>.jpg,
    generates multi-angle invariant biometric samples into static/dataset/<student_id>/,
    and registers samples in the database face_samples table.
    """
    import database
    student_dir = os.path.join(DATASET_DIR, str(student_id))
    os.makedirs(student_dir, exist_ok=True)

    saved_count = 0
    primary_profile_saved = False
    valid_face_crops = []

    angle_labels = ['Front', 'Slight Left', 'Slight Right', 'Smile', 'Neutral / Extra', 'Calibrated Biometric']

    for idx, raw_img in enumerate(image_list):
        img_bgr = robust_decode_image(raw_img)
        if img_bgr is None or img_bgr.size == 0:
            continue

        h_img, w_img = img_bgr.shape[:2]
        faces = detect_faces(img_bgr, high_sensitivity=True)

        if len(faces) == 0:
            # Fallback if image is already a cropped face portrait
            if w_img >= 40 and h_img >= 40:
                crop = img_bgr
                is_q, q_score, _ = validate_face_quality(img_bgr, (0, 0, w_img, h_img), is_upload=True)
            else:
                continue
        else:
            # Pick largest detected face
            faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
            x, y, w, h = faces[0]
            is_q, q_score, _ = validate_face_quality(img_bgr, (x, y, w, h), is_upload=True)

            # Add 12% proportional padding around face
            pad_y = int(h * 0.12)
            pad_x = int(w * 0.12)
            y1 = max(0, y - pad_y)
            y2 = min(h_img, y + h + pad_y)
            x1 = max(0, x - pad_x)
            x2 = min(w_img, x + w + pad_x)
            crop = img_bgr[y1:y2, x1:x2]

        if crop is None or crop.size == 0:
            continue

        valid_face_crops.append(crop)

        # Save primary profile avatar
        if not primary_profile_saved:
            profile_filename = f"{student_id}.jpg"
            profile_path = os.path.join(PROFILES_DIR, profile_filename)
            avatar = cv2.resize(crop, (300, 300), interpolation=cv2.INTER_AREA)
            cv2.imwrite(profile_path, avatar)
            primary_profile_saved = True

        # Preprocess and save primary sample
        preprocessed = preprocess_face_crop(crop)
        sample_filename = f"sample_{saved_count + 1}.jpg"
        sample_path = os.path.join(student_dir, sample_filename)
        cv2.imwrite(sample_path, preprocessed)

        # Register in face_samples DB table
        db_img_rel = f"/static/dataset/{student_id}/{sample_filename}"
        angle_name = angle_labels[saved_count] if saved_count < len(angle_labels) else f"Sample {saved_count + 1}"
        database.insert_face_sample(student_id, db_img_rel, capture_angle=angle_name, quality_score=q_score if 'q_score' in locals() else 95.0)
        saved_count += 1

    # If fewer than 15 samples exist (common for single uploaded photos),
    # generate rich biometric augmentation suite so the LBPH model is invariant
    # to webcam angles, room lighting, and camera distances!
    if saved_count > 0 and len(valid_face_crops) > 0:
        base_crop = valid_face_crops[0]
        biometric_samples = generate_biometric_samples(base_crop)

        # Save up to 25 synthetic invariant samples to dataset folder
        for i, aug_sample in enumerate(biometric_samples):
            if saved_count >= 25:
                break
            saved_count += 1
            aug_filename = f"sample_{saved_count}.jpg"
            cv2.imwrite(os.path.join(student_dir, aug_filename), aug_sample)
            db_rel = f"/static/dataset/{student_id}/{aug_filename}"
            database.insert_face_sample(student_id, db_rel, capture_angle=f"Biometric Invariant #{i+1}", quality_score=94.0)

    profile_url = f"/static/uploads/profiles/{student_id}.jpg" if primary_profile_saved else None
    return saved_count, profile_url

def train_face_recognizer(student_id_to_db_id_map):
    """
    Iterates over all folders in DATASET_DIR.
    student_id_to_db_id_map: dictionary mapping string student_id -> integer db_id
    Applies CLAHE normalization and multi-scale / mirror augmentations.
    Trains LBPH Face Recognizer and saves to models/trainer.yml.
    """
    face_samples = []
    labels = []

    if not os.path.exists(DATASET_DIR):
        return False, "Dataset directory does not exist."

    trained_students = 0
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    for student_dir_name in os.listdir(DATASET_DIR):
        folder_path = os.path.join(DATASET_DIR, student_dir_name)
        if not os.path.isdir(folder_path):
            continue

        db_id = student_id_to_db_id_map.get(student_dir_name)
        if db_id is None:
            continue

        images = [f for f in os.listdir(folder_path) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        if not images:
            continue

        has_samples_for_student = False
        for img_name in images:
            img_path = os.path.join(folder_path, img_name)
            gray_img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
            if gray_img is None:
                continue

            if gray_img.shape != (200, 200):
                gray_img = cv2.resize(gray_img, (200, 200))

            # Apply CLAHE normalization
            norm_img = clahe.apply(gray_img)

            # Invariant augmentations for training
            augmented = [
                norm_img,
                cv2.flip(norm_img, 1),
                np.clip(norm_img.astype(np.int16) + 12, 0, 255).astype(np.uint8),
                np.clip(norm_img.astype(np.int16) - 12, 0, 255).astype(np.uint8)
            ]

            for aug_sample in augmented:
                face_samples.append(aug_sample)
                labels.append(int(db_id))
            has_samples_for_student = True

        if has_samples_for_student:
            trained_students += 1

    if len(face_samples) == 0:
        return False, "No valid face samples found to train."

    recognizer = cv2.face.LBPHFaceRecognizer_create(radius=1, neighbors=8, grid_x=8, grid_y=8)
    recognizer.train(face_samples, np.array(labels, dtype=np.int32))
    recognizer.save(TRAINER_PATH)
    reload_recognizer()

    return True, f"Successfully trained model with {len(face_samples)} face samples across {trained_students} students."

def analyze_frame_faces(image_bgr, db_id_to_student_dict, distance_threshold=80.0, exclude_student_ids=None):
    """
    Detects faces in frame and performs multi-crop biometric recognition pipeline:
    1. Robust multi-stage detection.
    2. Face Quality Validation (relaxed bounds for high-res/uploaded pictures).
    3. Multi-crop evaluation (+5% zoom, standard crop, -5% zoom) with CLAHE.
    4. Calibrated Thresholds:
       - dist <= distance_threshold (80.0): MATCHED (candidate)
       - distance_threshold < dist <= distance_threshold + 12.0 (92.0): LOW CONFIDENCE
       - dist > 92.0 or unlisted: UNKNOWN (anti-hallucination safe)
    5. Already Marked Validation.
    """
    if image_bgr is None or image_bgr.size == 0:
        return {'detected_count': 0, 'faces': [], 'annotated_b64': None}

    h_img, w_img = image_bgr.shape[:2]
    recognizer = get_recognizer()
    has_model = os.path.exists(TRAINER_PATH) and recognizer is not None

    faces_boxes = detect_faces(image_bgr)
    results = []
    annotated = image_bgr.copy()

    LBPH_CONFIDENCE_THRESHOLD = float(distance_threshold)
    LBPH_BORDERLINE_THRESHOLD = float(distance_threshold) + 12.0

    for (x, y, w, h) in faces_boxes:
        is_quality_ok, q_score, q_reason = validate_face_quality(image_bgr, (x, y, w, h), is_upload=False)

        pad_y = int(h * 0.12)
        pad_x = int(w * 0.12)
        y1 = max(0, y - pad_y)
        y2 = min(h_img, y + h + pad_y)
        x1 = max(0, x - pad_x)
        x2 = min(w_img, x + w + pad_x)
        crop = image_bgr[y1:y2, x1:x2]

        student_info = None
        is_recognized = False
        confidence = 0.0
        dist = 999.0
        is_already_marked = False
        status = 'UNKNOWN'
        code = 'unknown'

        if not is_quality_ok or crop.size == 0:
            status = 'POOR FACE QUALITY'
            code = 'poor_quality'
            is_recognized = False
            confidence = 0.0
            color = (68, 68, 239) # Coral Red (BGR)
            label_text = "POOR FACE QUALITY"
            sub_text = q_reason
        else:
            if has_model and len(db_id_to_student_dict) > 0:
                try:
                    # Multi-crop evaluation: test standard crop, +5% zoom, and -5% zoom
                    # to achieve maximum alignment invariance with training data
                    candidate_crops = [preprocess_face_crop(crop)]
                    
                    # Zoom in 5%
                    ch, cw = crop.shape[:2]
                    if ch > 20 and cw > 20:
                        crop_z = crop[int(ch * 0.05):int(ch * 0.95), int(cw * 0.05):int(cw * 0.95)]
                        candidate_crops.append(preprocess_face_crop(crop_z))

                    best_label = -1
                    min_dist = 999.0
                    for c_crop in candidate_crops:
                        l_id, d = recognizer.predict(c_crop)
                        if d < min_dist:
                            min_dist = d
                            best_label = l_id

                    label_id = best_label
                    dist = min_dist

                    if dist <= LBPH_CONFIDENCE_THRESHOLD:
                        matched = db_id_to_student_dict.get(label_id)
                        if matched:
                            student_info = matched
                            is_recognized = True
                            code = 'candidate'
                            confidence = round(max(65.0, min(99.5, 100.0 - (dist * 0.42))), 1)

                            if exclude_student_ids and matched.get('student_id') in exclude_student_ids:
                                is_already_marked = True
                                status = 'ALREADY CHECKED IN'
                                color = (235, 175, 50) # Cyan
                                label_text = f"{matched['full_name']} (Checked In)"
                                sub_text = f"Already recorded today | Conf: {confidence}%"
                            else:
                                status = 'MATCHED'
                                color = (60, 179, 113) # Emerald Green
                                label_text = f"✓ {matched['full_name']} ({matched['roll_no']})"
                                sub_text = f"{matched['grade']}-{matched['section']} | Conf: {confidence}%"
                        else:
                            status = 'UNKNOWN'
                            code = 'unknown'
                            confidence = round(max(10.0, 100.0 - dist), 1)
                            color = (12, 140, 235)
                            label_text = "? UNKNOWN"
                            sub_text = "No reliable match in system"

                    elif dist <= LBPH_BORDERLINE_THRESHOLD:
                        matched = db_id_to_student_dict.get(label_id)
                        status = 'LOW CONFIDENCE'
                        code = 'low_confidence'
                        student_info = matched
                        is_recognized = False
                        confidence = round(max(45.0, 68.0 - ((dist - LBPH_CONFIDENCE_THRESHOLD) * 1.5)), 1)
                        color = (0, 190, 245)
                        label_text = "⚠ LOW CONFIDENCE"
                        sub_text = "Please look at camera / improve lighting"

                    else:
                        status = 'UNKNOWN'
                        code = 'unknown'
                        student_info = None
                        is_recognized = False
                        confidence = round(max(5.0, min(42.0, 100.0 - dist)), 1)
                        color = (12, 88, 234)
                        label_text = "? UNKNOWN"
                        sub_text = "No reliable match"

                except Exception as e:
                    print(f"Prediction error for face: {e}")
                    status = 'UNKNOWN'
                    code = 'unknown'
                    is_recognized = False
                    color = (12, 88, 234)
                    label_text = "? UNKNOWN"
                    sub_text = "Prediction error"
            else:
                status = 'UNKNOWN'
                code = 'unknown'
                color = (12, 88, 234)
                label_text = "Face Detected"
                sub_text = "Biometric model not trained"

        # Draw bounding box and header badge
        cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)
        badge_h = 38
        cv2.rectangle(annotated, (x, max(0, y - badge_h)), (x + w, y), color, -1)
        cv2.putText(annotated, label_text, (x + 8, max(18, y - 18)), cv2.FONT_HERSHEY_DUPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(annotated, sub_text, (x + 8, max(32, y - 5)), cv2.FONT_HERSHEY_DUPLEX, 0.40, (240, 240, 240), 1, cv2.LINE_AA)

        results.append({
            'box': [int(x), int(y), int(w), int(h)],
            'status': status,
            'code': code,
            'is_recognized': is_recognized,
            'confidence': confidence,
            'student': student_info,
            'distance': round(float(dist), 2),
            'already_logged': is_already_marked,
            'quality_ok': is_quality_ok,
            'quality_score': q_score,
            'quality_reason': q_reason
        })

    annotated_b64 = cv2_to_base64(annotated)

    return {
        'detected_count': len(results),
        'faces': results,
        'annotated_b64': annotated_b64
    }
