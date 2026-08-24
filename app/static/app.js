// UI controller for Basic Pitch Local.
// Handles drag & drop, file selection, microphone recording and the
// /convert request. The browser only ever talks to the local server.

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const recordBtn = document.getElementById("record-btn");
const advancedToggle = document.getElementById("advanced-toggle");
const advanced = document.getElementById("advanced");
const onset = document.getElementById("onset");
const frame = document.getElementById("frame");
const minlen = document.getElementById("minlen");
const statusEl = document.getElementById("status");
const statusTitle = document.getElementById("status-title");
const statusSub = document.getElementById("status-sub");
const errorEl = document.getElementById("error");
const resultEl = document.getElementById("result");
const download = document.getElementById("download");
const resetBtn = document.getElementById("reset");

let busy = false;

function setBusy(state, { title = "转换中…", sub = "首次运行需要加载模型，可能需要几十秒。" } = {}) {
    busy = state;
    statusEl.hidden = !state;
    if (state) {
        statusTitle.textContent = title;
        statusSub.textContent = sub;
    }
    dropzone.style.opacity = busy ? "0.6" : "1";
    recordBtn.disabled = busy;
}

function showError(message) {
    errorEl.hidden = false;
    errorEl.textContent = message;
}

function clearError() {
    errorEl.hidden = true;
    errorEl.textContent = "";
}

// ---- Advanced toggle ----
advancedToggle.addEventListener("click", () => {
    const open = advanced.hasAttribute("hidden");
    if (open) {
        advanced.removeAttribute("hidden");
        advancedToggle.setAttribute("aria-expanded", "true");
    } else {
        advanced.setAttribute("hidden", "");
        advancedToggle.setAttribute("aria-expanded", "false");
    }
});
onset.addEventListener("input", () => document.getElementById("onset-val").textContent = Number(onset.value).toFixed(2));
frame.addEventListener("input", () => document.getElementById("frame-val").textContent = Number(frame.value).toFixed(2));
minlen.addEventListener("input", () => document.getElementById("minlen-val").textContent = Number(minlen.value).toFixed(2));

// ---- Drag & drop ----
dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
});
["dragenter", "dragover"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.add("drag"); })
);
["dragleave", "drop"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => { e.preventDefault(); dropzone.classList.remove("drag"); })
);
dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) submitFile(file);
});
fileInput.addEventListener("change", () => {
    if (fileInput.files && fileInput.files[0]) submitFile(fileInput.files[0]);
});

// ---- Recording via MediaRecorder ----
let mediaRecorder = null;
let recordedChunks = [];

recordBtn.addEventListener("click", async () => {
    if (busy) return;
    if (mediaRecorder && mediaRecorder.state === "recording") {
        mediaRecorder.stop();
        return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showError("此浏览器不支持麦克风录音，请改用文件上传。");
        return;
    }
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        recordedChunks = [];
        const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
            ? "audio/webm;codecs=opus"
            : "";
        mediaRecorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
        mediaRecorder.ondataavailable = (e) => { if (e.data.size) recordedChunks.push(e.data); };
        mediaRecorder.onstop = () => {
            stream.getTracks().forEach((t) => t.stop());
            recordBtn.classList.remove("recording");
            const blob = new Blob(recordedChunks, { type: mediaRecorder.mimeType || "audio/webm" });
            const file = new File([blob], "recording.webm", { type: blob.type });
            submitFile(file);
        };
        mediaRecorder.start();
        recordBtn.classList.add("recording");
        clearError();
    } catch (err) {
        showError("无法访问麦克风：" + err.message);
    }
});

// ---- Submit to local server ----
function submitFile(file) {
    if (busy) return;
    clearError();
    resultEl.hidden = true;
    setBusy(true);

    const form = new FormData();
    form.append("file", file);
    form.append("onset_threshold", onset.value);
    form.append("frame_threshold", frame.value);
    form.append("min_note_length", minlen.value);

    fetch("/convert", { method: "POST", body: form })
        .then(async (resp) => {
            if (!resp.ok) {
                let detail = `HTTP ${resp.status}`;
                try {
                    const data = await resp.json();
                    if (data && data.detail) detail = data.detail;
                } catch (_) { /* ignore */ }
                throw new Error(detail);
            }
            return resp.blob().then((blob) => {
                const cd = resp.headers.get("Content-Disposition") || "";
                const match = cd.match(/filename="?([^"]+)"?/);
                const name = match ? match[1] : "output.mid";
                return { blob, name };
            });
        })
        .then(({ blob, name }) => {
            const url = URL.createObjectURL(blob);
            download.href = url;
            download.setAttribute("download", name);
            download.textContent = `下载 ${name}`;
            statusEl.hidden = true;
            resultEl.hidden = false;
        })
        .catch((err) => {
            showError("转换失败：" + err.message);
        })
        .finally(() => setBusy(false));
}

resetBtn.addEventListener("click", () => {
    resultEl.hidden = true;
    fileInput.value = "";
});
