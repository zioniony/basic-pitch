// UI controller for Basic Pitch Local.
// 三步工作流：选择音频 → 转换 → 下载。
// 任一时刻只显示当前步骤对应的面板，由 setState 统一切换。

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const recordBtn = document.getElementById("record-btn");
const recLabel = recordBtn.querySelector(".rec-label");
const advancedToggle = document.getElementById("advanced-toggle");
const advanced = document.getElementById("advanced");
const onset = document.getElementById("onset");
const frame = document.getElementById("frame");
const minlen = document.getElementById("minlen");

const panels = {
    input: document.getElementById("panel-input"),
    recording: document.getElementById("panel-recording"),
    converting: document.getElementById("panel-converting"),
    result: document.getElementById("panel-result"),
    error: document.getElementById("panel-error"),
};
const steps = Array.from(document.querySelectorAll(".stepper .step"));

const recTime = document.getElementById("rec-time");
const stopBtn = document.getElementById("stop-btn");
const cancelBtn = document.getElementById("cancel-btn");
const statusFile = document.getElementById("status-file");
const resultFile = document.getElementById("result-file");
const download = document.getElementById("download");
const resetBtn = document.getElementById("reset");
const backBtn = document.getElementById("back-btn");
const errorText = document.getElementById("error-text");

// 每个状态对应的步骤序号（用于高亮进度条；录音属于第 1→2 步之间的过渡）
const STEP_OF = { input: 1, recording: 1, converting: 2, result: 3, error: 1 };

function setState(name) {
    for (const [key, el] of Object.entries(panels)) {
        el.hidden = key !== name;
    }
    const current = STEP_OF[name] || 1;
    steps.forEach((el) => {
        const n = Number(el.dataset.step);
        el.classList.toggle("active", n === current);
        el.classList.toggle("done", n < current);
    });
}

function showError(message) {
    errorText.textContent = message;
    setState("error");
}

// ---- 高级选项 ----
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
onset.addEventListener("input", () => (document.getElementById("onset-val").textContent = Number(onset.value).toFixed(2)));
frame.addEventListener("input", () => (document.getElementById("frame-val").textContent = Number(frame.value).toFixed(2)));
minlen.addEventListener("input", () => (document.getElementById("minlen-val").textContent = Number(minlen.value).toFixed(2)));

// ---- 拖拽 / 选择文件 ----
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

// ---- 录音 ----
let mediaRecorder = null;
let recordedChunks = [];
let recTimer = null;
let recSeconds = 0;
let micStream = null;

function fmtTime(total) {
    const m = String(Math.floor(total / 60)).padStart(2, "0");
    const s = String(total % 60).padStart(2, "0");
    return `${m}:${s}`;
}

function stopRecTimer() {
    if (recTimer) { clearInterval(recTimer); recTimer = null; }
}

function releaseMic() {
    if (micStream) {
        micStream.getTracks().forEach((t) => t.stop());
        micStream = null;
    }
}

recordBtn.addEventListener("click", async () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showError("此浏览器不支持麦克风录音，请改用文件上传。");
        return;
    }
    // 点击后立即给出反馈，避免权限弹窗期间看起来“没反应”
    recordBtn.disabled = true;
    recLabel.textContent = "请求权限…";
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        micStream = stream;
        recordedChunks = [];
        const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
            ? "audio/webm;codecs=opus"
            : "";
        mediaRecorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
        mediaRecorder.ondataavailable = (e) => { if (e.data.size) recordedChunks.push(e.data); };
        mediaRecorder.onstop = () => {
            releaseMic();
            const blob = new Blob(recordedChunks, { type: mediaRecorder.mimeType || "audio/webm" });
            if (!blob.size) {
                showError("没有录到任何声音，请重试。");
                return;
            }
            submitFile(new File([blob], "recording.webm", { type: blob.type }));
        };
        mediaRecorder.start();
        recSeconds = 0;
        recTime.textContent = fmtTime(0);
        setState("recording");
        recTimer = setInterval(() => {
            recSeconds += 1;
            recTime.textContent = fmtTime(recSeconds);
        }, 1000);
    } catch (err) {
        releaseMic();
        showError("无法访问麦克风：" + err.message);
    } finally {
        recordBtn.disabled = false;
        recLabel.textContent = "录音";
    }
});

stopBtn.addEventListener("click", () => {
    stopRecTimer();
    if (mediaRecorder && mediaRecorder.state === "recording") mediaRecorder.stop();
});

cancelBtn.addEventListener("click", () => {
    stopRecTimer();
    if (mediaRecorder) {
        mediaRecorder.onstop = null; // 取消：不提交转换
        if (mediaRecorder.state === "recording") mediaRecorder.stop();
    }
    releaseMic();
    setState("input");
});

// ---- 提交到本地服务器转换 ----
function submitFile(file) {
    const displayName = file.name || "audio";
    statusFile.textContent = `文件：${displayName}`;
    setState("converting");

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
            resultFile.textContent = `「${displayName}」已转换为 MIDI`;
            setState("result");
        })
        .catch((err) => {
            showError("转换失败：" + err.message);
        });
}

// ---- 完成 / 出错后返回第 1 步 ----
resetBtn.addEventListener("click", () => {
    fileInput.value = "";
    setState("input");
});
backBtn.addEventListener("click", () => setState("input"));

setState("input");
