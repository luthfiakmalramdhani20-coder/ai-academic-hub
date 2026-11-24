// AI Academic Hub — frontend
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const md = (s) => marked.parse(String(s || ""));
const COLAB_URL = "https://colab.research.google.com/drive/1od03LHDqPUDkO_0LIAoTErJ7JwEgO1kM";
const MANUAL = "__manual__";
const AUDIO_EXT = [".mp3", ".m4a", ".wav", ".ogg", ".mp4", ".mkv", ".webm"];
const MATERI_EXT = [".txt", ".md", ".pptx", ".pdf", ".docx"];

let mode = "Kuliah";              // 'Kuliah' | 'Lain'
let historyItems = [];
let current = null;               // arsip yang sedang dibuka
let mm = null, activeTab = "ringkasan";
let sumber = "audio", mediaFile = null, materiFile = null, inboxUploads = [];
let busy = false;

// ---------------- API + auth Kreator ----------------
const getToken = () => sessionStorage.getItem("creatorToken") || "";
async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (getToken()) headers["X-Creator-Token"] = getToken();
  if (opts.json) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
  const r = await fetch(path, { ...opts, headers });
  if (r.status === 401 || r.status === 403) {
    let d = ""; try { d = (await r.json()).detail; } catch {}
    if (getToken()) setCreator(null);
    const err = new Error(d || "Khusus Kreator"); err.auth = true; throw err;
  }
  return r;
}
async function errText(r) { try { const d = await r.json(); return d.detail || JSON.stringify(d); } catch { return `HTTP ${r.status}`; } }

let pendingAction = null;
function setCreator(token) {
  if (token) sessionStorage.setItem("creatorToken", token); else sessionStorage.removeItem("creatorToken");
  const on = !!token, b = $("#btnCreator");
  b.textContent = on ? "🔓 Kreator Aktif" : "🔒 Mode Kreator";
  b.className = "px-3 py-1.5 rounded-lg border text-xs sm:text-sm font-semibold transition " +
    (on ? "bg-emerald-700 border-emerald-500 text-white" : "bg-slate-800 border-slate-600 text-slate-200 hover:bg-slate-700");
  $("#btnHimpunan")?.classList.toggle("hidden", mode !== "Kuliah");
}
function openCreatorModal(reason) {
  $("#creatorReason").textContent = reason || "Fitur ini khusus Kreator. Masukkan password untuk melanjutkan.";
  $("#creatorErr").classList.add("hidden");
  $("#creatorPw").value = "";
  $("#modalCreator").classList.remove("hidden");
  setTimeout(() => $("#creatorPw").focus(), 50);
}
/** Jalankan aksi khusus Kreator; jika belum terverifikasi, tampilkan modal password dulu. */
function requireCreator(action, reason) {
  if (getToken()) return action();
  pendingAction = action;
  openCreatorModal(reason);
}
async function creatorCall(fn) {   // bungkus aksi: 401/403 dari backend -> modal password
  try { return await fn(); }
  catch (e) {
    if (e.auth) { pendingAction = null; openCreatorModal(e.message); return; }
    throw e;
  }
}
$("#formCreator").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("#creatorErr");
  try {
    const r = await fetch("/api/auth/verify", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: $("#creatorPw").value }) });
    if (!r.ok) { err.textContent = await errText(r); err.classList.remove("hidden"); return; }
    setCreator((await r.json()).token);
    $("#modalCreator").classList.add("hidden");
    const act = pendingAction; pendingAction = null;
    if (act) act();
  } catch { err.textContent = "Gagal terhubung ke server."; err.classList.remove("hidden"); }
});
$("#btnCreator").addEventListener("click", () => {
  if (getToken()) { if (confirm("Keluar dari Mode Kreator?")) setCreator(null); }
  else openCreatorModal("Masukkan password Kreator untuk mengaktifkan mode Kreator.");
});
$$("[data-close]").forEach((b) => b.addEventListener("click", () => $("#" + b.dataset.close).classList.add("hidden")));

// ---------------- Navigasi ----------------
function show(view) {
  $$(".view").forEach((v) => v.classList.toggle("hidden", v.id !== "view-" + view));
  window.scrollTo({ top: 0 });
}
$$("[data-goto]").forEach((b) => b.addEventListener("click", () => show(b.dataset.goto)));
$("#brand").addEventListener("click", () => show(localStorage.getItem("hubUser") ? "home" : "landing"));
$$(".door").forEach((b) => b.addEventListener("click", () => openMode(b.dataset.mode)));
$("#btnBackMode").addEventListener("click", () => { show("mode"); renderHistory(); });

// ---------------- Landing / user ----------------
function setUser(u) {
  if (u) localStorage.setItem("hubUser", JSON.stringify(u)); else localStorage.removeItem("hubUser");
  const chip = $("#userChip");
  chip.classList.toggle("hidden", !u);
  if (u) chip.textContent = u.visitor ? "👀 Pengunjung" : "👤 " + (u.nama || u.nim);
}
$("#userChip").addEventListener("click", () => { if (confirm("Keluar dan kembali ke halaman awal?")) { setUser(null); show("landing"); } });
$("#btnVisitor").addEventListener("click", () => { setUser({ visitor: true }); show("home"); });
$$(".auth-tab").forEach((t) => t.addEventListener("click", () => {
  $$(".auth-tab").forEach((x) => x.classList.toggle("active", x === t));
  $("#formLogin").classList.toggle("hidden", t.dataset.t !== "login");
  $("#formDaftar").classList.toggle("hidden", t.dataset.t !== "daftar");
  $("#authMsg").classList.add("hidden");
}));
async function authPost(url, body) {
  const msg = $("#authMsg"); msg.classList.add("hidden");
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) { msg.textContent = await errText(r); msg.classList.remove("hidden"); return; }
  setUser(await r.json()); show("home");
}
$("#formLogin").addEventListener("submit", (e) => { e.preventDefault(); authPost("/api/users/login", { nim: $("#loginNim").value }); });
$("#formDaftar").addEventListener("submit", (e) => {
  e.preventDefault();
  authPost("/api/users/register", { nim: $("#regNim").value, nama: $("#regNama").value, kampus: $("#regKampus").value, prodi: $("#regProdi").value });
});

// ---------------- Status ----------------
fetch("/api/status").then((r) => r.json()).then((s) => {
  const badge = (ok, label) => `<span class="px-2 py-0.5 rounded-full ${ok ? "bg-emerald-900/60 text-emerald-300" : "bg-rose-900/60 text-rose-300"}">${ok ? "✓" : "✗"} ${label}</span>`;
  $("#statusBadges").innerHTML = badge(s.ffmpeg, "FFmpeg") + badge(s.groq_key, "Groq") + badge(s.gemini_key, "Gemini") + badge(s.creator_enabled, "Kreator");
}).catch(() => {});

// ---------------- Wizard ----------------
const MODES = {
  Kuliah: { title: "🏫 Transkrip Kegiatan Perkuliahan",
    fields: [{ k: "sem", label: "Semester", ph: "cth: Semester 3" }, { k: "mk", label: "Mata Kuliah", ph: "cth: Statistika Dasar" }, { k: "pt", label: "Pertemuan ke-", ph: "cth: Pertemuan 5" }] },
  Lain: { title: "🎤 Transkrip Kegiatan Lain",
    fields: [{ k: "mk", label: "Nama Kegiatan", ph: "cth: Seminar Nasional AI" }, { k: "pt", label: "Sesi / Bagian", ph: "cth: Sesi 1 - Pembukaan" }] },
};
const natural = (a, b) => a.localeCompare(b, "id", { numeric: true });
const uniq = (arr) => [...new Set(arr.filter(Boolean))];
const modeItems = () => historyItems.filter((h) => (mode === "Kuliah" ? h.kategori === "Kuliah" : h.kategori !== "Kuliah"));

function getVal(k) {
  const s = $("#f_" + k);
  if (!s) return "";
  return s.value === MANUAL ? ($("#m_" + k).value || "").trim() : s.value.trim();
}
function optionsFor(k) {
  const items = modeItems();
  if (k === "sem") return uniq([...Array.from({ length: 8 }, (_, i) => `Semester ${i + 1}`), ...items.map((h) => h.semester)]).sort(natural);
  if (k === "mk") return uniq(items.filter((h) => mode !== "Kuliah" || h.semester === getVal("sem")).map((h) => h.matkul)).sort(natural);
  const base = mode === "Kuliah" ? Array.from({ length: 16 }, (_, i) => `Pertemuan ${i + 1}`) : Array.from({ length: 8 }, (_, i) => `Sesi ${i + 1}`);
  return uniq([...base, ...items.filter((h) => h.matkul === getVal("mk") && (mode !== "Kuliah" || h.semester === getVal("sem"))).map((h) => h.pertemuan)]).sort(natural);
}
function existsAlready(k, v) {
  const items = modeItems().filter((h) => mode !== "Kuliah" || h.semester === getVal("sem"));
  if (k === "pt") return items.some((h) => h.matkul === getVal("mk") && h.pertemuan === v);
  return false;
}
function fillSelect(k) {
  const s = $("#f_" + k);
  if (s.value === MANUAL) return;
  const old = s.value;
  const opts = optionsFor(k);
  s.innerHTML = `<option value="">— Pilih —</option>` +
    opts.map((o) => `<option value="${esc(o)}">${esc(o)}${existsAlready(k, o) ? "  ✓ sudah ada" : ""}</option>`).join("") +
    `<option value="${MANUAL}">+ Tulis Manual</option>`;
  s.value = opts.includes(old) ? old : "";
}
function stepComplete(i) { return !!getVal(MODES[mode].fields[i].k); }

function renderWizard() {
  const cfg = MODES[mode], n = cfg.fields.length;
  $("#modeTitle").textContent = cfg.title;
  let html = `<div class="grid ${n === 3 ? "sm:grid-cols-3" : "sm:grid-cols-2"} gap-4">`;
  cfg.fields.forEach((f, i) => {
    html += `<div class="step" data-step="${i}">
      <div class="flex items-center gap-2 mb-3"><span class="step-num">${i + 1}</span><div><div class="text-[11px] uppercase tracking-wide text-slate-500">Tahap ${i + 1}</div><div class="font-semibold text-white leading-tight">${f.label}</div></div></div>
      <select id="f_${f.k}" class="inp"></select>
      <input id="m_${f.k}" class="inp mt-2 hidden" placeholder="${esc(f.ph)}">
    </div>`;
  });
  html += `</div>
  <div class="step" data-step="${n}">
    <div class="flex items-center gap-2 mb-3"><span class="step-num">${n + 1}</span><div><div class="text-[11px] uppercase tracking-wide text-slate-500">Tahap ${n + 1}</div><div class="font-semibold text-white leading-tight">Sumber Materi</div></div></div>
    <div class="grid sm:grid-cols-3 gap-2">
      <button class="src-tab active" data-src="audio">🎙️ Upload audio langsung <span class="block text-[11px] opacity-70">(Ditranskip Groq Whisper)</span></button>
      <button class="src-tab" data-src="inbox">📥 Tarik dari _INBOX_TRANSKRIP <span class="block text-[11px] opacity-70">(Hasil Colab V8)</span></button>
      <button class="src-tab" data-src="teks">📝 Tempel teks / Upload materi <span class="block text-[11px] opacity-70">(.txt, .md, .pptx, .pdf, .docx)</span></button>
    </div>
    <div class="mt-4" id="src-audio">
      <div class="dropzone" id="dropMedia"><input type="file" id="fileMedia" accept="${AUDIO_EXT.join(",")}" hidden>
        <div class="text-3xl">🎙️</div><div class="font-medium text-white">Audio / Video Rekaman</div>
        <div class="text-xs text-slate-400">.mp3 .m4a .wav .ogg .mp4 — maks 500 MB. Dipotong &amp; dikompres otomatis oleh FFmpeg di server.</div>
        <div class="file-name text-sm text-emerald-300 mt-1"></div></div>
    </div>
    <div class="mt-4 hidden space-y-3" id="src-inbox">
      <a href="${COLAB_URL}" target="_blank" rel="noopener" class="block text-center py-2.5 rounded-xl bg-amber-600 hover:bg-amber-500 font-semibold text-white">🚀 Transkrip File Besar / YouTube di Google Colab</a>
      <div><div class="text-sm text-slate-400 mb-1">File di folder <code>_INBOX_TRANSKRIP</code> server (centang untuk digabung):</div><div id="inboxList" class="space-y-1 text-sm"></div></div>
      <div class="dropzone" id="dropInbox"><input type="file" id="fileInbox" accept=".txt,.md" multiple hidden>
        <div class="text-2xl">📄</div><div class="font-medium text-white">Upload file .txt hasil Colab</div>
        <div class="text-xs text-slate-400">Boleh banyak file — akan digabung sesuai urutan nama</div>
        <div class="file-name text-sm text-emerald-300 mt-1"></div></div>
    </div>
    <div class="mt-4 hidden space-y-3" id="src-teks">
      <textarea id="teksArea" class="inp h-40 text-sm" placeholder="Tempel transkrip cadangan di sini (opsional jika melampirkan materi)..."></textarea>
      <div class="dropzone" id="dropMateri"><input type="file" id="fileMateri" accept="${MATERI_EXT.join(",")}" hidden>
        <div class="text-2xl">📑</div><div class="font-medium text-white">Materi Dosen <span class="text-slate-500">(opsional)</span></div>
        <div class="text-xs text-slate-400">.txt .md .pptx .pdf .docx — ikut dipakai AI pada sumber mana pun</div>
        <div class="file-name text-sm text-emerald-300 mt-1"></div></div>
    </div>
  </div>`;
  $("#wizard").innerHTML = html;

  cfg.fields.forEach((f) => {
    const sel = $("#f_" + f.k);
    sel.addEventListener("change", () => {
      $("#m_" + f.k).classList.toggle("hidden", sel.value !== MANUAL);
      if (sel.value === MANUAL) $("#m_" + f.k).focus();
      updateWizard();
    });
    $("#m_" + f.k).addEventListener("input", updateWizard);
  });
  $$(".src-tab").forEach((t) => t.addEventListener("click", () => {
    sumber = t.dataset.src;
    $$(".src-tab").forEach((x) => x.classList.toggle("active", x === t));
    ["audio", "inbox", "teks"].forEach((s) => $("#src-" + s).classList.toggle("hidden", s !== sumber));
    updateWizard();
  }));
  makeDrop("#dropMedia", "#fileMedia", AUDIO_EXT, 500, false, (fs) => { mediaFile = fs[0]; updateWizard(); });
  makeDrop("#dropMateri", "#fileMateri", MATERI_EXT, 200, false, (fs) => { materiFile = fs[0]; updateWizard(); });
  makeDrop("#dropInbox", "#fileInbox", [".txt", ".md"], 50, true, (fs) => { inboxUploads = fs; updateWizard(); });
  mediaFile = materiFile = null; inboxUploads = []; sumber = "audio";
  loadInbox();
  updateWizard();
}

function makeDrop(zoneSel, inputSel, exts, maxMB, multi, onFiles) {
  const zone = $(zoneSel), input = $(inputSel);
  const accept = (list) => {
    const ok = [];
    for (const f of list) {
      const ext = "." + f.name.split(".").pop().toLowerCase();
      if (!exts.includes(ext)) { alert(`Format ${ext} tidak didukung.\nGunakan: ${exts.join(" ")}`); continue; }
      if (f.size > maxMB * 1024 * 1024) { alert(`${f.name} terlalu besar (maks ${maxMB} MB).`); continue; }
      ok.push(f);
    }
    if (!ok.length) return;
    onFiles(multi ? ok : [ok[0]]);
    zone.classList.add("has-file");
    zone.querySelector(".file-name").textContent = ok.map((f) => `${f.name} (${(f.size / 1048576).toFixed(1)} MB)`).join(", ");
  };
  zone.addEventListener("click", () => input.click());
  input.addEventListener("change", () => accept([...input.files]));
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("drag"); accept([...e.dataTransfer.files]); });
}

async function loadInbox() {
  let list = [];
  try { list = await (await fetch("/api/inbox")).json(); } catch {}
  $("#inboxList").innerHTML = list.length
    ? list.map((f) => `<label class="flex items-center gap-2 p-2 rounded-lg bg-slate-900 border border-slate-800"><input type="checkbox" class="inbox-cb" value="${esc(f.name)}"> <span class="truncate">${esc(f.name)}</span> <span class="ml-auto text-xs text-slate-500">${(f.size / 1024).toFixed(0)} KB</span></label>`).join("")
    : `<p class="text-slate-500 text-xs">Belum ada file di folder inbox server — gunakan upload di bawah.</p>`;
}

/** Hitung bagian yang belum lengkap, kunci tahap berikutnya, perbarui dropdown bertingkat. */
function updateWizard() {
  const cfg = MODES[mode];
  cfg.fields.forEach((f) => fillSelect(f.k));
  let blocked = false;
  $$(".step").forEach((el) => {
    const i = +el.dataset.step;
    const isSrc = i === cfg.fields.length;
    const done = isSrc ? sourceMissing().length === 0 : stepComplete(i);
    el.classList.toggle("locked", blocked);
    el.classList.toggle("done", !blocked && done);
    el.classList.toggle("active", !blocked && !done);
    el.querySelectorAll("select,input,textarea,button").forEach((c) => { if (c.type !== "file") c.disabled = blocked; });
    if (!isSrc && !done) blocked = true;
  });
}
function sourceMissing() {
  if (sumber === "audio") return mediaFile ? [] : ["pilih file audio/video rekaman"];
  if (sumber === "inbox") return ($$(".inbox-cb:checked").length || inboxUploads.length) ? [] : ["centang/unggah minimal satu file .txt hasil Colab"];
  return ($("#teksArea")?.value.trim() || materiFile) ? [] : ["tempel teks transkrip atau lampirkan materi"];
}
document.addEventListener("change", (e) => { if (e.target.classList?.contains("inbox-cb")) updateWizard(); });
document.addEventListener("input", (e) => { if (e.target.id === "teksArea") updateWizard(); });

function missingList() {
  const cfg = MODES[mode], miss = [];
  cfg.fields.forEach((f, i) => { if (!getVal(f.k)) miss.push(`Tahap ${i + 1} — ${f.label} belum diisi`); });
  if (!miss.length) sourceMissing().forEach((m) => miss.push(`Tahap ${cfg.fields.length + 1} — Sumber Materi: ${m}`));
  else miss.push(`Tahap ${cfg.fields.length + 1} — Sumber Materi terkunci sampai tahap sebelumnya lengkap`);
  return miss;
}
function showWarn(list) {
  const w = $("#warnBox");
  if (!list.length) return w.classList.add("hidden");
  w.innerHTML = `<b>⚠️ Belum bisa dijalankan:</b><ul class="list-disc pl-5 mt-1">${list.map((m) => `<li>${esc(m)}</li>`).join("")}</ul>`;
  w.classList.remove("hidden");
  w.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// ---------------- Generate ----------------
$("#btnGenerate").addEventListener("click", () => {
  if (busy) return;
  const miss = missingList();
  showWarn(miss);
  if (miss.length) return;
  const pt = getVal("pt");
  if (existsAlready("pt", pt) && !confirm(`"${pt}" sudah ada di arsip. Timpa dengan hasil baru?`)) return;
  requireCreator(submitProcess, "Upload & generate baru khusus Kreator. Masukkan password.");
});

function submitProcess() {
  const fd = new FormData();
  fd.append("kategori", mode === "Kuliah" ? "Kuliah" : "Kegiatan Lain");
  fd.append("semester", mode === "Kuliah" ? getVal("sem") : "");
  fd.append("matkul", getVal("mk"));
  fd.append("pertemuan", getVal("pt"));
  fd.append("sumber", sumber);
  if (sumber === "audio") fd.append("media", mediaFile);
  if (sumber === "inbox") {
    $$(".inbox-cb:checked").forEach((c) => fd.append("inbox_names", c.value));
    inboxUploads.forEach((f) => fd.append("inbox_files", f));
  }
  if (sumber === "teks") fd.append("teks", $("#teksArea").value);
  if (materiFile) fd.append("materi", materiFile);

  startUI("Mengunggah file ke server...");
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/process");
  if (getToken()) xhr.setRequestHeader("X-Creator-Token", getToken());
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) setProgress(0, `Mengunggah file... ${Math.round((e.loaded / e.total) * 100)}%`); };
  xhr.onload = () => {
    let data = {};
    try { data = JSON.parse(xhr.responseText); } catch {}
    if (xhr.status === 401 || xhr.status === 403) { endUI(); setCreator(null); $("#progressSection").classList.add("hidden"); return openCreatorModal(data.detail); }
    if (xhr.status !== 200) { showError(`Server menolak (HTTP ${xhr.status})`, data.detail || xhr.responseText); return endUI(); }
    logLine("Upload selesai. Memulai proses...");
    listen(data.job_id);
  };
  xhr.onerror = () => { showError("Gagal terhubung ke server", "Periksa koneksi / pastikan server berjalan."); endUI(); };
  xhr.send(fd);
}

// ---------------- Progress ----------------
const STEPS = ["1 Potong audio", "2 Transkrip", "3 Materi", "4 AI Gemini", "5 Simpan"];
function startUI(msg) {
  busy = true;
  $("#btnGenerate").disabled = true;
  $("#progressSection").classList.remove("hidden");
  $("#errorBox").classList.add("hidden");
  $("#progressLog").innerHTML = "";
  $("#stepper").innerHTML = STEPS.map((s) => `<div class="stp">${s}</div>`).join("");
  setProgress(0, msg);
  $("#progressSection").scrollIntoView({ behavior: "smooth", block: "nearest" });
}
function endUI() { busy = false; $("#btnGenerate").disabled = false; }
function setStep(n) { $$("#stepper .stp").forEach((el, i) => { el.className = "stp " + (i + 1 < n ? "ok" : i + 1 === n ? "on" : ""); }); }
function setProgress(pct, msg) {
  if (pct != null) { $("#progressBar").style.width = pct + "%"; $("#progressPct").textContent = pct + "%"; }
  if (msg) $("#progressMsg").textContent = msg;
}
function logLine(text, cls = "") {
  const d = document.createElement("div");
  d.className = cls;
  d.textContent = `[${new Date().toLocaleTimeString("id-ID")}] ${text}`;
  $("#progressLog").appendChild(d);
  $("#progressLog").scrollTop = 1e9;
}
function showError(title, detail) {
  $("#progressSection").classList.remove("hidden");
  $("#errorBox").classList.remove("hidden");
  $("#errorTitle").textContent = "❌ " + title;
  let pretty = detail || "";
  try { pretty = JSON.stringify(JSON.parse(detail), null, 2); } catch {}
  $("#errorDetail").textContent = pretty;
}
function listen(jobId) {
  const es = new EventSource(`/api/progress/${jobId}`);
  let ended = false;
  es.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.type === "progress") { setProgress(ev.percent, ev.message); if (ev.step) setStep(ev.step); logLine(ev.message); }
    else if (ev.type === "warning") logLine("⚠️ " + ev.message, "text-amber-300");
    else if (ev.type === "error") {
      ended = true; es.close(); endUI();
      setProgress(null, "Proses gagal.");
      logLine("❌ " + ev.message, "text-rose-300");
      showError(ev.message, ev.detail);
      loadHistory();
    } else if (ev.type === "done") {
      ended = true; es.close(); endUI(); setStep(6);
      setProgress(100, "✅ Selesai! Membuka hasil...");
      logLine("Selesai.", "text-emerald-300");
      loadHistory().then(() => openArchive(ev.arsip_id));
    }
  };
  es.onerror = () => {
    if (ended) return;
    es.close(); endUI();
    showError("Koneksi progres terputus", "Server mungkin berhenti/restart. Cek arsip — proses bisa saja sudah selesai.");
  };
}

// ---------------- Arsip ----------------
async function loadHistory() {
  try { historyItems = await (await fetch("/api/history")).json(); } catch { historyItems = []; }
  $("#countKuliah").textContent = `${historyItems.filter((h) => h.kategori === "Kuliah").length} arsip tersedia →`;
  $("#countLain").textContent = `${historyItems.filter((h) => h.kategori !== "Kuliah").length} arsip tersedia →`;
  if (!$("#view-mode").classList.contains("hidden")) { renderHistory(); if ($("#f_mk")) updateWizard(); }
}
function renderHistory() {
  const q = $("#historySearch").value.toLowerCase().trim();
  const items = modeItems().filter((h) => `${h.semester} ${h.matkul} ${h.pertemuan}`.toLowerCase().includes(q));
  if (!items.length) { $("#historyList").innerHTML = `<p class="text-slate-500 text-center mt-6">${q ? "Tidak ada yang cocok." : "Belum ada arsip."}</p>`; return; }
  const groups = {};
  items.forEach((h) => {
    const top = mode === "Kuliah" ? h.semester || "Tanpa Semester" : h.matkul;
    const sub = mode === "Kuliah" ? h.matkul : "";
    ((groups[top] ??= {})[sub] ??= []).push(h);
  });
  const btn = (h) => `<button data-id="${esc(h.id)}" class="hist-item ${current && current.arsip_id === h.id ? "on" : ""}">${h.tipe === "himpunan" ? "📚 " : ""}${esc(mode === "Kuliah" ? h.pertemuan : h.pertemuan)}<span class="block text-[10px] text-slate-500">${esc(h.dibuat)}</span></button>`;
  let html = "";
  for (const top of Object.keys(groups).sort(natural)) {
    html += `<details class="mb-2" ${q ? "open" : ""}><summary class="px-2 py-1.5 rounded-lg bg-slate-900 text-slate-200 font-medium">📁 ${esc(top)}</summary><div class="pl-2 mt-1">`;
    for (const sub of Object.keys(groups[top]).sort(natural)) {
      const list = groups[top][sub].sort((a, b) => natural(a.pertemuan, b.pertemuan));
      if (sub) html += `<details ${q ? "open" : ""} class="mb-1"><summary class="px-2 py-1 text-slate-300">📘 ${esc(sub)} <span class="text-xs text-slate-500">(${list.length})</span></summary><div class="pl-3">${list.map(btn).join("")}</div></details>`;
      else html += list.map(btn).join("");
    }
    html += `</div></details>`;
  }
  $("#historyList").innerHTML = html;
  $$(".hist-item").forEach((b) => b.addEventListener("click", () => openArchive(b.dataset.id)));
}
$("#historySearch").addEventListener("input", renderHistory);
$("#refreshHistory").addEventListener("click", loadHistory);

function openMode(m) {
  mode = m;
  $("#historySearch").value = "";
  $("#btnHimpunan").classList.toggle("hidden", m !== "Kuliah");
  $("#warnBox").classList.add("hidden");
  if (!busy) $("#progressSection").classList.add("hidden");
  show("mode");
  renderWizard();
  renderHistory();
}

async function openArchive(id) {
  const r = await fetch(`/api/archive?id=${encodeURIComponent(id)}`);
  if (!r.ok) return alert("Gagal membuka arsip: " + (await errText(r)));
  current = await r.json();
  const m = current.metadata || {};
  mode = m.kategori === "Kuliah" ? "Kuliah" : "Lain";
  renderResult();
  show("result");
}

// ---------------- Tabs ----------------
$$(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
function switchTab(name) {
  activeTab = name;
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".tab-panel").forEach((p) => p.classList.toggle("hidden", p.id !== "panel-" + name));
  if (name === "mindmap") renderMindmap();
}

// ---------------- Render hasil ----------------
function renderResult() {
  const c = current, m = c.metadata || {};
  $("#resultTitle").textContent = `${m.matkul || ""} — ${m.pertemuan || ""}`;
  $("#resultMeta").textContent = `${m.kategori || ""} · ${m.semester || "-"} · dibuat ${c.dibuat || ""}${c.diedit ? " · diedit " + c.diedit : ""} · model ${c.model || "-"}`;
  $("#panel-ringkasan").innerHTML = md(c.ringkasan);
  $("#catatanView").innerHTML = md(c.catatan);
  cancelEdit();
  $("#trSearch").value = "";
  drawTranscript();
  const id = encodeURIComponent(c.arsip_id);
  $("#dlTxt").href = `/api/download?id=${id}&file=transkrip.txt`;
  $("#dlMd").href = `/api/download?id=${id}&file=catatan.md`;
  renderFlashcards();
  renderQuiz();
  if (mm) { $("#mindmapSvg").innerHTML = ""; mm = null; }
  switchTab(activeTab);
}

// Transkrip + pencarian
function drawTranscript() {
  const text = (current && current.transkrip) || "";
  const q = $("#trSearch").value.trim();
  let html = esc(text), n = 0;
  if (q) {
    const re = new RegExp(esc(q).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
    html = html.replace(re, (m) => { n++; return `<mark>${m}</mark>`; });
  }
  $("#transkripText").innerHTML = html;
  $("#trCount").textContent = q ? `${n} hasil` : "";
  if (q) $("#transkripText").querySelector("mark")?.scrollIntoView({ block: "center" });
}
$("#trSearch").addEventListener("input", drawTranscript);
$("#copyTranscript").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(current?.transkrip || ""); $("#copyTranscript").textContent = "✓ Tersalin"; }
  catch { $("#copyTranscript").textContent = "Gagal menyalin"; }
  setTimeout(() => ($("#copyTranscript").textContent = "📋 Salin"), 1500);
});

// ---------------- Download .docx & cetak ----------------
$("#btnDocx").addEventListener("click", async () => {
  if (!current) return;
  const btn = $("#btnDocx"), label = btn.innerHTML;
  btn.disabled = true; btn.textContent = "⏳ Menyusun dokumen Word...";
  try {
    const r = await fetch(`/api/export-docx/${current.arsip_id.split("/").map(encodeURIComponent).join("/")}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${(await r.text()).slice(0, 300)}`);
    const cd = r.headers.get("Content-Disposition") || "";
    const fm = cd.match(/filename\*=UTF-8''([^;]+)/) || cd.match(/filename="([^"]+)"/);
    const url = URL.createObjectURL(await r.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: fm ? decodeURIComponent(fm[1]) : "Laporan.docx" });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (e) { alert("Gagal membuat dokumen .docx\n" + e.message); }
  finally { btn.disabled = false; btn.innerHTML = label; }
});
$("#btnPrint").addEventListener("click", () => {
  if (!current) return;
  const m = current.metadata || {};
  const w = window.open("", "_blank");
  if (!w) return alert("Pop-up diblokir browser. Izinkan pop-up untuk mencetak.");
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(m.matkul)} — ${esc(m.pertemuan)}</title>
  <style>body{font-family:Calibri,Arial,sans-serif;max-width:800px;margin:2rem auto;line-height:1.6;color:#111}h1,h2,h3{color:#1e3a8a}table{border-collapse:collapse}td,th{border:1px solid #999;padding:4px 8px}code{background:#eee;padding:0 3px}</style></head><body>
  <h1>${esc(m.matkul)} — ${esc(m.pertemuan)}</h1><p><small>${esc(m.semester || "")} · ${esc(current.dibuat || "")}</small></p>
  <h2>Ringkasan Kontekstual</h2>${md(current.ringkasan)}<hr><h2>Catatan Komprehensif</h2>${md(current.catatan)}</body></html>`);
  w.document.close();
  setTimeout(() => w.print(), 500);
});

// ---------------- Aksi Kreator pada hasil ----------------
$("#btnRegen").addEventListener("click", () => requireCreator(() => {
  if (!confirm("Generate ulang catatan, ringkasan, mind map, flashcard & kuis dari transkrip tersimpan? Hasil lama akan ditimpa.")) return;
  creatorCall(async () => {
    const r = await api("/api/regenerate", { method: "POST", json: { id: current.arsip_id } });
    if (!r.ok) return alert(await errText(r));
    const { job_id } = await r.json();
    openMode(mode);
    startUI("Memulai re-generate...");
    listen(job_id);
  });
}, "Re-generate khusus Kreator. Masukkan password."));

$("#btnEdit").addEventListener("click", () => requireCreator(() => {
  switchTab("catatan");
  $("#catatanArea").value = current.catatan || "";
  $("#catatanView").classList.add("hidden");
  $("#catatanEdit").classList.remove("hidden");
}, "Edit catatan khusus Kreator. Masukkan password."));
function cancelEdit() { $("#catatanView").classList.remove("hidden"); $("#catatanEdit").classList.add("hidden"); }
$("#cancelEdit").addEventListener("click", cancelEdit);
$("#saveEdit").addEventListener("click", () => creatorCall(async () => {
  const r = await api("/api/archive", { method: "PUT", json: { id: current.arsip_id, catatan: $("#catatanArea").value } });
  if (!r.ok) return alert(await errText(r));
  current.catatan = $("#catatanArea").value;
  renderResult();
}));

$("#btnDelete").addEventListener("click", () => requireCreator(() => {
  if (!confirm(`Hapus permanen arsip "${current.metadata.matkul} — ${current.metadata.pertemuan}"? Tidak bisa dibatalkan.`)) return;
  creatorCall(async () => {
    const r = await api(`/api/archive?id=${encodeURIComponent(current.arsip_id)}`, { method: "DELETE" });
    if (!r.ok) return alert(await errText(r));
    current = null;
    await loadHistory();
    openMode(mode);
  });
}, "Hapus arsip khusus Kreator. Masukkan password."));

// ---------------- Himpunan UTS/UAS ----------------
$("#btnHimpunan").addEventListener("click", () => {
  const items = historyItems.filter((h) => h.kategori === "Kuliah" && h.tipe !== "himpunan");
  const sems = uniq(items.map((h) => h.semester)).sort(natural);
  if (!sems.length) return alert("Belum ada arsip perkuliahan untuk dihimpun.");
  $("#hmSem").innerHTML = sems.map((s) => `<option>${esc(s)}</option>`).join("");
  fillHmMk();
  $("#hmErr").classList.add("hidden");
  $("#modalHimpunan").classList.remove("hidden");
});
function fillHmMk() {
  const items = historyItems.filter((h) => h.kategori === "Kuliah" && h.tipe !== "himpunan" && h.semester === $("#hmSem").value);
  $("#hmMk").innerHTML = uniq(items.map((h) => h.matkul)).sort(natural).map((s) => `<option>${esc(s)}</option>`).join("");
  fillHmList();
}
function fillHmList() {
  const items = historyItems.filter((h) => h.kategori === "Kuliah" && h.tipe !== "himpunan" && h.semester === $("#hmSem").value && h.matkul === $("#hmMk").value)
    .sort((a, b) => natural(a.pertemuan, b.pertemuan));
  $("#hmList").innerHTML = items.map((h) => `<label class="flex items-center gap-2 p-2 rounded-lg bg-slate-900 border border-slate-800"><input type="checkbox" class="hm-cb" value="${esc(h.id)}" checked> ${esc(h.pertemuan)}</label>`).join("");
}
$("#hmSem").addEventListener("change", fillHmMk);
$("#hmMk").addEventListener("change", fillHmList);
$("#hmGo").addEventListener("click", () => {
  const ids = [...$$(".hm-cb:checked")].map((c) => c.value);
  if (ids.length < 2) { $("#hmErr").textContent = "Pilih minimal 2 pertemuan."; return $("#hmErr").classList.remove("hidden"); }
  requireCreator(() => creatorCall(async () => {
    const r = await api("/api/himpunan", { method: "POST", json: { semester: $("#hmSem").value, matkul: $("#hmMk").value, jenis: document.querySelector("[name=hmJenis]:checked").value, ids } });
    if (!r.ok) { $("#hmErr").textContent = await errText(r); return $("#hmErr").classList.remove("hidden"); }
    $("#modalHimpunan").classList.add("hidden");
    const { job_id } = await r.json();
    startUI("Menyusun himpunan...");
    listen(job_id);
  }), "Membuat Himpunan UTS/UAS khusus Kreator. Masukkan password.");
});

// ---------------- Mind map ----------------
function renderMindmap() {
  if (!current) return;
  const { Transformer, Markmap } = window.markmap || {};
  if (!Transformer || !Markmap) { $("#panel-mindmap").insertAdjacentHTML("beforeend", "<p class='text-rose-300'>Library Markmap gagal dimuat (cek koneksi internet).</p>"); return; }
  const src = String(current.mindmap || "# (Mind map kosong)").replace(/^```(?:markdown|md)?\s*|\s*```$/g, "");
  const { root } = new Transformer().transform(src);
  requestAnimationFrame(() => {
    if (!mm) mm = Markmap.create("#mindmapSvg", { duration: 400, maxWidth: 280, color: (n) => d3.schemeTableau10[(n.state?.depth ?? 0) % 10] }, root);
    else mm.setData(root);
    mm.fit();
  });
}
$("#mmFit").addEventListener("click", () => mm && mm.fit());

// ---------------- Flashcard ----------------
let fcIndex = 0, fcOrder = [];
function renderFlashcards() {
  fcOrder = (current.flashcards || []).map((_, i) => i);
  fcIndex = 0;
  drawFlashcard();
}
function drawFlashcard() {
  const cards = current.flashcards || [];
  const p = $("#panel-flashcard");
  if (!cards.length) { p.innerHTML = "<p class='text-slate-500'>Tidak ada flashcard.</p>"; return; }
  const c = cards[fcOrder[fcIndex]];
  p.innerHTML = `
    <div class="max-w-xl mx-auto">
      <div class="fc-wrap"><div class="fc" id="fcCard">
        <div class="fc-face fc-front"><div>${esc(c.depan ?? c.front ?? c.pertanyaan)}<div class="text-xs text-sky-300 mt-4">klik untuk membalik</div></div></div>
        <div class="fc-face fc-back"><div>${esc(c.belakang ?? c.back ?? c.jawaban)}</div></div>
      </div></div>
      <div class="flex items-center justify-between mt-4">
        <button id="fcPrev" class="btn-dl">← Sebelumnya</button>
        <span class="text-sm text-slate-400">${fcIndex + 1} / ${cards.length}</span>
        <button id="fcNext" class="btn-dl">Berikutnya →</button>
      </div>
      <div class="text-center mt-3"><button id="fcShuffle" class="text-xs text-sky-300 hover:underline">🔀 Acak urutan</button></div>
    </div>`;
  $("#fcCard").addEventListener("click", () => $("#fcCard").classList.toggle("flipped"));
  $("#fcPrev").addEventListener("click", () => { fcIndex = (fcIndex - 1 + cards.length) % cards.length; drawFlashcard(); });
  $("#fcNext").addEventListener("click", () => { fcIndex = (fcIndex + 1) % cards.length; drawFlashcard(); });
  $("#fcShuffle").addEventListener("click", () => { fcOrder.sort(() => Math.random() - 0.5); fcIndex = 0; drawFlashcard(); });
}

// ---------------- Kuis ----------------
function renderQuiz() {
  const qs = current.kuis || [];
  const p = $("#panel-kuis");
  if (!qs.length) { p.innerHTML = "<p class='text-slate-500'>Tidak ada soal kuis.</p>"; return; }
  const answers = new Array(qs.length).fill(null);
  p.innerHTML = `<div id="quizScore" class="hidden mb-4 p-4 rounded-xl bg-sky-950 border border-sky-700 text-center"></div>` +
    qs.map((q, i) => `
      <div class="mb-5 p-4 rounded-xl bg-slate-950 border border-slate-800" data-q="${i}">
        <div class="font-medium text-slate-100">${i + 1}. ${esc(q.pertanyaan)}</div>
        ${(q.pilihan || []).map((o, j) => `<button class="opt" data-q="${i}" data-o="${j}">${"ABCD"[j] || j + 1}. ${esc(o)}</button>`).join("")}
        <div class="explain hidden mt-3 text-sm p-3 rounded-lg bg-slate-900 border border-slate-700"></div>
      </div>`).join("") +
    `<div class="flex gap-3"><button id="quizCheck" class="flex-1 py-2.5 rounded-xl bg-sky-600 hover:bg-sky-500 font-semibold text-white disabled:opacity-50">Periksa Jawaban</button>
     <button id="quizReset" class="px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700">Ulangi</button></div>`;
  p.querySelectorAll(".opt").forEach((b) => b.addEventListener("click", () => {
    const qi = +b.dataset.q;
    answers[qi] = +b.dataset.o;
    p.querySelectorAll(`.opt[data-q="${qi}"]`).forEach((x) => x.classList.toggle("selected", x === b));
  }));
  $("#quizCheck").addEventListener("click", () => {
    let score = 0;
    qs.forEach((q, i) => {
      const correct = Number(q.jawaban);
      if (answers[i] === correct) score++;
      p.querySelectorAll(`.opt[data-q="${i}"]`).forEach((x) => {
        const o = +x.dataset.o;
        x.disabled = true;
        x.classList.remove("selected");
        if (o === correct) x.classList.add("correct");
        else if (o === answers[i]) x.classList.add("wrong");
      });
      const ex = p.querySelector(`[data-q="${i}"] .explain`);
      ex.classList.remove("hidden");
      const ok = answers[i] === correct;
      ex.innerHTML = `<span class="${ok ? "text-emerald-300" : "text-rose-300"} font-semibold">${ok ? "✓ Benar" : answers[i] === null ? "— Tidak dijawab" : "✗ Salah"}</span>
        · Jawaban: <b>${"ABCD"[correct] || ""}</b><div class="mt-1 text-slate-300">${esc(q.pembahasan)}</div>`;
    });
    const pct = Math.round((score / qs.length) * 100);
    const s = $("#quizScore");
    s.classList.remove("hidden");
    s.innerHTML = `<div class="text-3xl font-bold text-white">${score} / ${qs.length}</div><div class="text-sky-300">Skor ${pct} — ${pct >= 80 ? "Luar biasa! 🎉" : pct >= 60 ? "Bagus, tingkatkan lagi 💪" : "Ayo pelajari ulang catatannya 📖"}</div>`;
    s.scrollIntoView({ behavior: "smooth", block: "center" });
    $("#quizCheck").disabled = true;
  });
  $("#quizReset").addEventListener("click", renderQuiz);
}

// ---------------- Init ----------------
(async function init() {
  setCreator(getToken() || null);
  try {
    const c = await (await fetch("/api/auth/check", { headers: getToken() ? { "X-Creator-Token": getToken() } : {} })).json();
    if (getToken() && !c.creator) setCreator(null);
  } catch {}
  await loadHistory();
  let u = null; try { u = JSON.parse(localStorage.getItem("hubUser")); } catch {}
  setUser(u);
  show(u ? "home" : "landing");
})();
