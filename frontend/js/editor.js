// "Create Spray": choose media → crop/trim/loop → options → preview → save to My Sprays.
import { api } from "./api.js";
import { Timeline } from "./timeline.js";
import { Cropper } from "./crop.js";
import { $, el, show, hide, toast, confirmDialog } from "./ui.js";

const TF2_FPS = 5;

const state = {
    jobId: null,
    media: null,
    timeline: null,
    cropper: null,
    onSaved: () => {},
};

export function initEditor({ onSaved }) {
    state.onSaved = onSaved;
    state.timeline = new Timeline($("#timeline"), $("#video"), { onChange: onSelectionChange });
    state.cropper = new Cropper({ onChange: onCropChange });
    api.config()
        .then((cfg) => {
            if (cfg.url_import_enabled) return;
            $("#urlInput").disabled = true;
            $("#urlBtn").disabled = true;
            $("#urlNote").textContent = "URL import is disabled on this server.";
        })
        .catch(() => {});
    wireImport();
    wireCrop();
    wireOptions();
    wireResult();
    $("#findLoopsBtn").addEventListener("click", findLoops);
}

export function importIntoEditor(file) {
    importFile(file);
}

const isAnimated = () => Boolean(state.media && state.media.animated && state.media.preview_video);
const sampleFps = () => parseFloat($("#optFps").value) || TF2_FPS;

// ------------------------------------------------------------------ import
function wireImport() {
    const zone = $("#dropzone");
    $("#fileInput").addEventListener("change", (e) => {
        if (e.target.files[0]) importFile(e.target.files[0]);
        e.target.value = "";
    });
    ["dragenter", "dragover"].forEach((type) =>
        zone.addEventListener(type, (e) => {
            e.preventDefault();
            zone.classList.add("drag");
        })
    );
    ["dragleave", "drop"].forEach((type) =>
        zone.addEventListener(type, (e) => {
            e.preventDefault();
            zone.classList.remove("drag");
        })
    );
    zone.addEventListener("drop", (e) => e.dataTransfer.files[0] && importFile(e.dataTransfer.files[0]));
    $("#urlBtn").addEventListener("click", () => {
        const url = $("#urlInput").value.trim();
        if (url) importUrl(url);
    });
}

function suggestName(filename) {
    const base = filename.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_.-]+/g, "_").replace(/^_+|_+$/g, "");
    return base.slice(0, 48) || "spray";
}

async function runImport(label, request, name) {
    const progress = $("#importProgress");
    $("#importProgressText").textContent = label;
    show(progress);
    hide($("#importError"));
    try {
        onImported(await request(), name);
    } catch (e) {
        $("#importError").textContent = `Import failed: ${e.message}`;
        show($("#importError"));
    } finally {
        hide(progress);
    }
}

const importFile = (file) => runImport("Uploading & analyzing…", () => api.uploadFile(file), suggestName(file.name));
const importUrl = (url) => runImport("Fetching from URL…", () => api.importUrl(url), null);

function onImported(res, name) {
    state.jobId = res.job_id;
    state.media = res.media;
    if (name) $("#optName").value = name;
    hide($("#resultCard"));
    setupEdit();
    show($("#editCard"));
    show($("#optionsCard"));
    $("#editCard").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ------------------------------------------------------------------ crop / trim / loop
function setupEdit() {
    const m = state.media;
    const animated = isAnimated();
    $("#srcMeta").textContent = `${m.width}×${m.height}${animated ? ` · ${m.duration}s · ${m.fps} fps` : " · image"}`;

    $("#staticPreviewWrap").classList.toggle("hidden", animated);
    $("#videoWrap").classList.toggle("hidden", !animated);
    $("#timeline").classList.toggle("hidden", !animated);
    $("#loopsPane").classList.toggle("hidden", !animated);
    $("#editGrid").classList.toggle("single", !animated);
    $("#boomerangField").classList.toggle("hidden", !animated);
    $("#fpsField").classList.toggle("hidden", !animated);
    $("#optAnimated").checked = animated;
    $("#optAnimated").disabled = !animated;
    $("#optBoomerang").checked = false;
    $("#loopList").replaceChildren();

    if (animated) {
        state.timeline.load(api.fileUrl(state.jobId, "preview.mp4"), { fps: m.fps, filmstrip: api.filmstripUrl(state.jobId) });
    } else {
        state.timeline.unload();
        $("#staticPreview").src = m.preview_image;
    }

    $("#cropEnable").checked = false;
    $("#cropLock").checked = false;
    $("#cropReadout").textContent = "";
    state.cropper.attachTo(animated ? $("#videoWrap") : $("#staticPreviewWrap"), animated ? $("#video") : $("#staticPreview"));
    state.cropper.setEnabled(false);

    scheduleEstimate();
    if (animated) findLoops();
}

function onSelectionChange() {
    scheduleEstimate();
    scheduleSeam();
}

let seamTimer = null;
function scheduleSeam() {
    clearTimeout(seamTimer);
    seamTimer = setTimeout(updateSeam, 300);
}

function updateSeam() {
    if (!isAnimated()) return;
    const sel = state.timeline.getSelection();
    if (!sel.duration) return;
    const fps = sampleFps();
    const frames = Math.max(1, Math.round(sel.duration * fps));
    $("#seamStart").src = api.frameUrl(state.jobId, sel.start, 160);
    $("#seamEnd").src = api.frameUrl(state.jobId, sel.start + (frames - 1) / fps, 160);
    $("#seamHint").textContent = $("#optBoomerang").checked
        ? "Boomerang plays the clip back in reverse, so it always loops seamlessly."
        : "The closer these two frames look, the smoother the spray loops.";
}

async function findLoops() {
    if (!isAnimated()) return;
    const jobId = state.jobId;
    show($("#loopsProgress"));
    $("#loopList").replaceChildren();
    state.timeline.setMarkers([], null);
    try {
        const res = await api.loops(jobId, { analysis_fps: 12, min_duration: 0.4, top_n: 6 });
        if (jobId === state.jobId) renderLoops(res.candidates || []);
    } catch (e) {
        if (jobId === state.jobId) $("#loopList").replaceChildren(el("li", { class: "muted small" }, `Loop analysis failed: ${e.message}`));
    } finally {
        if (jobId === state.jobId) hide($("#loopsProgress"));
    }
}

function renderLoops(candidates) {
    state.timeline.setMarkers(candidates, useLoop);
    if (!candidates.length) {
        $("#loopList").replaceChildren(
            el("li", { class: "muted small" }, "No clear loop found — trim it by hand, or tick Boomerang loop in step 3.")
        );
        return;
    }
    $("#loopList").replaceChildren(
        ...candidates.map((c, i) => {
            const pct = Math.round(c.similarity * 100);
            return el(
                "li",
                { class: `loop-item${i === 0 ? " best" : ""}`, dataset: { start: c.start_time } },
                el(
                    "div",
                    { class: "meta" },
                    el("div", {}, el("strong", {}, `${c.duration.toFixed(2)}s`), ` · ${c.start_time.toFixed(2)}–${c.end_time.toFixed(2)}s `, i === 0 && el("span", { class: "accent" }, "★ best")),
                    el("div", { class: "bar" }, el("i", { style: `width:${pct}%` })),
                    el("div", { class: "muted small" }, `${pct}% seamless · ${Math.max(1, Math.round(c.duration * sampleFps()))} spray frames`)
                ),
                el("button", { class: "btn small", onclick: () => useLoop(c) }, "Use")
            );
        })
    );
}

function useLoop(c) {
    state.timeline.setRange(c.start_time, c.end_time);
    state.timeline.seek(c.start_time);
    $("#optAnimated").checked = true;
    document.querySelectorAll("#loopList .loop-item").forEach((li) =>
        li.classList.toggle("active", li.dataset.start === String(c.start_time))
    );
}

function wireCrop() {
    $("#cropEnable").addEventListener("change", (e) => state.cropper.setEnabled(e.target.checked));
    $("#cropLock").addEventListener("change", (e) => state.cropper.setLock(e.target.checked));
    $("#cropReset").addEventListener("click", () => {
        if (!state.cropper.enabled) {
            $("#cropEnable").checked = true;
            state.cropper.setEnabled(true);
        }
        state.cropper.reset(0.7);
    });
}

function onCropChange(crop) {
    const readout = $("#cropReadout");
    if (!state.cropper || !state.cropper.enabled) {
        readout.textContent = "";
    } else if (!crop) {
        readout.textContent = "Full frame";
    } else {
        const m = state.media || { width: 0, height: 0 };
        readout.textContent = `Crop: ${Math.round(crop.w * m.width)}×${Math.round(crop.h * m.height)}px`;
    }
}

// ------------------------------------------------------------------ options + estimate
function wireOptions() {
    $("#optChromaTol").addEventListener("input", (e) => ($("#tolVal").textContent = e.target.value));
    $("#optChromaSoft").addEventListener("input", (e) => ($("#softVal").textContent = e.target.value));
    ["optFps", "optFormat", "optFit", "optMip", "optFade", "optMaxEdge", "optAnimated", "optChroma", "optBoomerang"].forEach((id) =>
        $(`#${id}`).addEventListener("change", scheduleEstimate)
    );
    ["optFps", "optBoomerang"].forEach((id) => $(`#${id}`).addEventListener("change", scheduleSeam));

    $("#fadeInput").addEventListener("change", async (e) => {
        const file = e.target.files[0];
        if (!file || !state.jobId) return;
        try {
            await api.uploadFade(state.jobId, file);
            $("#optFade").checked = true;
            scheduleEstimate();
        } catch (err) {
            toast(`Fade image upload failed: ${err.message}`, { kind: "error" });
        }
    });
    $("#convertBtn").addEventListener("click", convert);
}

function hexToRgb(hex) {
    const v = hex.replace("#", "");
    return [0, 2, 4].map((i) => parseInt(v.slice(i, i + 2), 16));
}

function selectionOpts(animated) {
    if (!isAnimated()) return {};
    const sel = state.timeline.getSelection();
    return animated ? { start: +sel.start.toFixed(3), duration: +sel.duration.toFixed(3) } : { start: +sel.start.toFixed(3) };
}

function sharedOpts() {
    const opts = {
        animated: $("#optAnimated").checked,
        fps: sampleFps(),
        boomerang: $("#optBoomerang").checked,
        format: $("#optFormat").value,
        fit_mode: $("#optFit").value,
        mipmaps: $("#optMip").checked,
        fade: $("#optFade").checked,
        chroma_key: $("#optChroma").checked,
    };
    const maxEdge = parseInt($("#optMaxEdge").value, 10);
    if (maxEdge) opts.max_edge = maxEdge;
    return opts;
}

function gatherOptions() {
    const opts = {
        ...sharedOpts(),
        name: $("#optName").value || "spray",
        point_sample: $("#optPoint").checked,
        chroma_tolerance: parseInt($("#optChromaTol").value, 10),
        chroma_softness: parseInt($("#optChromaSoft").value, 10),
        fade_from_level: parseInt($("#optFadeLevel").value, 10) || 2,
        translucent: true,
    };
    if (opts.chroma_key) opts.chroma_color = hexToRgb($("#optChromaColor").value);
    const crop = state.cropper.getCrop();
    if (crop) opts.crop = crop;
    return { ...opts, ...selectionOpts(opts.animated) };
}

let estimateTimer = null;
function scheduleEstimate() {
    if (!state.jobId) return;
    clearTimeout(estimateTimer);
    estimateTimer = setTimeout(runEstimate, 250);
}

async function runEstimate() {
    const box = $("#estimate");
    const opts = sharedOpts();
    const { duration } = selectionOpts(opts.animated);
    try {
        const r = await api.estimate(state.jobId, duration ? { ...opts, duration } : opts);
        if (!r.fits) {
            box.replaceChildren(el("span", { class: "bad" }, "⚠ Too many frames to fit in 512 KB — shorten the selection or lower the fps."));
            return;
        }
        const frames = r.frame_count > 1 ? `${r.frame_count} frames (${(r.frame_count / TF2_FPS).toFixed(1)}s in-game)` : "static";
        box.replaceChildren(
            "≈ ",
            el("strong", {}, `${r.width}×${r.height}`),
            ` · ${frames} · `,
            el("strong", {}, r.format),
            " · ",
            el("span", { class: r.size_kib < 512 ? "ok" : "bad" }, `${r.size_kib} KiB`)
        );
    } catch {
        box.replaceChildren();
    }
}

async function convert() {
    const error = $("#convertError");
    hide(error);
    show($("#convertProgress"));
    $("#convertBtn").disabled = true;
    try {
        renderResult(await api.convert(state.jobId, gatherOptions()));
    } catch (e) {
        error.textContent = `Conversion failed: ${e.message}`;
        show(error);
    } finally {
        hide($("#convertProgress"));
        $("#convertBtn").disabled = false;
    }
}

// ------------------------------------------------------------------ result + save
function renderResult(res) {
    show($("#resultCard"));
    const size = $("#resSize");
    size.textContent = `${res.size_kib} KiB`;
    size.className = res.within_limit ? "size-ok" : "size-bad";
    $("#resDims").textContent = `${res.width}×${res.height}`;
    $("#resFrames").textContent =
        res.frame_count > 1 ? `${res.frame_count} · ${(res.frame_count / TF2_FPS).toFixed(1)}s loop in-game` : "1 (static)";
    $("#resFormat").textContent = res.format;
    const warn = $("#resWarn");
    if (res.within_limit) {
        hide(warn);
    } else {
        warn.textContent = "⚠ Over 512 KB — TF2 will ignore this spray. Shorten the clip or lower the resolution.";
        show(warn);
    }
    $("#resultPreview").src = `${res.preview_url}?t=${Date.now()}`;
    $("#dlVtf").href = res.download_vtf;
    $("#dlVmt").href = res.download_vmt;
    $("#saveResult").textContent = "";
    $("#resultCard").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function save(overwrite = false) {
    const out = $("#saveResult");
    out.className = "small muted";
    out.textContent = "Saving…";
    try {
        const res = await api.saveToTf2(state.jobId, $("#optName").value || "spray", overwrite);
        out.className = "small size-ok";
        out.textContent = `✓ Saved as ${res.filename}`;
        toast(`Saved ${res.filename} to My Sprays.`, { kind: "success", action: "View", onAction: () => (location.hash = "#library") });
        state.onSaved(res.filename);
    } catch (e) {
        if (e.status === 409 && !overwrite) {
            if (await confirmDialog(`${e.message} Replace it with this new one?`, "Replace")) return save(true);
            out.textContent = "Not saved — change the spray name in step 3 to keep both.";
            return;
        }
        out.className = "small size-bad";
        out.textContent = `✗ ${e.message}`;
    }
}

function wireResult() {
    $("#saveTf2Btn").addEventListener("click", () => save());
    $("#startOverBtn").addEventListener("click", () => {
        ["editCard", "optionsCard", "resultCard"].forEach((id) => hide($(`#${id}`)));
        state.timeline.unload();
        state.cropper.setEnabled(false);
        state.jobId = null;
        state.media = null;
        $("#urlInput").value = "";
        $("#optName").value = "spray";
        $("#estimate").replaceChildren();
        window.scrollTo({ top: 0, behavior: "smooth" });
    });
}
