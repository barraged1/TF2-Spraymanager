// "My Sprays": browse, search, preview, import, delete (with undo), and rotation controls.
import { api } from "./api.js";
import { $, el, show, hide, toast, confirmDialog, formatSize } from "./ui.js";

const TF2_FPS = 5;

const state = {
    data: null,
    highlight: null,
    dialogSpray: null,
    onMediaDropped: () => {},
};

const stop = (e) => e.stopPropagation();
const isVisible = () => !$("#view-library").classList.contains("hidden");
const stem = (filename) => filename.replace(/\.vtf$/i, "");
const isStart = (spray) => {
    const { installed, start } = state.data.rotation;
    return installed && Boolean(start) && start.toLowerCase() === spray.filename.toLowerCase();
};

export function initLibrary({ onMediaDropped }) {
    state.onMediaDropped = onMediaDropped;
    $("#libSearch").addEventListener("input", render);
    $("#libSort").addEventListener("change", render);
    $("#vtfInput").addEventListener("change", (e) => {
        importFiles([...e.target.files]);
        e.target.value = "";
    });
    $("#rotEnabled").addEventListener("change", (e) => setRotation(e.target.checked));
    $("#rotShuffle").addEventListener("click", shuffle);
    $("#rotStart").addEventListener("change", (e) => setStart(e.target.value || null));
    $("#rotSteps").addEventListener("change", (e) => setStepKeys(e.target.checked));
    $("#rotVerbose").addEventListener("change", (e) => setVerbose(e.target.checked));
    wireDrop();
    wireDialog();
}

export async function loadLibrary({ highlight } = {}) {
    if (highlight) state.highlight = highlight.toLowerCase();
    try {
        state.data = await api.library();
    } catch (e) {
        toast(`Couldn't load your sprays: ${e.message}`, { kind: "error" });
        return;
    }
    render();
}

// ------------------------------------------------------------------ rendering
function visibleSprays() {
    const query = $("#libSearch").value.trim().toLowerCase();
    const sprays = state.data.sprays.filter((s) => !query || s.name.toLowerCase().includes(query));
    const sorters = {
        newest: (a, b) => b.modified - a.modified,
        name: (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
        size: (a, b) => b.size_bytes - a.size_bytes,
        frames: (a, b) => b.frames - a.frames,
    };
    return sprays.sort(sorters[$("#libSort").value]);
}

function render() {
    const data = state.data;
    if (!data) return;
    const grid = $("#libGrid");
    const empty = $("#libEmpty");
    renderRotation();

    if (!data.tf2_found) {
        grid.replaceChildren();
        $("#libStats").textContent = "";
        empty.textContent = "Team Fortress 2 wasn't found. Install it through Steam, or set TF2SPRAY_TF2_DIR to its folder.";
        show(empty);
        return;
    }

    const all = data.sprays;
    const animated = all.filter((s) => s.frames > 1).length;
    const total = all.reduce((sum, s) => sum + s.size_bytes, 0);
    $("#libStats").textContent = `${all.length} spray${all.length === 1 ? "" : "s"} · ${animated} animated · ${formatSize(total)}`;

    const sprays = visibleSprays();
    grid.classList.toggle("rot-on", data.rotation.installed);
    grid.replaceChildren(...sprays.map(card));
    if (!all.length) {
        empty.textContent = "No sprays yet. Import a .vtf, or create one from an image or video.";
        show(empty);
    } else if (!sprays.length) {
        empty.textContent = "No sprays match your search.";
        show(empty);
    } else {
        hide(empty);
    }

    if (state.highlight && isVisible()) {
        const match = [...grid.children].find((node) => node.dataset.file === state.highlight);
        state.highlight = null;
        if (match) {
            match.scrollIntoView({ behavior: "smooth", block: "center" });
            match.classList.add("flash");
        }
    }
}

function badges(spray) {
    return [
        spray.is_current && el("span", { class: "badge current", title: "TF2's last saved spray (cl_logofile)" }, "Current"),
        isStart(spray) && el("span", { class: "badge start", title: "Every TF2 launch starts with this spray" }, "🏁 Start"),
        spray.frames > 1 && el("span", { class: "badge anim" }, `▶ ${spray.frames} frames`),
        spray.over_limit && el("span", { class: "badge bad", title: "TF2 ignores sprays of 512 KB or more" }, "Over 512 KB"),
        spray.missing_bytes > 0 && el("span", { class: "badge bad", title: "The file is cut off, so TF2 most likely can't load it" }, "Damaged"),
        !spray.valid && el("span", { class: "badge bad" }, "Unreadable"),
    ];
}

function metaLine(spray) {
    if (!spray.valid) return formatSize(spray.size_bytes);
    return `${spray.width}×${spray.height} · ${spray.format} · ${formatSize(spray.size_bytes)}`;
}

function rotationTitle(spray) {
    if (!spray.rotation_ok) return "Can't join the random rotation (name has spaces/symbols, or the file is damaged, invalid or too big)";
    return spray.rotation_included
        ? "In the random rotation — click to leave it out"
        : "Left out of the random rotation — click to include";
}

function rotationButton(spray) {
    const on = spray.rotation_ok && spray.rotation_included;
    return el(
        "button",
        {
            class: `icon-btn rot-toggle${on ? " on" : ""}`,
            title: rotationTitle(spray),
            "aria-pressed": String(on),
            disabled: !spray.rotation_ok,
            onclick: (e) => {
                stop(e);
                toggleIncluded(spray);
            },
        },
        "🎲"
    );
}

function card(spray) {
    return el(
        "article",
        {
            class: `spray-card${spray.valid ? "" : " invalid"}`,
            dataset: { file: spray.filename.toLowerCase() },
            tabindex: 0,
            title: spray.filename,
            onclick: () => openDialog(spray),
            onkeydown: (e) => e.key === "Enter" && openDialog(spray),
        },
        el(
            "div",
            { class: "thumb checker" },
            spray.valid
                ? el("img", { src: api.previewUrl(spray, "thumb"), alt: spray.name, loading: "lazy", decoding: "async" })
                : "⚠ Can't read this file",
            el("div", { class: "card-badges" }, badges(spray))
        ),
        el("div", { class: "card-body" }, el("div", { class: "card-name" }, spray.name), el("div", { class: "card-meta" }, metaLine(spray))),
        el(
            "div",
            { class: "card-actions" },
            rotationButton(spray),
            el("a", { class: "icon-btn", href: api.downloadUrl(spray.filename), download: spray.filename, title: "Download .vtf", onclick: stop }, "⬇"),
            el("button", { class: "icon-btn danger", title: "Delete", onclick: (e) => { stop(e); remove(spray); } }, "🗑")
        )
    );
}

// ------------------------------------------------------------------ rotation
function renderRotation() {
    const data = state.data;
    $("#rotationBar").classList.toggle("hidden", !data.tf2_found);
    const { installed, count, start } = data.rotation;
    $("#rotEnabled").checked = installed;
    $("#rotShuffle").disabled = !installed;
    $("#rotStartWrap").classList.toggle("hidden", !installed);
    $("#rotStepsWrap").classList.toggle("hidden", !installed);
    $("#rotSteps").checked = Boolean(data.rotation.step_keys);
    $("#rotVerboseWrap").classList.toggle("hidden", !installed);
    $("#rotVerbose").checked = Boolean(data.rotation.verbose);
    if (installed) renderStartChoices(start);
    const flow = start
        ? `Every launch starts with ${stem(start)}; after that, every class pick (and spray key) moves to a new one, used from the next map.`
        : "Every class pick (and spray key) moves to a new spray, used from the next map.";
    $("#rotInfo").textContent = installed
        ? `On · ${count} spray${count === 1 ? "" : "s"} in the rotation. ${flow} Use 🎲 on a spray to include or leave it out.`
        : "Off · TF2 keeps using the spray picked in its options.";
}

function renderStartChoices(start) {
    const choices = state.data.sprays
        .filter((s) => s.rotation_ok)
        .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
    const select = $("#rotStart");
    select.replaceChildren(
        el("option", { value: "" }, "Shuffle order (no fixed start)"),
        ...choices.map((s) => el("option", { value: s.filename }, s.name))
    );
    select.value = start ?? "";
}

async function setVerbose(enabled) {
    try {
        state.data.rotation = await api.setVerbose(enabled);
        render();
        toast(
            enabled
                ? "From your next TF2 launch, every step shows in the console (~). Tip: con_filter_enable 1; con_filter_text EasyImport shows only these lines."
                : "Step logging is off from your next TF2 launch.",
            { kind: "success", timeout: enabled ? 12000 : 5000 }
        );
    } catch (e) {
        $("#rotVerbose").checked = !enabled;
        toast(e.message, { kind: "error" });
    }
}

async function setStepKeys(enabled) {
    try {
        state.data.rotation = await api.setStepKeys(enabled);
        render();
        toast(
            enabled
                ? "Jumps and weapon switches now move the rotation on too — takes effect next TF2 launch."
                : "Only spraying and picking a class move the rotation on now.",
            { kind: "success" }
        );
    } catch (e) {
        $("#rotSteps").checked = !enabled;
        toast(e.message, { kind: "error" });
    }
}

async function setStart(filename) {
    try {
        state.data.rotation = await api.setStartSpray(filename);
        render();
        if (state.dialogSpray) fillDialog(state.dialogSpray);
        toast(
            filename ? `Every TF2 launch will start with ${stem(filename)}.` : "Starting spray cleared — launches follow the shuffle order.",
            { kind: "success" }
        );
    } catch (e) {
        renderRotation();
        toast(e.message, { kind: "error" });
    }
}

async function setRotation(enabled) {
    try {
        state.data.rotation = await api.setRotation(enabled);
        render();
        toast(enabled ? "Random spray rotation is on — it starts next time you launch TF2." : "Random spray rotation is off.", { kind: "success" });
    } catch (e) {
        $("#rotEnabled").checked = !enabled;
        toast(e.message, { kind: "error" });
    }
}

async function shuffle() {
    try {
        await api.shuffleRotation();
        toast("Rotation reshuffled — the new order applies next TF2 launch.", { kind: "success" });
    } catch (e) {
        toast(e.message, { kind: "error" });
    }
}

async function toggleIncluded(spray) {
    try {
        const res = await api.setIncluded(spray.filename, !spray.rotation_included);
        spray.rotation_included = res.included;
        state.data.rotation = res.rotation;
        render();
        if (state.dialogSpray === spray) fillDialog(spray);
    } catch (e) {
        toast(e.message, { kind: "error" });
    }
}

// ------------------------------------------------------------------ import / delete
async function importFiles(files) {
    const vtfs = files.filter((f) => f.name.toLowerCase().endsWith(".vtf"));
    const media = files.filter((f) => !f.name.toLowerCase().endsWith(".vtf"));
    if (media.length) state.onMediaDropped(media[0]);
    if (!vtfs.length) return;
    try {
        const res = await api.importVtfs(vtfs);
        await loadLibrary({ highlight: res.imported[0] });
        if (res.imported.length) {
            toast(`Imported ${res.imported.length} spray${res.imported.length === 1 ? "" : "s"}.`, { kind: "success" });
        }
        res.errors.forEach((message) => toast(message, { kind: "error", timeout: 9000 }));
    } catch (e) {
        toast(`Import failed: ${e.message}`, { kind: "error" });
    }
}

async function remove(spray) {
    const current = spray.is_current ? " It's your current spray, so TF2 will show none until you pick another." : "";
    if (!(await confirmDialog(`Delete "${spray.name}"?${current} You can undo this right after.`, "Delete"))) return;
    try {
        const res = await api.deleteSpray(spray.filename);
        if ($("#sprayDialog").open) $("#sprayDialog").close();
        await loadLibrary();
        toast(`Deleted ${spray.name}.`, { action: "Undo", onAction: () => restore(res.trash_id), timeout: 12000 });
    } catch (e) {
        toast(`Couldn't delete: ${e.message}`, { kind: "error" });
    }
}

async function restore(trashId) {
    try {
        const res = await api.restoreSpray(trashId);
        await loadLibrary({ highlight: res.filename });
        toast(`Restored ${res.filename}.`, { kind: "success" });
    } catch (e) {
        toast(`Couldn't restore: ${e.message}`, { kind: "error" });
    }
}

function wireDrop() {
    const view = $("#view-library");
    const zone = $("#libDrop");
    let depth = 0;
    view.addEventListener("dragenter", (e) => {
        e.preventDefault();
        depth += 1;
        zone.classList.add("dragging");
    });
    view.addEventListener("dragover", (e) => e.preventDefault());
    view.addEventListener("dragleave", () => {
        depth -= 1;
        if (depth <= 0) zone.classList.remove("dragging");
    });
    view.addEventListener("drop", (e) => {
        e.preventDefault();
        depth = 0;
        zone.classList.remove("dragging");
        importFiles([...e.dataTransfer.files]);
    });
}

// ------------------------------------------------------------------ details dialog
function wireDialog() {
    const dialog = $("#sprayDialog");
    dialog.addEventListener("click", (e) => {
        if (e.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", () => {
        state.dialogSpray = null;
        $("#dlgPreview").removeAttribute("src");
    });
    $("#dlgRotation").addEventListener("click", () => state.dialogSpray && toggleIncluded(state.dialogSpray));
    $("#dlgStart").addEventListener(
        "click",
        () => state.dialogSpray && setStart(isStart(state.dialogSpray) ? null : state.dialogSpray.filename)
    );
    $("#dlgDelete").addEventListener("click", () => state.dialogSpray && remove(state.dialogSpray));
}

function openDialog(spray) {
    state.dialogSpray = spray;
    if (spray.valid) $("#dlgPreview").src = api.previewUrl(spray, "full");
    fillDialog(spray);
    $("#sprayDialog").showModal();
}

function fillDialog(spray) {
    $("#dlgName").textContent = spray.name;
    $("#dlgBadges").replaceChildren(...badges(spray).filter(Boolean));
    const square = spray.width === spray.height ? "" : " (stretched to a square in-game)";
    const rows = [
        ["File", spray.filename],
        ["Resolution", spray.valid ? `${spray.width}×${spray.height}${square}` : "—"],
        ["Frames", spray.frames > 1 ? `${spray.frames} · ${(spray.frames / TF2_FPS).toFixed(1)}s loop in-game` : spray.valid ? "1 (static)" : "—"],
        ["Format", spray.valid ? `${spray.format}${spray.mipmaps > 1 ? ` · ${spray.mipmaps} mipmaps` : ""}` : "—"],
        ["Size", `${formatSize(spray.size_bytes)} · ${Math.round((spray.size_bytes / (512 * 1024)) * 100)}% of TF2's 512 KB limit`],
        ["Modified", new Date(spray.modified * 1000).toLocaleString()],
    ];
    if (spray.missing_bytes > 0) {
        rows.push([
            "Damaged",
            `The file is cut off (${formatSize(spray.missing_bytes)} of image data missing), so TF2 most likely can't load it. The preview shows only the frames that survived — re-create it from the original, or delete it.`,
        ]);
    }
    $("#dlgDetails").replaceChildren(...rows.flatMap(([term, value]) => [el("dt", {}, term), el("dd", {}, value)]));

    const rotation = $("#dlgRotation");
    rotation.classList.toggle("hidden", !state.data.rotation.installed);
    rotation.disabled = !spray.rotation_ok;
    rotation.title = rotationTitle(spray);
    rotation.textContent = spray.rotation_ok && spray.rotation_included ? "🎲 In rotation — leave out" : "🎲 Add to rotation";
    const startButton = $("#dlgStart");
    startButton.classList.toggle("hidden", !state.data.rotation.installed);
    startButton.disabled = !spray.rotation_ok;
    startButton.textContent = isStart(spray) ? "🏁 Starting spray — clear" : "🏁 Start every launch with this";
    $("#dlgDownload").href = api.downloadUrl(spray.filename);
    $("#dlgDownload").setAttribute("download", spray.filename);
}
