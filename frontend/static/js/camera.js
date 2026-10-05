// Ash Education Smart Attendance - Live Camera Hub JS
document.addEventListener('DOMContentLoaded', () => {
  const video = document.getElementById('webcam-video');
  const canvas = document.getElementById('overlay-canvas');
  const ctx = canvas.getContext('2d');
  
  const statusLabel = document.getElementById('camera-status-label');
  const btnToggleScan = document.getElementById('btn-toggle-scan');
  const scanToggleText = document.getElementById('scan-toggle-text');
  const btnSnapAttendance = document.getElementById('btn-snap-attendance');
  const btnSoundToggle = document.getElementById('btn-sound-toggle');
  const soundLabel = document.getElementById('sound-label');
  const cameraFallback = document.getElementById('camera-fallback');
  const btnRequestCamera = document.getElementById('btn-request-camera');
  const btnCameraText = document.getElementById('btn-camera-text');
  const cameraFallbackTitle = document.getElementById('camera-fallback-title');
  const cameraFallbackDesc = document.getElementById('camera-fallback-desc');
  const cameraFallbackAlert = document.getElementById('camera-fallback-alert');
  const btnReloadCamera = document.getElementById('btn-reload-camera');
  const btnGotoLocalhost = document.getElementById('btn-goto-localhost');
  const btnDemoSimulate = document.getElementById('btn-demo-simulate');
  const btnRetrain = document.getElementById('btn-retrain-camera');
  const btnUploadPhoto = document.getElementById('btn-upload-photo');
  const inputUploadPhoto = document.getElementById('input-upload-photo');
  const staticPictureView = document.getElementById('static-picture-view');
  const btnBackLive = document.getElementById('btn-back-live');

  // Feedback Card Elements
  const verifiedCard = document.getElementById('verified-card');
  const recognizedAvatar = document.getElementById('recognized-avatar');
  const recognizedName = document.getElementById('recognized-name');
  const recognizedMeta = document.getElementById('recognized-meta');
  const recognitionBannerTag = document.getElementById('recognition-banner-tag');
  const recognitionTimeBadge = document.getElementById('recognition-time-badge');
  const recognitionConfTag = document.getElementById('recognition-confidence-tag');
  const confBadgeText = document.getElementById('conf-badge-text');

  // Verification Progress Bar (Section 2.2)
  const verificationProgressContainer = document.getElementById('verification-progress-container');
  const verificationProgressBar = document.getElementById('verification-progress-bar');
  const verificationProgressPercent = document.getElementById('verification-progress-percent');

  // Audit Log Modal (Section 11)
  const btnOpenAudit = document.getElementById('btn-open-audit');
  const auditModal = document.getElementById('audit-modal');
  const auditLogsTbody = document.getElementById('audit-logs-tbody');
  const auditUnknownStat = document.getElementById('audit-unknown-stat');

  // Feed list
  const feedList = document.getElementById('attendance-feed-list');
  const liveCountBadge = document.getElementById('live-count-badge');
  const emptyPlaceholder = document.getElementById('empty-feed-placeholder');

  let stream = null;
  let isScanning = true;
  let isProcessingFrame = false;
  let audioEnabled = true;
  let audioCtx = null;
  let scanTimer = null;
  let resetTimer = null;

  // 30-Second Cooldown & Multi-Frame Confirmation Tracker (Section 2.2 & 2.8)
  const REQUIRED_CONFIRMATIONS = 3;
  const COOLDOWN_DURATION_MS = 30000;
  const recentAttendanceLog = new Map(); // student_id -> last_marked_timestamp

  const multiFrameTracker = {
    candidateId: null,
    candidateStudent: null,
    consecutiveCount: 0,
    targetCount: REQUIRED_CONFIRMATIONS,
    emptyFrames: 0
  };


  // Web Audio Chime Synthesizer
  function playSuccessChime() {
    if (!audioEnabled) return;
    try {
      if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (audioCtx.state === 'suspended') {
        audioCtx.resume();
      }

      const now = audioCtx.currentTime;
      // Tone 1: E5
      const osc1 = audioCtx.createOscillator();
      const gain1 = audioCtx.createGain();
      osc1.type = 'sine';
      osc1.frequency.setValueAtTime(659.25, now);
      gain1.gain.setValueAtTime(0.2, now);
      gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.35);
      osc1.connect(gain1);
      gain1.connect(audioCtx.destination);
      osc1.start(now);
      osc1.stop(now + 0.35);

      // Tone 2: B5 (cheerful harmonic chime)
      const osc2 = audioCtx.createOscillator();
      const gain2 = audioCtx.createGain();
      osc2.type = 'sine';
      osc2.frequency.setValueAtTime(987.77, now + 0.12);
      gain2.gain.setValueAtTime(0.25, now + 0.12);
      gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.55);
      osc2.connect(gain2);
      gain2.connect(audioCtx.destination);
      osc2.start(now + 0.12);
      osc2.stop(now + 0.55);
    } catch (e) {
      console.log('Audio chime error:', e);
    }
  }

  // Helper to request media stream with progressive constraints fallback
  async function acquireMediaStream() {
    const isLocal = window.location.hostname === 'localhost' ||
                    window.location.hostname === '127.0.0.1' ||
                    window.location.hostname === '[::1]';

    // 1. Check for insecure origin blocking mediaDevices
    if (!window.isSecureContext && !isLocal && (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)) {
      const err = new Error('Insecure Context: Camera access requires HTTPS or localhost');
      err.name = 'InsecureContextError';
      throw err;
    }

    // 2. Modern MediaDevices API
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      // Progressive fallback constraints
      const constraintCandidates = [
        // Candidate 1: High quality 640x480 user-facing
        { video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }, audio: false },
        // Candidate 2: Resolution only (handles webcams that reject facingMode)
        { video: { width: { ideal: 640 }, height: { ideal: 480 } }, audio: false },
        // Candidate 3: Basic video true (broadest device driver compatibility)
        { video: true, audio: false }
      ];

      let lastError = null;
      for (const constraints of constraintCandidates) {
        try {
          const mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
          if (mediaStream) return mediaStream;
        } catch (e) {
          lastError = e;
          // If browser specifically blocked permissions or webcam is locked/absent, break early to show instructions
          if (e.name === 'NotAllowedError' || e.name === 'PermissionDeniedError' ||
              e.name === 'NotReadableError' || e.name === 'TrackStartError' ||
              e.name === 'NotFoundError' || e.name === 'DevicesNotFoundError') {
            throw e;
          }
          console.warn('Media constraint attempt failed:', constraints, e);
        }
      }
      throw lastError || new Error('Failed to acquire webcam stream');
    }

    // 3. Legacy navigator.getUserMedia API fallback
    const legacyGetUserMedia = navigator.getUserMedia ||
                               navigator.webkitGetUserMedia ||
                               navigator.mozGetUserMedia ||
                               navigator.msGetUserMedia;
    if (legacyGetUserMedia) {
      return new Promise((resolve, reject) => {
        legacyGetUserMedia.call(navigator, { video: true, audio: false }, resolve, reject);
      });
    }

    const unsupportedErr = new Error('Camera API is not supported by your browser');
    unsupportedErr.name = 'NotSupportedError';
    throw unsupportedErr;
  }

  // Camera Initialization
  async function initCamera(userInitiated = false) {
    if (userInitiated && btnRequestCamera) {
      btnRequestCamera.disabled = true;
      if (btnCameraText) btnCameraText.innerText = 'Requesting Camera Access...';
    }

    try {
      stream = await acquireMediaStream();

      video.srcObject = stream;
      
      // Ensure video plays
      try {
        await video.play();
      } catch (playErr) {
        console.warn('Video play triggered:', playErr);
      }

      if (cameraFallback) cameraFallback.style.display = 'none';
      if (statusLabel) statusLabel.innerText = 'Camera Online & Scanning';
      
      matchCanvasDimensions();
      startContinuousScan();

      if (btnRequestCamera) {
        btnRequestCamera.disabled = false;
        if (btnCameraText) btnCameraText.innerText = 'Grant Camera Permission';
      }
      if (cameraFallbackAlert) cameraFallbackAlert.style.display = 'none';
    } catch (err) {
      console.warn('Camera could not be accessed:', err);
      handleCameraError(err, userInitiated);
    }
  }

  function handleCameraError(err, userInitiated) {
    if (cameraFallback) cameraFallback.style.display = 'flex';
    if (statusLabel) statusLabel.innerText = 'Camera Inactive';

    if (btnRequestCamera) {
      btnRequestCamera.disabled = false;
      if (btnCameraText) btnCameraText.innerText = 'Retry Camera Access';
    }

    const isLocal = window.location.hostname === 'localhost' ||
                    window.location.hostname === '127.0.0.1' ||
                    window.location.hostname === '[::1]';

    // Case 1: Insecure Origin (LAN IP without HTTPS)
    if (err.name === 'InsecureContextError' || (!window.isSecureContext && !isLocal)) {
      if (cameraFallbackTitle) cameraFallbackTitle.innerText = 'Browser Security Restriction';
      if (cameraFallbackDesc) cameraFallbackDesc.innerText = 'Modern browsers (Chrome, Edge, Firefox) disable camera access on non-secure IP addresses.';
      if (cameraFallbackAlert) {
        cameraFallbackAlert.style.display = 'block';
        cameraFallbackAlert.style.background = '#eff6ff';
        cameraFallbackAlert.style.border = '1px solid #bfdbfe';
        cameraFallbackAlert.style.color = '#1e40af';
        const port = window.location.port ? `:${window.location.port}` : '';
        cameraFallbackAlert.innerHTML = `
          <strong>💡 Solution for Camera Access:</strong><br>
          You are viewing via a network IP. Chrome/Edge will immediately allow camera access if you open the system using <strong>localhost</strong> or <strong>127.0.0.1</strong>.
        `;
      }
      if (btnGotoLocalhost) {
        const port = window.location.port ? `:${window.location.port}` : '';
        btnGotoLocalhost.href = `http://127.0.0.1${port}/camera`;
        btnGotoLocalhost.style.display = 'inline-flex';
      }
      return;
    }

    // Case 2: Blocked / Denied in browser settings
    if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
      if (cameraFallbackTitle) cameraFallbackTitle.innerText = 'Camera Permission Blocked';
      if (cameraFallbackDesc) cameraFallbackDesc.innerText = 'Camera access was previously denied or blocked in your browser settings.';
      if (cameraFallbackAlert) {
        cameraFallbackAlert.style.display = 'block';
        cameraFallbackAlert.style.background = '#fef2f2';
        cameraFallbackAlert.style.border = '1px solid #fecaca';
        cameraFallbackAlert.style.color = '#991b1b';
        cameraFallbackAlert.innerHTML = `
          <strong>🔧 How to unblock camera in your browser:</strong>
          <ol style="margin:8px 0 0 16px; padding:0; line-height:1.6;">
            <li>Look at the <strong>address bar</strong> at the very top of your browser.</li>
            <li>Click the <strong>lock icon 🔒</strong> (or site settings / tune icon) to the left of the URL.</li>
            <li>Find <strong>Camera</strong> and toggle it from <em>Block</em> to <strong>Allow</strong>.</li>
            <li>Click the <strong>Reload Page</strong> button below.</li>
          </ol>
        `;
      }
      if (btnReloadCamera) {
        btnReloadCamera.style.display = 'inline-flex';
      }
      return;
    }

    // Case 3: In Use / Locked by another application
    if (err.name === 'NotReadableError' || err.name === 'TrackStartError') {
      if (cameraFallbackTitle) cameraFallbackTitle.innerText = 'Webcam Locked / In Use';
      if (cameraFallbackDesc) cameraFallbackDesc.innerText = 'Your webcam hardware is currently locked or in use by another application.';
      if (cameraFallbackAlert) {
        cameraFallbackAlert.style.display = 'block';
        cameraFallbackAlert.style.background = '#fffbeb';
        cameraFallbackAlert.style.border = '1px solid #fde68a';
        cameraFallbackAlert.style.color = '#92400e';
        cameraFallbackAlert.innerHTML = `
          <strong>⚠️ Camera Hardware In Use:</strong><br>
          Please close any open video conferencing tools (Zoom, Microsoft Teams, Skype, Google Meet) or other browser tabs that may be using the camera, then click <strong>Retry Camera Access</strong>.
        `;
      }
      return;
    }

    // Case 4: No Camera Device Found
    if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
      if (cameraFallbackTitle) cameraFallbackTitle.innerText = 'No Webcam Detected';
      if (cameraFallbackDesc) cameraFallbackDesc.innerText = 'No video capture hardware was detected on your machine.';
      if (cameraFallbackAlert) {
        cameraFallbackAlert.style.display = 'block';
        cameraFallbackAlert.style.background = '#fef2f2';
        cameraFallbackAlert.style.border = '1px solid #fecaca';
        cameraFallbackAlert.style.color = '#991b1b';
        cameraFallbackAlert.innerHTML = `
          <strong>🔌 Connect Webcam:</strong><br>
          Please connect a USB webcam or ensure your laptop's integrated camera is enabled, then click <strong>Retry Camera Access</strong>.
        `;
      }
      return;
    }

    // Case 5: General error
    if (userInitiated) {
      if (cameraFallbackAlert) {
        cameraFallbackAlert.style.display = 'block';
        cameraFallbackAlert.style.background = '#fef2f2';
        cameraFallbackAlert.style.border = '1px solid #fecaca';
        cameraFallbackAlert.style.color = '#991b1b';
        cameraFallbackAlert.innerHTML = `<strong>Camera Notice:</strong> ${err.message || 'Camera permission could not be acquired.'}`;
      }
    }
  }

  function matchCanvasDimensions() {
    const isStatic = staticPictureView && staticPictureView.style.display !== 'none';
    const targetEl = isStatic ? staticPictureView : video;
    const rect = targetEl.getBoundingClientRect();
    if (rect.width && rect.height) {
      canvas.width = rect.width;
      canvas.height = rect.height;
    } else {
      canvas.width = 640;
      canvas.height = 480;
    }
  }

  window.addEventListener('resize', matchCanvasDimensions);
  if (video) {
    video.addEventListener('loadedmetadata', matchCanvasDimensions);
    video.addEventListener('canplay', matchCanvasDimensions);
  }

  // Capture frame as Base64 JPEG optimized for ultra-fast instant detection
  function captureCurrentFrameBase64() {
    if (!video.videoWidth || !video.videoHeight) return null;

    const maxDim = 640;
    let targetW = video.videoWidth;
    let targetH = video.videoHeight;
    if (targetW > maxDim) {
      targetH = Math.round((maxDim / targetW) * targetH);
      targetW = maxDim;
    }

    const offscreen = document.createElement('canvas');
    offscreen.width = targetW;
    offscreen.height = targetH;
    const offCtx = offscreen.getContext('2d');

    // Draw raw camera frame
    offCtx.drawImage(video, 0, 0, targetW, targetH);

    return {
      dataUrl: offscreen.toDataURL('image/jpeg', 0.82),
      procW: targetW,
      procH: targetH
    };
  }

  // Draw face bounding boxes on overlay canvas (live mirrored webcam feed)
  function drawDetections(results, procW, procH) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!results || results.length === 0) return;

    const baseW = procW || video.videoWidth || 640;
    const baseH = procH || video.videoHeight || 480;
    const cW = canvas.width;
    const cH = canvas.height;

    // Accurate object-fit: cover mapping
    const scale = Math.max(cW / baseW, cH / baseH);
    const renderedW = baseW * scale;
    const renderedH = baseH * scale;
    const offsetX = (cW - renderedW) / 2;
    const offsetY = (cH - renderedH) / 2;

    results.forEach((res, idx) => {
      const [x, y, w, h] = res.bbox;
      // Convert bbox coordinates with mirror flip to match mirrored video
      const canvasX = (cW - offsetX) - (x * scale + w * scale);
      const canvasY = offsetY + (y * scale);
      const boxW = w * scale;
      const boxH = h * scale;

      const isAlreadyLogged = res.already_logged || false;
      const code = res.code || (res.status === 'recognized' ? 'candidate' : 'unknown');

      let color = '#f59e0b'; // Amber default
      if (code === 'poor_quality' || res.status === 'POOR FACE QUALITY') {
        color = '#ef4444'; // Red
      } else if (code === 'low_confidence' || res.status === 'LOW CONFIDENCE') {
        color = '#f59e0b'; // Amber / Yellow
      } else if (code === 'unknown' || res.status === 'UNKNOWN') {
        color = '#ea580c'; // Dark Orange
      } else if (res.student) {
        if (isAlreadyLogged) {
          color = '#0284c7'; // Sky Blue
        } else if (multiFrameTracker.candidateId === res.student.student_id && multiFrameTracker.consecutiveCount < REQUIRED_CONFIRMATIONS) {
          color = '#2563eb'; // Electric Blue
        } else {
          color = '#10b981'; // Emerald Green
        }
      }

      ctx.save();
      ctx.lineWidth = 3;
      ctx.strokeStyle = color;
      ctx.fillStyle = color;

      // Draw rounded rectangle
      ctx.beginPath();
      const r = 8;
      ctx.moveTo(canvasX + r, canvasY);
      ctx.lineTo(canvasX + boxW - r, canvasY);
      ctx.quadraticCurveTo(canvasX + boxW, canvasY, canvasX + boxW, canvasY + r);
      ctx.lineTo(canvasX + boxW, canvasY + boxH - r);
      ctx.quadraticCurveTo(canvasX + boxW, canvasY + boxH, canvasX + boxW - r, canvasY + boxH);
      ctx.lineTo(canvasX + r, canvasY + boxH);
      ctx.quadraticCurveTo(canvasX, canvasY + boxH, canvasX, canvasY + boxH - r);
      ctx.lineTo(canvasX, canvasY + r);
      ctx.quadraticCurveTo(canvasX, canvasY, canvasX + r, canvasY);
      ctx.closePath();
      ctx.stroke();

      // Corner accent markers
      const cLen = 14;
      ctx.lineWidth = 5;
      // Top Left
      ctx.beginPath();
      ctx.moveTo(canvasX, canvasY + cLen);
      ctx.lineTo(canvasX, canvasY);
      ctx.lineTo(canvasX + cLen, canvasY);
      ctx.stroke();
      // Top Right
      ctx.beginPath();
      ctx.moveTo(canvasX + boxW - cLen, canvasY);
      ctx.lineTo(canvasX + boxW, canvasY);
      ctx.lineTo(canvasX + boxW, canvasY + cLen);
      ctx.stroke();

      // Tag Label pill
      let labelText = 'Scanning Face...';
      if (code === 'poor_quality' || res.status === 'POOR FACE QUALITY') {
        labelText = '⚠ POOR QUALITY' + (res.quality_reason ? ` (${res.quality_reason})` : '');
      } else if (code === 'low_confidence' || res.status === 'LOW CONFIDENCE') {
        labelText = `⚠ LOW CONFIDENCE (${res.confidence || 0}%)`;
      } else if (code === 'unknown' || res.status === 'UNKNOWN') {
        labelText = '? UNKNOWN (No Match)';
      } else if (res.student) {
        if (isAlreadyLogged) {
          labelText = `✓ ${res.student.full_name} (Checked In)`;
        } else if (multiFrameTracker.candidateId === res.student.student_id && multiFrameTracker.consecutiveCount < REQUIRED_CONFIRMATIONS) {
          labelText = `Verifying ${res.student.full_name} (${multiFrameTracker.consecutiveCount}/${REQUIRED_CONFIRMATIONS})`;
        } else {
          labelText = `✓ ${res.student.full_name} (${res.confidence}%)`;
        }
      } else if (results.length > 1) {
        labelText = `Face #${idx + 1}`;
      }

      ctx.font = '600 12px Inter, sans-serif';
      const textWidth = ctx.measureText(labelText).width;
      const pillW = textWidth + 16;
      const pillH = 24;

      ctx.fillStyle = color;
      ctx.fillRect(canvasX, Math.max(0, canvasY - pillH - 4), pillW, pillH);

      ctx.fillStyle = '#ffffff';
      ctx.fillText(labelText, canvasX + 8, Math.max(0, canvasY - pillH - 4) + 16);

      ctx.restore();
    });
  }

  // Draw face bounding boxes on overlay canvas for uploaded static picture (unmirrored, object-fit: contain)
  function drawStaticDetections(results, imgW, imgH) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!results || results.length === 0) return;

    const cW = canvas.width;
    const cH = canvas.height;
    const imgRatio = imgW / imgH;
    const canvasRatio = cW / cH;

    let renderW, renderH, offsetX, offsetY;
    if (canvasRatio > imgRatio) {
      renderH = cH;
      renderW = cH * imgRatio;
      offsetX = (cW - renderW) / 2;
      offsetY = 0;
    } else {
      renderW = cW;
      renderH = cW / imgRatio;
      offsetX = 0;
      offsetY = (cH - renderH) / 2;
    }

    const scale = renderW / imgW;

    results.forEach((res, idx) => {
      const [x, y, w, h] = res.bbox;
      const canvasX = offsetX + (x * scale);
      const canvasY = offsetY + (y * scale);
      const boxW = w * scale;
      const boxH = h * scale;

      const isAlreadyLogged = res.already_logged || false;
      const code = res.code || (res.status === 'recognized' ? 'candidate' : 'unknown');

      let color = '#f59e0b';
      let labelText = 'Face Detected';

      if (code === 'poor_quality' || res.status === 'POOR FACE QUALITY') {
        color = '#ef4444';
        labelText = '⚠ POOR QUALITY' + (res.quality_reason ? ` (${res.quality_reason})` : '');
      } else if (code === 'low_confidence' || res.status === 'LOW CONFIDENCE') {
        color = '#f59e0b';
        labelText = `⚠ LOW CONFIDENCE (${res.confidence || 0}%)`;
      } else if (code === 'unknown' || res.status === 'UNKNOWN') {
        color = '#ea580c';
        labelText = '? UNKNOWN (No Match)';
      } else if (res.student) {
        color = isAlreadyLogged ? '#0284c7' : '#10b981';
        labelText = isAlreadyLogged ? `✓ ${res.student.full_name} (Checked In)` : `✓ ${res.student.full_name} (${res.confidence}%)`;
      } else if (results.length > 1) {
        labelText = `Face #${idx + 1}`;
      }

      ctx.font = '600 12px Inter, sans-serif';
      const textWidth = ctx.measureText(labelText).width;
      const pillW = textWidth + 16;
      const pillH = 24;

      ctx.fillStyle = color;
      ctx.fillRect(canvasX, Math.max(0, canvasY - pillH - 4), pillW, pillH);

      ctx.fillStyle = '#ffffff';
      ctx.fillText(labelText, canvasX + 8, Math.max(0, canvasY - pillH - 4) + 16);

      ctx.restore();
    });
  }

  // Handle multi-frame verification in progress (Section 2.2)
  function handleVerifyingEvent(studentData, count, required, confidence) {
    if (verificationProgressContainer) {
      verificationProgressContainer.style.display = 'block';
      const pct = Math.min(100, Math.round((count / required) * 100));
      if (verificationProgressBar) verificationProgressBar.style.width = pct + '%';
      if (verificationProgressPercent) verificationProgressPercent.innerText = `Frame ${count} of ${required} (${pct}%)`;
    }

    recognitionBannerTag.innerText = `Verifying Identity (Frame ${count}/${required})...`;
    recognitionBannerTag.style.color = '#2563eb';
    recognitionTimeBadge.innerText = 'Verifying';
    recognitionTimeBadge.className = 'badge badge-late';

    recognizedName.innerText = studentData.full_name;
    recognizedMeta.innerText = `${studentData.grade || ''} - Section ${studentData.section || ''} | Roll: ${studentData.roll_no || ''} • Confirming consecutive biometric frames...`;

    if (studentData.photo_path) {
      recognizedAvatar.src = studentData.photo_path;
    } else {
      recognizedAvatar.src = `https://ui-avatars.com/api/?name=${encodeURIComponent(studentData.full_name)}&background=E0E7FF&color=4338CA`;
    }

    if (confidence) {
      recognitionConfTag.style.display = 'inline-block';
      confBadgeText.innerText = `Verifying Match (${confidence}%)`;
      confBadgeText.style.background = '#dbeafe';
      confBadgeText.style.color = '#1d4ed8';
    }
  }

  // Handle successful student attendance mark (Section 1 & 2.1)
  function handleAttendanceEvent(studentData) {
    playSuccessChime();

    if (verificationProgressContainer) {
      verificationProgressContainer.style.display = 'none';
    }

    // Visual pulse effect on verified card
    verifiedCard.classList.remove('pulse');
    void verifiedCard.offsetWidth; // trigger reflow
    verifiedCard.classList.add('pulse');

    // Update feedback panel
    recognitionBannerTag.innerText = 'Attendance Logged ✓';
    recognitionBannerTag.style.color = '#059669';
    recognitionTimeBadge.innerText = studentData.time || new Date().toLocaleTimeString();
    recognitionTimeBadge.className = 'badge badge-present';

    recognizedName.innerText = studentData.full_name;
    recognizedMeta.innerText = `${studentData.grade || ''} - Section ${studentData.section || ''} | Roll: ${studentData.roll_no || ''} • Verified Present`;

    if (studentData.photo_path) {
      recognizedAvatar.src = studentData.photo_path;
    } else {
      recognizedAvatar.src = `https://ui-avatars.com/api/?name=${encodeURIComponent(studentData.full_name)}&background=E0E7FF&color=4338CA`;
    }

    if (studentData.confidence) {
      recognitionConfTag.style.display = 'inline-block';
      confBadgeText.innerText = `✓ Match Confirmed (${studentData.confidence}%)`;
      confBadgeText.style.background = '';
      confBadgeText.style.color = '';
    }

    // Add to or update top of feed list
    if (emptyPlaceholder) {
      emptyPlaceholder.style.display = 'none';
    }

    // Check if student item already exists in feed
    let existingItem = feedList.querySelector(`[data-student-id="${studentData.student_id}"]`);
    if (existingItem) {
      existingItem.style.background = '#ecfdf5';
      setTimeout(() => { existingItem.style.background = ''; }, 2000);
    } else {
      const feedItem = document.createElement('div');
      feedItem.className = 'feed-item new';
      feedItem.setAttribute('data-student-id', studentData.student_id);
      feedItem.innerHTML = `
        <div class="student-cell">
          <img src="${studentData.photo_path || '/static/img/avatar_default.png'}" class="student-avatar" alt="${studentData.full_name}" onerror="this.src='https://ui-avatars.com/api/?name=${encodeURIComponent(studentData.full_name)}&background=E0E7FF&color=4338CA'">
          <div class="student-meta">
            <div class="name">${studentData.full_name}</div>
            <div class="sub">${studentData.grade || ''} - ${studentData.section || ''} | Roll: ${studentData.roll_no || ''}</div>
          </div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:12px; font-weight:700; color:var(--text-main);">${studentData.time || new Date().toLocaleTimeString()}</div>
          <span class="badge badge-present" style="font-size:10px; padding:2px 7px;">✓ Verified</span>
        </div>
      `;
      feedList.insertBefore(feedItem, feedList.firstChild);

      // Update present count badge
      const curCountMatch = liveCountBadge.innerText.match(/\\d+/);
      const curCount = curCountMatch ? parseInt(curCountMatch[0]) : 0;
      liveCountBadge.innerText = `${curCount + 1} Present`;
    }
  }

  // Handle student who has already been marked today or in 30s cooldown (Section 2.8)
  function handleAlreadyLoggedEvent(studentData, isCooldown = false) {
    if (verificationProgressContainer) {
      verificationProgressContainer.style.display = 'none';
    }

    recognitionBannerTag.innerText = isCooldown ? 'Cooldown Active (30s) ⏱' : 'Already Checked In Today ✓';
    recognitionBannerTag.style.color = '#0284c7';
    recognitionTimeBadge.innerText = isCooldown ? 'Cooldown Active' : 'Present Today';
    recognitionTimeBadge.className = 'badge badge-present';

    recognizedName.innerText = studentData.full_name;
    recognizedMeta.innerText = `${studentData.grade || ''} - Section ${studentData.section || ''} | Roll: ${studentData.roll_no || ''} • Attendance already recorded today (duplicate check-in prevented)`;

    if (studentData.photo_path) {
      recognizedAvatar.src = studentData.photo_path;
    } else {
      recognizedAvatar.src = `https://ui-avatars.com/api/?name=${encodeURIComponent(studentData.full_name)}&background=E0E7FF&color=4338CA`;
    }

    if (studentData.confidence) {
      recognitionConfTag.style.display = 'inline-block';
      confBadgeText.innerText = `✓ Verified Match (${studentData.confidence}%)`;
      confBadgeText.style.background = '';
      confBadgeText.style.color = '';
    }
  }

  // Handle unknown/unregistered face detected in camera (Section 1 & 2.1 - strictly no forced guesses!)
  function handleUnknownFaceEvent() {
    if (verificationProgressContainer) {
      verificationProgressContainer.style.display = 'none';
    }

    recognitionBannerTag.innerText = 'Unknown Face Detected ⚠️';
    recognitionBannerTag.style.color = '#ea580c';
    recognitionTimeBadge.innerText = 'Unknown Face';
    recognitionTimeBadge.className = 'badge badge-absent';

    recognizedName.innerText = 'Unregistered / Unknown Face';
    recognizedMeta.innerText = 'Face detected does not match any enrolled student biometrics with required confidence. Anti-hallucination active: attendance NOT marked.';
    recognizedAvatar.src = '/static/img/avatar_default.png';
    recognitionConfTag.style.display = 'none';
  }

  // Handle low confidence face candidate (Section 1 & 2.3)
  function handleLowConfidenceEvent(confidence) {
    if (verificationProgressContainer) {
      verificationProgressContainer.style.display = 'none';
    }

    recognitionBannerTag.innerText = 'Low Recognition Confidence ⚠️';
    recognitionBannerTag.style.color = '#f59e0b';
    recognitionTimeBadge.innerText = 'Low Confidence';
    recognitionTimeBadge.className = 'badge badge-late';

    recognizedName.innerText = 'Ambiguous / Unverified Face';
    recognizedMeta.innerText = `Biometric similarity (${confidence}%) is below safe threshold (65.0%). Attendance NOT marked to prevent false matches.`;
    recognizedAvatar.src = '/static/img/avatar_default.png';
    if (confidence) {
      recognitionConfTag.style.display = 'inline-block';
      confBadgeText.innerText = `Low Confidence (${confidence}%)`;
      confBadgeText.style.background = '#fef3c7';
      confBadgeText.style.color = '#b45309';
    } else {
      recognitionConfTag.style.display = 'none';
    }
  }

  // Handle poor face quality: blur, dark, overexposed, edge cut (Section 1 & 2.4)
  function handlePoorQualityEvent(reason) {
    if (verificationProgressContainer) {
      verificationProgressContainer.style.display = 'none';
    }

    recognitionBannerTag.innerText = 'Poor Face Quality 📷';
    recognitionBannerTag.style.color = '#ef4444';
    recognitionTimeBadge.innerText = 'Low Quality';
    recognitionTimeBadge.className = 'badge badge-absent';

    recognizedName.innerText = 'Face Quality Insufficient';
    recognizedMeta.innerText = `Frame rejected: ${reason || 'Face too blurry, too dark, or too close to edge'}. Please look directly into the camera with good lighting.`;
    recognizedAvatar.src = '/static/img/avatar_default.png';
    recognitionConfTag.style.display = 'none';
  }

  // Load and display recognition audit events (Section 11)
  async function loadAuditLogs() {
    if (!auditModal || !auditLogsTbody) return;
    auditLogsTbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:16px; color:var(--text-muted);">Loading audit trail...</td></tr>';
    auditModal.style.display = 'flex';

    try {
      const res = await fetch('/api/audit-logs?limit=50');
      const data = await res.json();
      if (!data.success) throw new Error(data.message || 'Failed to load logs');

      if (auditUnknownStat) {
        auditUnknownStat.innerText = data.unknown_count || 0;
      }

      if (!data.logs || data.logs.length === 0) {
        auditLogsTbody.innerHTML = '<tr><td colspan="5" style="text-align:center; padding:16px; color:var(--text-muted);">No audit events recorded today yet.</td></tr>';
        return;
      }

      auditLogsTbody.innerHTML = data.logs.map(log => {
        let badgeClass = 'badge-absent';
        if (log.result === 'MATCHED') badgeClass = 'badge-present';
        else if (log.result && log.result.startsWith('VERIFYING')) badgeClass = 'badge-late';
        else if (log.result === 'ALREADY LOGGED') badgeClass = 'badge-present';
        else if (log.result === 'LOW CONFIDENCE') badgeClass = 'badge-late';

        const confText = log.confidence > 0 ? `${log.confidence.toFixed(1)}%` : '--';
        const labelText = log.detected_label || 'NONE';

        return `
          <tr style="border-bottom:1px solid #f1f5f9; font-size:12px;">
            <td style="padding:8px 10px; font-family:monospace; color:var(--text-muted);">${log.timestamp ? (log.timestamp.split('T')[1] || log.timestamp) : '--'}</td>
            <td style="padding:8px 10px; font-weight:600; color:var(--text-main);">${labelText}</td>
            <td style="padding:8px 10px;">${confText}</td>
            <td style="padding:8px 10px;"><span class="badge ${badgeClass}" style="font-size:10px;">${log.result}</span></td>
            <td style="padding:8px 10px; color:var(--text-muted); font-size:11px;">${log.camera_id || 'webcam-1'}</td>
          </tr>
        `;
      }).join('');
    } catch (err) {
      auditLogsTbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:16px; color:#ef4444;">Error: ${err.message}</td></tr>`;
    }
  }

  if (btnOpenAudit) {
    btnOpenAudit.addEventListener('click', loadAuditLogs);
  }

  // Reset feedback card after idle period
  function scheduleResetFeedbackCard() {
    if (resetTimer) return;
    resetTimer = setTimeout(() => {
      recognitionBannerTag.innerText = 'Awaiting Student Face';
      recognitionBannerTag.style.color = 'var(--text-muted)';
      recognitionTimeBadge.innerText = '--:--:--';
      recognitionTimeBadge.className = 'badge badge-excused';
      recognizedName.innerText = 'Stand in Front of Camera';
      recognizedMeta.innerText = 'Classroom camera is active. Keep face steady for instant verification.';
      recognizedAvatar.src = '/static/img/avatar_default.png';
      recognitionConfTag.style.display = 'none';
      if (verificationProgressContainer) verificationProgressContainer.style.display = 'none';
      resetTimer = null;
    }, 3200);
  }

  // Send frame to Flask backend with 5-state multi-frame confirmation
  async function processVideoFrame(isManual = false) {
    if (isProcessingFrame) return;
    if (!isScanning && !isManual) return;

    const capture = captureCurrentFrameBase64();
    if (!capture || !capture.dataUrl) {
      if (isScanning && !isManual) scheduleNextScan(120);
      return;
    }

    isProcessingFrame = true;
    try {
      // Calculate next confirmation count to send
      const targetCount = multiFrameTracker.consecutiveCount + 1;
      const willConfirm = isManual || (targetCount >= REQUIRED_CONFIRMATIONS);

      const response = await fetch('/api/process-frame', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          image: capture.dataUrl,
          auto_mark: true,
          confirm_count: targetCount,
          is_confirmed: willConfirm
        })
      });

      if (!response.ok) {
        throw new Error('Network error ' + response.status);
      }

      const data = await response.json();
      const results = data.results || [];
      if (data.success && results) {
        drawDetections(results, capture.procW, capture.procH);

        const faceCount = results.length;
        if (faceCount > 0) {
          if (resetTimer) {
            clearTimeout(resetTimer);
            resetTimer = null;
          }

          // Evaluate primary face detection
          multiFrameTracker.emptyFrames = 0;
          const primary = results[0];
          const code = primary.code;
          const student = primary.student;

          if (code === 'poor_quality') {
            multiFrameTracker.consecutiveCount = Math.max(0, (multiFrameTracker.consecutiveCount || 0) - 1);
            if (multiFrameTracker.consecutiveCount === 0) multiFrameTracker.candidateId = null;
            handlePoorQualityEvent(primary.quality_reason);
            statusLabel.innerHTML = `<strong>Face Notice: ${primary.quality_reason || 'Frame rejected'}</strong>`;
            statusLabel.style.color = '#ef4444';
          } else if (code === 'low_confidence') {
            multiFrameTracker.consecutiveCount = Math.max(0, (multiFrameTracker.consecutiveCount || 0) - 1);
            if (multiFrameTracker.consecutiveCount === 0) multiFrameTracker.candidateId = null;
            handleLowConfidenceEvent(primary.confidence);
            statusLabel.innerHTML = `<strong>Please Look at Camera (${primary.confidence}%)</strong>`;
            statusLabel.style.color = '#f59e0b';
          } else if (code === 'unknown' || !student) {
            multiFrameTracker.consecutiveCount = Math.max(0, (multiFrameTracker.consecutiveCount || 0) - 1);
            if (multiFrameTracker.consecutiveCount === 0) multiFrameTracker.candidateId = null;
            handleUnknownFaceEvent();
            statusLabel.innerHTML = `<strong>${faceCount} Unknown Face${faceCount > 1 ? 's' : ''} (Anti-Hallucination Safe)</strong>`;
            statusLabel.style.color = '#ea580c';
          } else {
            // Valid candidate student recognized
            const stuId = student.student_id;
            const now = Date.now();
            const lastMarked = recentAttendanceLog.get(stuId);
            const inCooldown = lastMarked && (now - lastMarked < COOLDOWN_DURATION_MS);

            if (primary.already_logged || inCooldown) {
              multiFrameTracker.candidateId = null;
              multiFrameTracker.consecutiveCount = 0;
              handleAlreadyLoggedEvent(student, inCooldown);
              statusLabel.innerHTML = `<strong>${student.full_name} (${inCooldown ? '30s Cooldown Active' : 'Already Marked Today'})</strong>`;
              statusLabel.style.color = '#0284c7';
            } else if (primary.marked) {
              // Successfully marked attendance after confirmations or manual snap!
              recentAttendanceLog.set(stuId, now);
              multiFrameTracker.candidateId = null;
              multiFrameTracker.consecutiveCount = 0;
              handleAttendanceEvent({
                student_id: student.student_id,
                full_name: student.full_name,
                grade: student.grade,
                section: student.section,
                roll_no: student.roll_no,
                photo_path: student.photo_path,
                time: primary.time,
                confidence: primary.confidence
              });
              statusLabel.innerHTML = `<strong>✓ Confirmed & Marked ${student.full_name} Present!</strong>`;
              statusLabel.style.color = '#10b981';
            } else {
              // Consecutive frame tracking towards confirmations
              if (multiFrameTracker.candidateId === stuId) {
                multiFrameTracker.consecutiveCount += 1;
              } else {
                multiFrameTracker.candidateId = stuId;
                multiFrameTracker.candidateStudent = student;
                multiFrameTracker.consecutiveCount = 1;
              }

              handleVerifyingEvent(student, multiFrameTracker.consecutiveCount, REQUIRED_CONFIRMATIONS, primary.confidence);
              statusLabel.innerHTML = `<strong>Verifying ${student.full_name} (${multiFrameTracker.consecutiveCount}/${REQUIRED_CONFIRMATIONS})...</strong>`;
              statusLabel.style.color = '#2563eb';
            }
          }
        } else {
          // No faces detected in frame - graceful timeout before resetting
          multiFrameTracker.emptyFrames = (multiFrameTracker.emptyFrames || 0) + 1;
          if (multiFrameTracker.emptyFrames >= 3) {
            multiFrameTracker.candidateId = null;
            multiFrameTracker.consecutiveCount = 0;
            if (verificationProgressContainer) verificationProgressContainer.style.display = 'none';
          }

          statusLabel.innerText = 'Camera Online & Scanning';
          statusLabel.style.color = '';
          scheduleResetFeedbackCard();
        }
      }
    } catch (err) {
      console.log('Frame processing error:', err);
    } finally {
      isProcessingFrame = false;
      if (isScanning && !isManual) {
        // Smooth 120ms scan interval (~8 FPS) ensures real-time detection without UI lag
        scheduleNextScan(120);
      }
    }
  }

  function scheduleNextScan(delayMs = 120) {
    if (!isScanning) return;
    if (scanTimer) clearTimeout(scanTimer);
    scanTimer = setTimeout(() => {
      processVideoFrame(false);
    }, delayMs);
  }

  function startContinuousScan() {
    if (scanTimer) clearTimeout(scanTimer);
    processVideoFrame(false);
  }

  function stopContinuousScan() {
    if (scanTimer) {
      clearTimeout(scanTimer);
      scanTimer = null;
    }
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    statusLabel.innerText = 'Scanning Paused';
    statusLabel.style.color = '';
  }

  // Upload and process a static live picture / test photo
  async function processStaticPicture(dataUrl) {
    stopContinuousScan();

    if (staticPictureView) {
      staticPictureView.src = dataUrl;
      staticPictureView.style.display = 'block';
    }
    if (video) video.style.display = 'none';
    if (btnBackLive) btnBackLive.style.display = 'inline-flex';

    statusLabel.innerText = 'Analyzing Picture...';
    statusLabel.style.color = '#f59e0b';

    await new Promise((resolve) => {
      if (staticPictureView && staticPictureView.complete) resolve();
      else if (staticPictureView) staticPictureView.onload = () => resolve();
      else resolve();
    });

    matchCanvasDimensions();

    try {
      const response = await fetch('/api/process-frame', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image: dataUrl, auto_mark: true, is_confirmed: true, is_static: true })
      });

      if (!response.ok) throw new Error('HTTP ' + response.status);

      const data = await response.json();
      const results = data.results || [];
      const imgW = (staticPictureView && staticPictureView.naturalWidth) || 640;
      const imgH = (staticPictureView && staticPictureView.naturalHeight) || 480;

      drawStaticDetections(results, imgW, imgH);

      const faceCount = results.length;
      if (faceCount > 0) {
        if (resetTimer) {
          clearTimeout(resetTimer);
          resetTimer = null;
        }

        const primary = results[0];
        const code = primary.code;
        const student = primary.student;

        if (code === 'poor_quality') {
          handlePoorQualityEvent(primary.quality_reason);
          statusLabel.innerHTML = `<strong>Picture Rejected: Poor Face Quality (${primary.quality_reason || 'Low quality'})</strong>`;
          statusLabel.style.color = '#ef4444';
        } else if (code === 'low_confidence') {
          handleLowConfidenceEvent(primary.confidence);
          statusLabel.innerHTML = `<strong>Picture Analyzed: Low Confidence (${primary.confidence}%)</strong>`;
          statusLabel.style.color = '#f59e0b';
        } else if (code === 'unknown' || !student) {
          handleUnknownFaceEvent();
          statusLabel.innerHTML = `<strong>${faceCount} Unknown Face${faceCount > 1 ? 's' : ''} Detected (Anti-Hallucination Safe)</strong>`;
          statusLabel.style.color = '#ea580c';
        } else if (primary.marked) {
          recentAttendanceLog.set(student.student_id, Date.now());
          handleAttendanceEvent({
            student_id: student.student_id,
            full_name: student.full_name,
            grade: student.grade,
            section: student.section,
            roll_no: student.roll_no,
            photo_path: student.photo_path,
            time: primary.time,
            confidence: primary.confidence
          });
          statusLabel.innerHTML = `<strong>Picture Scanned: ${student.full_name} Marked Present ✓</strong>`;
          statusLabel.style.color = '#10b981';
        } else if (primary.already_logged) {
          handleAlreadyLoggedEvent(student, false);
          statusLabel.innerHTML = `<strong>${student.full_name} Already Marked Today ✓</strong>`;
          statusLabel.style.color = '#0284c7';
        } else {
          statusLabel.innerHTML = `<strong>${student.full_name} Verified</strong>`;
          statusLabel.style.color = '#10b981';
        }
      } else {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        statusLabel.innerText = 'No face detected in picture';
        statusLabel.style.color = '#ef4444';
        recognitionBannerTag.innerText = 'No Face Found';
        recognitionBannerTag.style.color = '#ef4444';
        recognizedName.innerText = 'Face Detection Failed';
        recognizedMeta.innerText = 'No face could be found in the uploaded image. Please ensure the face is clearly visible and facing the camera.';
      }
    } catch (err) {
      console.error('Static picture scan error:', err);
      statusLabel.innerText = 'Error analyzing picture';
      statusLabel.style.color = '#ef4444';
    }
  }

  // Event Listeners
  btnToggleScan.addEventListener('click', () => {
    isScanning = !isScanning;
    if (isScanning) {
      scanToggleText.innerText = 'Pause Scanning';
      btnToggleScan.className = 'btn btn-primary btn-sm';
      statusLabel.innerText = 'Camera Online & Scanning';
      startContinuousScan();
    } else {
      scanToggleText.innerText = 'Resume Scanning';
      btnToggleScan.className = 'btn btn-secondary btn-sm';
      statusLabel.innerText = 'Scanning Paused';
      stopContinuousScan();
    }
  });

  btnSnapAttendance.addEventListener('click', () => {
    processVideoFrame(true);
    // Quick flash effect
    canvas.style.backgroundColor = 'rgba(255,255,255,0.4)';
    setTimeout(() => { canvas.style.backgroundColor = 'transparent'; }, 150);
  });

  if (btnUploadPhoto && inputUploadPhoto) {
    btnUploadPhoto.addEventListener('click', () => {
      inputUploadPhoto.click();
    });

    inputUploadPhoto.addEventListener('change', (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;

      const reader = new FileReader();
      reader.onload = (evt) => {
        processStaticPicture(evt.target.result);
      };
      reader.readAsDataURL(file);
      inputUploadPhoto.value = '';
    });
  }

  if (btnBackLive) {
    btnBackLive.addEventListener('click', () => {
      if (staticPictureView) staticPictureView.style.display = 'none';
      if (video) video.style.display = 'block';
      btnBackLive.style.display = 'none';
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      isScanning = true;
      scanToggleText.innerText = 'Pause Scanning';
      btnToggleScan.className = 'btn btn-primary btn-sm';
      statusLabel.innerText = 'Camera Online & Scanning';
      statusLabel.style.color = '';
      matchCanvasDimensions();
      startContinuousScan();
    });
  }

  btnSoundToggle.addEventListener('click', () => {
    audioEnabled = !audioEnabled;
    soundLabel.innerText = audioEnabled ? 'Audio Chime ON' : 'Audio Muted';
    btnSoundToggle.style.opacity = audioEnabled ? '1' : '0.65';
  });

  if (btnRequestCamera) {
    btnRequestCamera.addEventListener('click', () => {
      initCamera(true);
    });
  }

  if (btnReloadCamera) {
    btnReloadCamera.addEventListener('click', () => {
      window.location.reload();
    });
  }

  // Demo simulation mode for testing when running in headless or camera-disabled environments
  btnDemoSimulate.addEventListener('click', async () => {
    cameraFallback.style.display = 'none';

    // If STU-1001 is already scanned today, ignore / cannot scan again
    if (feedList.querySelector('[data-student-id="STU-1001"]')) {
      statusLabel.innerText = 'Student Aarav Sharma already scanned today';
      return;
    }

    statusLabel.innerText = 'Demo Simulation Active';

    // Simulate recognition of student STU-1001
    try {
      const res = await fetch('/api/mark-status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          student_id: 'STU-1001',
          status: 'Present',
          notes: 'Camera Simulated Verification'
        })
      });
      const data = await res.json();
      if (data.success) {
        handleAttendanceEvent({
          student_id: 'STU-1001',
          full_name: 'Aarav Sharma',
          grade: 'Grade 10',
          section: 'A',
          roll_no: '1001',
          photo_path: '/static/uploads/profiles/STU-1001.jpg',
          time: new Date().toLocaleTimeString(),
          confidence: 97.4
        });
      }
    } catch (e) {
      console.log('Demo error:', e);
    }
  });

  btnRetrain.addEventListener('click', async () => {
    btnRetrain.disabled = true;
    btnRetrain.innerHTML = '<span>Training...</span>';
    try {
      const res = await fetch('/api/retrain', { method: 'POST' });
      const data = await res.json();
      alert(data.message || 'Model updated successfully.');
    } catch (e) {
      alert('Error retraining face engine: ' + e);
    } finally {
      btnRetrain.disabled = false;
      btnRetrain.innerHTML = `
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="23 4 23 10 17 10"></polyline>
          <polyline points="1 20 1 14 7 14"></polyline>
          <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
        </svg>
        <span>Sync Face AI</span>
      `;
    }
  });

  // Start Camera
  initCamera();
});

