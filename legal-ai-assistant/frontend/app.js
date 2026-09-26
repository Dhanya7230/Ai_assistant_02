// Legal Document Assistant — frontend logic.
// No frameworks/build step by design: keeps the app auditable and fast to ship.
//
// The backend is stateless: after upload, THIS PAGE holds the extracted
// document text in memory (state.documentText) and sends it back with
// every subsequent request. Nothing about the document persists on the
// server between requests — see backend/main.py for why.

const API_BASE = ""; // same-origin

const state = {
  documentText: null,
  compareDocumentText: null,
};

const els = {
  uploadForm: document.getElementById("upload-form"),
  fileInput: document.getElementById("file-input"),
  uploadStatus: document.getElementById("upload-status"),
  uploadPreview: document.getElementById("upload-preview"),
  previewText: document.getElementById("preview-text"),
  actionsSection: document.getElementById("actions-section"),
  btnSimplify: document.getElementById("btn-simplify"),
  btnChecklist: document.getElementById("btn-checklist"),
  askForm: document.getElementById("ask-form"),
  questionInput: document.getElementById("question-input"),
  compareForm: document.getElementById("compare-form"),
  compareFileInput: document.getElementById("compare-file-input"),
  compareStatus: document.getElementById("compare-status"),
  btnCompare: document.getElementById("btn-compare"),
  results: document.getElementById("results"),
};

function setStatus(el, message, isError = false) {
  el.textContent = message;
  el.classList.toggle("status-error", isError);
}

function setBusy(button, busy, busyLabel) {
  if (busy) {
    button.dataset.originalLabel = button.textContent;
    button.textContent = busyLabel || "Working…";
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalLabel || button.textContent;
    button.disabled = false;
  }
}

// Minimal, dependency-free Markdown -> HTML for the limited subset the
// backend actually produces (headings, bullets, checkboxes, bold).
function renderMarkdown(md) {
  const escape = (s) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  const lines = escape(md).split("\n");
  let html = "";
  let inList = false;

  const closeList = () => {
    if (inList) {
      html += "</ul>";
      inList = false;
    }
  };

  for (let line of lines) {
    const heading = line.match(/^(#{1,3})\s+(.*)/);
    const checkbox = line.match(/^-\s+\[( |x)\]\s+(.*)/i);
    const bullet = line.match(/^-\s+(.*)/);

    if (heading) {
      closeList();
      const level = heading[1].length + 2; // ## -> h4, keeps page hierarchy sane
      html += `<h${level}>${inlineFormat(heading[2])}</h${level}>`;
    } else if (checkbox) {
      if (!inList) {
        html += "<ul class='checklist'>";
        inList = true;
      }
      const checked = checkbox[1].toLowerCase() === "x";
      html += `<li><label><input type="checkbox" disabled ${checked ? "checked" : ""}/> ${inlineFormat(checkbox[2])}</label></li>`;
    } else if (bullet) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      html += `<li>${inlineFormat(bullet[1])}</li>`;
    } else if (line.trim() === "") {
      closeList();
    } else {
      closeList();
      html += `<p>${inlineFormat(line)}</p>`;
    }
  }
  closeList();
  return html;
}

function inlineFormat(text) {
  return text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function showResult(title, markdown) {
  els.results.innerHTML = `<h3>${title}</h3>${renderMarkdown(markdown)}`;
}

async function apiRequest(path, formData) {
  const resp = await fetch(API_BASE + path, { method: "POST", body: formData });
  let data;
  try {
    data = await resp.json();
  } catch {
    throw new Error("Unexpected server response.");
  }
  if (!resp.ok) {
    throw new Error(data.detail || `Request failed (${resp.status}).`);
  }
  return data;
}

els.uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = els.fileInput.files[0];
  if (!file) return;

  setStatus(els.uploadStatus, "Uploading…");
  const fd = new FormData();
  fd.append("file", file);

  try {
    const data = await apiRequest("/api/upload", fd);
    state.documentText = data.text;
    setStatus(els.uploadStatus, `Uploaded "${data.filename}".`);
    els.previewText.textContent = data.preview;
    els.uploadPreview.hidden = false;
    els.actionsSection.hidden = false;
    els.btnCompare.disabled = !els.compareFileInput.files[0];
  } catch (err) {
    setStatus(els.uploadStatus, err.message, true);
  }
});

els.btnSimplify.addEventListener("click", async () => {
  if (!state.documentText) return;
  setBusy(els.btnSimplify, true, "Analyzing…");
  try {
    const fd = new FormData();
    fd.append("document_text", state.documentText);
    const data = await apiRequest("/api/simplify", fd);
    showResult("Plain-Language Analysis", data.result);
  } catch (err) {
    showResult("Error", `**${err.message}**`);
  } finally {
    setBusy(els.btnSimplify, false);
  }
});

els.btnChecklist.addEventListener("click", async () => {
  if (!state.documentText) return;
  setBusy(els.btnChecklist, true, "Generating…");
  try {
    const fd = new FormData();
    fd.append("document_text", state.documentText);
    const data = await apiRequest("/api/checklist", fd);
    showResult("Checklist", data.result);
  } catch (err) {
    showResult("Error", `**${err.message}**`);
  } finally {
    setBusy(els.btnChecklist, false);
  }
});

els.askForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.documentText) return;
  const question = els.questionInput.value.trim();
  if (!question) return;

  const submitBtn = els.askForm.querySelector("button[type=submit]");
  setBusy(submitBtn, true, "Asking…");
  try {
    const fd = new FormData();
    fd.append("document_text", state.documentText);
    fd.append("question", question);
    const data = await apiRequest("/api/ask", fd);
    showResult(`Answer: "${question}"`, data.result);
  } catch (err) {
    showResult("Error", `**${err.message}**`);
  } finally {
    setBusy(submitBtn, false);
  }
});

els.compareFileInput.addEventListener("change", () => {
  els.btnCompare.disabled = !(state.documentText && els.compareFileInput.files[0]);
});

els.compareForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = els.compareFileInput.files[0];
  if (!file || !state.documentText) return;

  setStatus(els.compareStatus, "Uploading second document…");
  try {
    const fd = new FormData();
    fd.append("file", file);
    const uploadData = await apiRequest("/api/upload", fd);
    state.compareDocumentText = uploadData.text;

    setBusy(els.btnCompare, true, "Comparing…");
    const compareFd = new FormData();
    compareFd.append("document_text_a", state.documentText);
    compareFd.append("document_text_b", state.compareDocumentText);
    const data = await apiRequest("/api/compare", compareFd);
    setStatus(els.compareStatus, "Comparison complete.");
    showResult("Document Comparison", data.result);
  } catch (err) {
    setStatus(els.compareStatus, err.message, true);
  } finally {
    setBusy(els.btnCompare, false);
  }
});
