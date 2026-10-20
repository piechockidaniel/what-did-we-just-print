import { post } from "./api.js";
import { $, el, button, field, notice, readImage } from "./ui.js";
import { packingForm, getState } from "./workflow.js";

let stream,
  refresh,
  captured,
  scanResult,
  generation = 0;
export function stopCamera() {
  generation++;
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  const video = $("station-camera");
  if (video) video.srcObject = null;
}
function resetResults() {
  scanResult = null;
  $("scan-results").replaceChildren();
}

export function setupStation(callback) {
  refresh = callback;
  const panel = $("station-view");
  panel.innerHTML =
    '<h2>SCAN STATION</h2><p>Experimental ORB feature matching. Inspect names and destinations yourself. No calibrated probability, physical-size inference or whole-stack verification.</p><div class="workflow-columns"><section class="surface" id="capture-controls"></section><section class="surface" id="scan-controls"></section></div><div id="scan-status" class="station-status" role="status">Capture a product or upload a photograph.</div><div id="scan-results" class="scan-results"></div>';
  const captureControls = $("capture-controls"),
    controls = $("scan-controls");
  const cameraLabel = el("label", "Camera device"),
    cameras = el("select");
  cameras.id = "camera-device";
  cameraLabel.append(cameras);
  const defaultCamera = el("option", "Default camera");
  defaultCamera.value = "";
  cameras.append(defaultCamera);
  const video = el("video");
  video.id = "station-camera";
  video.className = "station-video";
  video.autoplay = true;
  video.muted = true;
  video.playsInline = true;
  const preview = el("img");
  preview.id = "scan-preview";
  preview.className = "scan-preview";
  preview.alt = "Current captured product";
  preview.hidden = true;
  const file = el("input");
  file.type = "file";
  file.accept = "image/png,image/jpeg,image/webp";
  file.setAttribute("capture", "environment");
  file.id = "scan-file";
  const upload = el("label", "Upload a captured product photograph");
  upload.append(file);
  const cameraActions = el("div", undefined, "station-controls");
  cameraActions.append(
    button("Start camera", async () => {
      stopCamera();
      const token = generation;
      if (!navigator.mediaDevices?.getUserMedia)
        throw new Error(
          "Camera requires a supported browser and a secure context (HTTPS or loopback localhost).",
        );
      const next = await navigator.mediaDevices.getUserMedia({
        video: cameras.value
          ? { deviceId: { exact: cameras.value } }
          : { facingMode: "environment" },
        audio: false,
      });
      if (token !== generation) {
        next.getTracks().forEach((track) => track.stop());
        return;
      }
      stream = next;
      video.srcObject = stream;
      await video.play();
      const current = cameras.value;
      cameras.replaceChildren(defaultCamera);
      for (const device of await navigator.mediaDevices.enumerateDevices())
        if (device.kind === "videoinput") {
          const option = el("option", device.label || "Camera");
          option.value = device.deviceId;
          cameras.append(option);
        }
      cameras.value = current;
      notice(
        "Camera running. Place a single product under controlled lighting.",
      );
    }),
    button("Capture frame", () => {
      if (!stream || !video.videoWidth)
        throw new Error("Start the camera and wait for a frame.");
      const canvas = el("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d").drawImage(video, 0, 0);
      setCapture(canvas.toDataURL("image/jpeg", 0.94));
    }),
    button("Stop camera", stopCamera),
  );
  captureControls.append(
    el("p", "Phone pilot · business cards. Use the rear camera, keep one card flat and fully visible, and avoid glare. Live camera access on a phone requires an approved HTTPS address. You can also take a photograph using the upload control."),
    cameraLabel, video, cameraActions, upload, preview,
  );
  function setCapture(image) {
    captured = image;
    preview.src = image;
    preview.hidden = false;
    resetResults();
    $("scan-status").textContent =
      "Capture ready. Check product framing; corners below are optional.";
  }
  file.addEventListener("change", async () => {
    try {
      if (file.files[0]) setCapture((await readImage(file.files[0])).image);
    } catch (error) {
      notice(error.message, true);
    } finally {
      file.value = "";
    }
  });
  const filterLabel = el("label", "Search pool"),
    filter = el("select");
  filter.id = "scan-sheet";
  filterLabel.append(filter);
  const stationLabel = el(
      "label",
      "Station profile (configured product-size class)",
    ),
    station = el("select");
  stationLabel.append(station);
  const updateFilter = () => {
    const selected = filter.value;
    filter.replaceChildren();
    const all = el("option", "All active production");
    all.value = "";
    filter.append(all);
    for (const sheet of getState().sheets.filter(
      (s) => s.state === "released",
    )) {
      const option = el("option", sheet.number);
      option.value = sheet.id;
      filter.append(option);
    }
    filter.value = [...filter.options].some((o) => o.value === selected)
      ? selected
      : "";
    const chosen = station.value;
    station.replaceChildren();
    const anyStation = el("option", "Unconfigured station / all product sizes");
    anyStation.value = "";
    station.append(anyStation);
    for (const profile of getState().stations || []) {
      const option = el(
        "option",
        `${profile.name} · up to ${profile.max_width} × ${profile.max_height} mm`,
      );
      option.value = profile.id;
      station.append(option);
    }
    station.value = [...station.options].some((o) => o.value === chosen)
      ? chosen
      : "";
  };
  window.addEventListener("production-updated", updateFilter);
  updateFilter();
  filter.addEventListener("change", resetResults);
  station.addEventListener("change", resetResults);
  const cornerLabel = el(
      "label",
      "Optional corners: TL, TR, BR, BL as JSON pixel coordinates",
    ),
    corners = el("textarea");
  corners.placeholder = "[[20,20],[920,20],[920,520],[20,520]]";
  cornerLabel.append(corners);
  corners.addEventListener("input", resetResults);
  const autoLabel = el("label", undefined, "checkbox-label"),
    autoCrop = el("input");
  autoCrop.type = "checkbox";
  autoCrop.checked = true;
  autoCrop.addEventListener("change", resetResults);
  autoLabel.append(
    autoCrop,
    document.createTextNode(
      "Try automatic product framing (experimental; inspect outline)",
    ),
  );
  controls.append(
    stationLabel,
    filterLabel,
    cornerLabel,
    autoLabel,
    el(
      "p",
      "Manual corners override automatic framing. If no boundary is found, the whole image is compared. Inspect the returned outline; station calibration still needs physical measurement. Never infer millimetres directly from image pixels.",
    ),
    button(
      "Find active candidates",
      async () => {
        if (!captured) throw new Error("Capture or upload a product first.");
        resetResults();
        $("scan-status").textContent = "Comparing against active production…";
        try {
          scanResult = await post("/scans", {
            image: captured,
            sheetId: filter.value || null,
            stationId: station.value || null,
            corners: corners.value.trim() ? JSON.parse(corners.value) : null,
            autoCrop: autoCrop.checked,
          });
          renderResults();
        } catch (error) {
          $("scan-status").textContent =
            "Matching unavailable. No identity decision was made.";
          throw error;
        }
      },
      "primary",
    ),
  );
  const profileEditor = el("details");
  profileEditor.append(
    el("summary", "Register a station profile (supervisor)"),
  );
  const profileForm = el("form");
  const [nameLabel, name] = field("Station name"),
    [widthLabel, width] = field("Maximum product width (mm)", "number", "150"),
    [heightLabel, height] = field(
      "Maximum product height (mm)",
      "number",
      "150",
    ),
    [notesLabel, notes] = field("Lighting / mount notes", "text", "", false);
  width.min = height.min = "20";
  width.max = height.max = "3000";
  width.step = height.step = ".1";
  profileForm.append(
    nameLabel,
    widthLabel,
    heightLabel,
    notesLabel,
    button("Save station profile", async () => {
      if (!profileForm.reportValidity()) return;
      await post("/stations", {
        name: name.value,
        maxWidthMm: Number(width.value),
        maxHeightMm: Number(height.value),
        notes: notes.value,
      });
      await refresh();
      notice(
        "Station profile saved. Physical calibration still requires measurements and validation.",
      );
    }),
  );
  profileForm.addEventListener("submit", (event) => event.preventDefault());
  profileEditor.append(profileForm);
  controls.append(profileEditor);
  window.addEventListener("pagehide", stopCamera);
  window.addEventListener("operator-signed-out", () => {
    stopCamera();
    captured = null;
    preview.src = "";
    preview.hidden = true;
    resetResults();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopCamera();
  });
}

function renderResults() {
  const result = scanResult;
  $("scan-status").textContent =
    `${result.decision.toUpperCase()} · ${result.reason} · ${result.durationMs} ms · ${result.activeAllocations ?? 0} active allocations searched. Operator review required.`;
  const container = $("scan-results");
  container.replaceChildren();
  const framing = el("article", undefined, "scan-candidate");
  framing.append(
    el("h3", "CAPTURE FRAMING"),
    el(
      "p",
      `${result.framing.mode}: inspect the product outline before accepting any candidate.`,
    ),
  );
  if (result.framing.corners) {
    const canvas = el("canvas"),
      image = new Image();
    canvas.width = 900;
    canvas.height = Math.round(
      (900 * result.framing.sourceSize[1]) / result.framing.sourceSize[0],
    );
    image.onload = () => {
      const context = canvas.getContext("2d");
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      context.strokeStyle = "#ff5b20";
      context.lineWidth = 4;
      context.beginPath();
      result.framing.corners.forEach(([x, y], index) => {
        const p = [
          (x / result.framing.sourceSize[0]) * canvas.width,
          (y / result.framing.sourceSize[1]) * canvas.height,
        ];
        if (index) context.lineTo(...p);
        else context.moveTo(...p);
      });
      context.closePath();
      context.stroke();
    };
    image.src = captured;
    canvas.setAttribute(
      "aria-label",
      "Product boundary outline on the capture",
    );
    framing.append(canvas);
  }
  container.append(framing);
  result.candidates.forEach((candidate, index) => {
    const card = el("article", undefined, "scan-candidate"),
      image = el("img");
    image.src = candidate.image;
    image.alt = `Reference: ${candidate.name}`;
    card.append(
      el("h3", `${index + 1}. ${candidate.name}`),
      image,
      el("p", `${candidate.orderNumber} · ${candidate.customer}`),
      el(
        "p",
        `Destination: ${candidate.destination} · Sheet: ${candidate.sheetNumber}`,
      ),
      el(
        "p",
        `${candidate.inliers} / ${candidate.tentativeMatches} tentative points geometrically consistent · ${candidate.inlierRatio === null ? "no ratio" : `${(candidate.inlierRatio * 100).toFixed(1)}% inlier ratio (not probability)`}`,
      ),
      el(
        "p",
        `${candidate.remaining} remaining · ${candidate.distinguishingEvidence}`,
      ),
    );
    const overlay = el("canvas");
    overlay.width = 600;
    overlay.height = 180;
    const context = overlay.getContext("2d");
    context.fillStyle = "#15120e";
    context.fillRect(0, 0, 600, 180);
    context.fillStyle = "#a39b8e";
    context.font = "12px monospace";
    context.fillText(
      "Geometric inlier locations in normalized capture",
      12,
      18,
    );
    context.fillStyle = "#ff5b20";
    for (const point of candidate.evidence) {
      context.beginPath();
      context.arc(
        10 + (point.capture[0] / result.captureSize[0]) * 580,
        30 + (point.capture[1] / result.captureSize[1]) * 140,
        2,
        0,
        2 * Math.PI,
      );
      context.fill();
    }
    overlay.setAttribute(
      "aria-label",
      `${candidate.inliers} geometric matches; point distribution in the captured image`,
    );
    card.append(overlay);
    const [reasonLabel, reason] = field(
      "Identification evidence / context",
      "text",
    );
    reason.maxLength = 500;
    const packing = el("div");
    card.append(
      reasonLabel,
      button("Confirm this allocation for packing", async () => {
        if (!reason.value.trim())
          throw new Error(
            "Describe the distinguishing name or independent production context.",
          );
        await post(`/scans/${result.id}/review`, {
          allocationId: candidate.id,
          decision: "confirm",
          reason: reason.value,
        });
        packing.replaceChildren(
          el("p", "Review recorded. Confirm the actual quantity separately."),
          packingForm(candidate, result.id, async () => {
            await refresh();
            resetResults();
            $("scan-status").textContent =
              "Packing committed. Capture again for the next quantity.";
          }),
        );
        notice(
          "Candidate confirmed by operator. No quantity has been packed yet.",
        );
      }),
      button("Reject result", async () => {
        await post(`/scans/${result.id}/review`, {
          allocationId: candidate.id,
          decision: "reject",
          reason: reason.value.trim() || "Operator rejected candidate",
        });
        packing.replaceChildren();
        notice("Rejection recorded. No packing quantities changed.");
      }),
      packing,
    );
    container.append(card);
  });
}
