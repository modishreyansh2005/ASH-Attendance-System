// Ash Education Smart Attendance - Registration JS
document.addEventListener('DOMContentLoaded', () => {
  const video = document.getElementById('reg-webcam');
  const canvas = document.getElementById('reg-canvas');
  const loadingOverlay = document.getElementById('camera-loading-overlay');
  
  const tabWebcam = document.getElementById('tab-webcam');
  const tabUpload = document.getElementById('tab-upload');
  const sectionWebcam = document.getElementById('section-webcam');
  const sectionUpload = document.getElementById('section-upload');

  const btnStartCapture = document.getElementById('btn-start-capture');
  const btnSnapSingle = document.getElementById('btn-snap-single');
  const progressBar = document.getElementById('capture-progress-bar');
  const statusText = document.getElementById('capture-status-text');
  const percentText = document.getElementById('capture-percent');
  const snapGallery = document.getElementById('snap-gallery');
  const capturedFacesInput = document.getElementById('captured_faces_json');
  const form = document.getElementById('student-reg-form');
  const btnSubmit = document.getElementById('btn-submit-registration');

  let stream = null;
  const capturedFrames = [];
  const TARGET_SAMPLES = 5;

  // Initialize Camera with progressive fallback
  async function initWebcam() {
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('MediaDevices not available');
      }

      // Progressive fallback
      let mediaStream = null;
      try {
        mediaStream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
          audio: false
        });
      } catch (e1) {
        try {
          mediaStream = await navigator.mediaDevices.getUserMedia({
            video: { width: { ideal: 640 }, height: { ideal: 480 } },
            audio: false
          });
        } catch (e2) {
          mediaStream = await navigator.mediaDevices.getUserMedia({
            video: true,
            audio: false
          });
        }
      }

      stream = mediaStream;
      video.srcObject = stream;
      try {
        await video.play();
      } catch (playErr) {
        console.warn('Register video play caught:', playErr);
      }
      if (loadingOverlay) loadingOverlay.style.display = 'none';
    } catch (err) {
      console.warn('Webcam access failed:', err);
      if (loadingOverlay) {
        loadingOverlay.innerHTML = `
          <div style="font-size:12px; color:#dc2626; font-weight:600; padding:10px; text-align:center;">
            Camera not accessible (${err.name || 'Error'}).<br>Please use the "Upload Photo File" tab or allow camera permissions.
          </div>
        `;
      }
    }
  }

  // Switch Tabs
  tabWebcam.addEventListener('click', () => {
    tabWebcam.style.background = 'white';
    tabWebcam.style.color = 'var(--primary)';
    tabWebcam.style.fontWeight = '700';

    tabUpload.style.background = 'transparent';
    tabUpload.style.color = 'var(--text-muted)';
    tabUpload.style.fontWeight = '600';

    sectionWebcam.style.display = 'block';
    sectionUpload.style.display = 'none';
  });

  tabUpload.addEventListener('click', () => {
    tabUpload.style.background = 'white';
    tabUpload.style.color = 'var(--primary)';
    tabUpload.style.fontWeight = '700';

    tabWebcam.style.background = 'transparent';
    tabWebcam.style.color = 'var(--text-muted)';
    tabWebcam.style.fontWeight = '600';

    sectionUpload.style.display = 'block';
    sectionWebcam.style.display = 'none';
  });

  function captureFrame() {
    if (!video.videoWidth || !video.videoHeight) return null;
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', 0.90);
  }

  function addSample(dataUrl) {
    if (!dataUrl) return;
    capturedFrames.push(dataUrl);
    capturedFacesInput.value = JSON.stringify(capturedFrames);

    // Update Progress
    const count = capturedFrames.length;
    const pct = Math.min(100, Math.round((count / TARGET_SAMPLES) * 100));
    progressBar.style.width = `${pct}%`;
    percentText.innerText = `${pct}%`;
    statusText.innerText = `${count} of ${TARGET_SAMPLES} Samples Captured`;

    // Add thumbnail
    const thumb = document.createElement('img');
    thumb.src = dataUrl;
    thumb.className = 'snap-thumb';
    thumb.style.animation = 'modalPop 0.2s ease-out';
    snapGallery.appendChild(thumb);
  }

  // Snap 1 manually
  btnSnapSingle.addEventListener('click', () => {
    const frame = captureFrame();
    if (frame) addSample(frame);
  });

  // Automated 5-shot sequence
  btnStartCapture.addEventListener('click', async () => {
    btnStartCapture.disabled = true;
    btnSnapSingle.disabled = true;

    // Reset gallery if already full
    if (capturedFrames.length >= TARGET_SAMPLES) {
      capturedFrames.length = 0;
      snapGallery.innerHTML = '';
      progressBar.style.width = '0%';
      percentText.innerText = '0%';
    }

    const remaining = TARGET_SAMPLES - capturedFrames.length;
    for (let i = 0; i < remaining; i++) {
      statusText.innerText = `Capturing angle ${i + 1} of ${remaining}... Keep steady!`;
      await new Promise(r => setTimeout(r, 450));
      const frame = captureFrame();
      if (frame) addSample(frame);
    }

    statusText.innerText = `All ${TARGET_SAMPLES} Samples Captured & Ready to Train!`;
    statusText.style.color = 'var(--success-text)';
    btnStartCapture.disabled = false;
    btnSnapSingle.disabled = false;
  });

  // Form Submit Loading State
  form.addEventListener('submit', () => {
    btnSubmit.disabled = true;
    btnSubmit.innerHTML = `
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="spin-icon" style="animation:spin 1s linear infinite;">
        <circle cx="12" cy="12" r="10" stroke-opacity="0.25"></circle>
        <path d="M12 2a10 10 0 0 1 10 10" stroke-opacity="1"></path>
      </svg>
      <span>Enrolling Student & Training OpenCV Model...</span>
    `;
  });

  // Start webcam
  initWebcam();
});

// File upload preview & biometric verification handler
async function previewUpload(event) {
  const file = event.target.files && event.target.files[0];
  if (!file) return;

  const dropzone = document.getElementById('upload-dropzone');
  const loadingState = document.getElementById('upload-loading-state');
  const verifiedCard = document.getElementById('upload-verified-card');
  const errorCard = document.getElementById('upload-error-card');
  const annotatedImg = document.getElementById('upload-annotated-img');
  const qualityBadge = document.getElementById('upload-quality-badge');
  const headline = document.getElementById('upload-result-headline');
  const desc = document.getElementById('upload-result-desc');
  const errorTitle = document.getElementById('upload-error-title');
  const errorDesc = document.getElementById('upload-error-desc');
  const capturedFacesInput = document.getElementById('captured_faces_json');
  const btnSubmit = document.getElementById('btn-submit-registration');

  // Show loading spinner
  if (loadingState) loadingState.style.display = 'block';
  if (verifiedCard) verifiedCard.style.display = 'none';
  if (errorCard) errorCard.style.display = 'none';

  try {
    const formData = new FormData();
    formData.append('photo_file', file);

    const response = await fetch('/api/validate-uploaded-photo', {
      method: 'POST',
      body: formData
    });

    const data = await response.json();

    if (loadingState) loadingState.style.display = 'none';

    if (response.ok && data.success) {
      if (verifiedCard) verifiedCard.style.display = 'block';
      if (annotatedImg) annotatedImg.src = data.preview_b64;
      if (qualityBadge) {
        qualityBadge.innerText = `Quality: ${data.quality_score}%`;
        qualityBadge.className = data.quality_score >= 70 ? 'badge badge-present' : 'badge badge-late';
      }
      if (headline) {
        headline.innerText = data.face_count > 1 
          ? `Primary Face Selected (${data.face_count} detected)`
          : `Face Verified for Biometrics ✓`;
      }
      if (desc) {
        desc.innerText = data.message || 'Face validated and ready to train high-accuracy OpenCV attendance model.';
      }

      // Store cropped face sample in captured faces input
      if (capturedFacesInput && data.crop_b64) {
        capturedFacesInput.value = JSON.stringify([data.crop_b64]);
      }
      if (btnSubmit) btnSubmit.disabled = false;
    } else {
      if (errorCard) errorCard.style.display = 'block';
      if (errorTitle) errorTitle.innerText = 'Face Detection Failed';
      if (errorDesc) {
        errorDesc.innerText = data.message || 'Could not find a clear face in this picture. Please ensure the face is facing forward with good lighting.';
      }
      if (capturedFacesInput) capturedFacesInput.value = '';
    }
  } catch (err) {
    console.error('Photo validation error:', err);
    if (loadingState) loadingState.style.display = 'none';
    if (errorCard) {
      errorCard.style.display = 'block';
      if (errorTitle) errorTitle.innerText = 'Validation Network Error';
      if (errorDesc) errorDesc.innerText = 'Could not verify photo. You can still submit and the server will train during enrollment.';
    }
  }
}
