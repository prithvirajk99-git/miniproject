/**
 * UrbanEye - Modern Dashboard Controller
 * Handles real-time telemetry polling, video controls, confidence calibration,
 * dynamic stream URL updates, and modal previews for captured pothole incidents.
 */

document.addEventListener("DOMContentLoaded", () => {
  // DOM Elements
  const systemClock = document.getElementById("systemClock");
  const camDot = document.getElementById("camDot");
  const camStatusText = document.getElementById("camStatusText");
  const modelDot = document.getElementById("modelDot");
  const modelStatusText = document.getElementById("modelStatusText");

  // Video HUD & Stream
  const videoStream = document.getElementById("videoStream");
  const videoWrapper = document.getElementById("videoWrapper");
  const fpsDisplay = document.getElementById("fpsDisplay");
  const hudAlertBadge = document.getElementById("hudAlertBadge");
  const hudAlertText = document.getElementById("hudAlertText");
  const hudUrlLabel = document.getElementById("hudUrlLabel");
  const hudCooldownLabel = document.getElementById("hudCooldownLabel");
  const btnFullscreen = document.getElementById("btnFullscreen");

  // Metric Cards
  const metricStatusVal = document.getElementById("metricStatusVal");
  const metricCurrentCount = document.getElementById("metricCurrentCount");
  const metricTotalCount = document.getElementById("metricTotalCount");
  const metricConfVal = document.getElementById("metricConfVal");

  // Controls
  const btnStartDetection = document.getElementById("btnStartDetection");
  const btnStopDetection = document.getElementById("btnStopDetection");
  const btnSnapshot = document.getElementById("btnSnapshot");
  const inputCamUrl = document.getElementById("inputCamUrl");
  const btnUpdateUrl = document.getElementById("btnUpdateUrl");
  const sliderConfidence = document.getElementById("sliderConfidence");
  const valConfidence = document.getElementById("valConfidence");
  const sliderCooldown = document.getElementById("sliderCooldown");
  const valCooldown = document.getElementById("valCooldown");

  // Captures Gallery & Modal
  const capturesList = document.getElementById("capturesList");
  const emptyCaptures = document.getElementById("emptyCaptures");
  const captureCountBadge = document.getElementById("captureCountBadge");
  const btnRefreshCaptures = document.getElementById("btnRefreshCaptures");
  const imageModal = document.getElementById("imageModal");
  const modalClose = document.getElementById("modalClose");
  const modalBackdrop = document.getElementById("modalBackdrop");
  const modalAnnotatedImg = document.getElementById("modalAnnotatedImg");
  const modalOrigImg = document.getElementById("modalOrigImg");
  const modalMeta = document.getElementById("modalMeta");

  let lastTotalCaptures = -1;
  let debounceTimeout = null;

  // 1. Live System Clock
  function updateClock() {
    const now = new Date();
    systemClock.textContent = now.toTimeString().split(" ")[0];
  }
  setInterval(updateClock, 1000);
  updateClock();

  // 2. Poll System & Detection Status
  async function fetchStatus() {
    try {
      const res = await fetch("/api/status");
      if (!res.ok) return;
      const data = await res.json();

      // Camera status
      if (data.camera_connected) {
        camDot.className = "pulse-dot green";
        camStatusText.textContent = "CONNECTED";
      } else {
        camDot.className = "pulse-dot red";
        camStatusText.textContent = data.reconnecting ? "RECONNECTING..." : "DISCONNECTED";
      }

      // Model status
      if (data.model_loaded) {
        modelDot.className = "pulse-dot green";
        modelStatusText.textContent = data.model_name;
      } else {
        modelDot.className = "pulse-dot red";
        modelStatusText.textContent = "NOT LOADED";
      }

      // FPS display
      fpsDisplay.textContent = `${data.fps.toFixed(1)} FPS`;

      // HUD & Metric Cards Status
      if (!data.detection_active) {
        metricStatusVal.textContent = "STOPPED";
        metricStatusVal.className = "metric-value status-text";
        hudAlertBadge.className = "hud-badge-alert";
        hudAlertText.textContent = "DETECTION PAUSED";
      } else if (data.pothole_detected) {
        metricStatusVal.textContent = "POTHOLE DETECTED";
        metricStatusVal.className = "metric-value status-text status-danger";
        hudAlertBadge.className = "hud-badge-alert danger";
        hudAlertText.textContent = `⚠️ POTHOLE DETECTED (${data.current_potholes_count})`;
      } else {
        metricStatusVal.textContent = "NO POTHOLE";
        metricStatusVal.className = "metric-value status-text status-safe";
        hudAlertBadge.className = "hud-badge-alert safe";
        hudAlertText.textContent = "✓ CLEAR - NO POTHOLE";
      }

      // Numerical metrics
      metricCurrentCount.textContent = data.current_potholes_count;
      metricTotalCount.textContent = data.total_potholes_detected;
      metricConfVal.textContent = `${data.max_confidence.toFixed(1)}%`;

      // Bottom HUD labels
      hudUrlLabel.textContent = `URL: ${data.camera_url}`;
      hudCooldownLabel.textContent = `Cooldown: ${data.cooldown_seconds}s`;

      // Auto update inputs if not actively typing
      if (document.activeElement !== inputCamUrl && !inputCamUrl.value) {
        inputCamUrl.value = data.camera_url;
      }

      // Refresh gallery if total count changed
      if (data.total_potholes_detected !== lastTotalCaptures) {
        lastTotalCaptures = data.total_potholes_detected;
        fetchCaptures();
      }

    } catch (err) {
      console.warn("Status fetch error:", err);
    }
  }

  // Poll status every 400ms for smooth live telemetry
  setInterval(fetchStatus, 400);
  fetchStatus();

  // 3. Start / Stop Detection Controls
  btnStartDetection.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/control/start", { method: "POST" });
      const data = await res.json();
      if (data.success) {
        btnStartDetection.classList.add("btn-primary");
        btnStopDetection.classList.remove("btn-primary");
      }
    } catch (e) {
      alert("Failed to start detection: " + e.message);
    }
  });

  btnStopDetection.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/control/stop", { method: "POST" });
      const data = await res.json();
      if (data.success) {
        btnStopDetection.classList.add("btn-secondary");
      }
    } catch (e) {
      alert("Failed to stop detection: " + e.message);
    }
  });

  // 4. Manual Snapshot Trigger
  btnSnapshot.addEventListener("click", async () => {
    try {
      btnSnapshot.disabled = true;
      const res = await fetch("/api/control/snapshot", { method: "POST" });
      const data = await res.json();
      if (data.success) {
        fetchCaptures();
      } else {
        alert(data.message || "Could not capture snapshot.");
      }
    } catch (e) {
      alert("Snapshot failed: " + e.message);
    } finally {
      setTimeout(() => { btnSnapshot.disabled = false; }, 1000);
    }
  });

  // 5. Update Camera Stream URL
  btnUpdateUrl.addEventListener("click", async () => {
    const newUrl = inputCamUrl.value.trim();
    if (!newUrl) {
      alert("Please enter a valid ESP32-CAM stream URL.");
      return;
    }
    try {
      btnUpdateUrl.disabled = true;
      btnUpdateUrl.textContent = "Connecting...";
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ esp32_stream_url: newUrl })
      });
      const data = await res.json();
      if (data.success) {
        // Refresh video stream source
        videoStream.src = `/video_feed?t=${Date.now()}`;
      } else {
        alert("Failed to update URL: " + data.message);
      }
    } catch (e) {
      alert("Error updating stream URL: " + e.message);
    } finally {
      btnUpdateUrl.disabled = false;
      btnUpdateUrl.textContent = "Update";
    }
  });

  // 6. Confidence Threshold Slider (Live adjustment)
  sliderConfidence.addEventListener("input", (e) => {
    const val = e.target.value;
    valConfidence.textContent = `${val}%`;

    clearTimeout(debounceTimeout);
    debounceTimeout = setTimeout(async () => {
      try {
        await fetch("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confidence_threshold: parseFloat(val) / 100 })
        });
      } catch (err) {
        console.error("Failed to update confidence:", err);
      }
    }, 250);
  });

  // 7. Cooldown Slider
  sliderCooldown.addEventListener("input", (e) => {
    const val = e.target.value;
    valCooldown.textContent = `${val}s`;

    clearTimeout(debounceTimeout);
    debounceTimeout = setTimeout(async () => {
      try {
        await fetch("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ cooldown_seconds: parseFloat(val) })
        });
      } catch (err) {
        console.error("Failed to update cooldown:", err);
      }
    }, 250);
  });

  // 8. Fullscreen Toggle
  btnFullscreen.addEventListener("click", () => {
    if (!document.fullscreenElement) {
      videoWrapper.requestFullscreen().catch(err => {
        alert(`Error attempting to enable fullscreen: ${err.message}`);
      });
    } else {
      document.exitFullscreen();
    }
  });

  // 9. Fetch & Render Captures Gallery
  async function fetchCaptures() {
    try {
      const res = await fetch("/api/detections");
      if (!res.ok) return;
      const data = await res.json();
      const captures = data.captures || [];

      captureCountBadge.textContent = captures.length;

      if (captures.length === 0) {
        emptyCaptures.style.display = "flex";
        // Remove old items
        document.querySelectorAll(".capture-item").forEach(el => el.remove());
        return;
      }

      emptyCaptures.style.display = "none";
      // Clear existing items
      document.querySelectorAll(".capture-item").forEach(el => el.remove());

      captures.forEach(item => {
        const card = document.createElement("div");
        card.className = "capture-item";
        card.innerHTML = `
          <img class="capture-thumb" src="${item.annotated_url}" alt="Pothole Snapshot" loading="lazy">
          <div class="capture-details">
            <span class="capture-title">⚠️ Pothole Detected</span>
            <span class="capture-time font-mono">${item.timestamp}</span>
            <span class="capture-conf font-mono">Conf: ${item.confidence}%</span>
          </div>
        `;

        card.addEventListener("click", () => openModal(item));
        capturesList.appendChild(card);
      });
    } catch (err) {
      console.warn("Error fetching captures:", err);
    }
  }

  btnRefreshCaptures.addEventListener("click", fetchCaptures);

  // 10. Incident Modal Preview
  function openModal(item) {
    modalAnnotatedImg.src = item.annotated_url;
    modalOrigImg.src = item.orig_url;
    modalMeta.innerHTML = `
      <div><strong>Timestamp:</strong> ${item.timestamp}</div>
      <div><strong>Confidence:</strong> ${item.confidence}%</div>
      <div><strong>Potholes in Frame:</strong> ${item.potholes_count || 1}</div>
      <div><a href="${item.annotated_url}" download style="color:var(--accent-cyan); text-decoration:none;">Download Image</a></div>
    `;
    imageModal.classList.add("active");
  }

  function closeModal() {
    imageModal.classList.remove("active");
  }

  modalClose.addEventListener("click", closeModal);
  modalBackdrop.addEventListener("click", closeModal);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });
});
