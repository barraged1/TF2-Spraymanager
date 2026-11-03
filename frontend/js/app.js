// Entry point: tab routing between "My Sprays" and "Create Spray", plus the TF2 status chip.
import { api } from "./api.js";
import { $ } from "./ui.js";
import { initLibrary, loadLibrary } from "./library.js";
import { initEditor, importIntoEditor } from "./editor.js";

function route() {
    const view = location.hash === "#create" ? "create" : "library";
    document.querySelectorAll(".view").forEach((section) => section.classList.toggle("hidden", section.id !== `view-${view}`));
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.view === view));
    if (view === "library") loadLibrary();
}

async function refreshTf2Status() {
    const chip = $("#tf2Status");
    const label = chip.querySelector(".label");
    try {
        const status = await api.tf2Status();
        chip.classList.toggle("found", status.found);
        chip.classList.toggle("missing", !status.found);
        label.textContent = status.found ? "TF2 detected" : "TF2 not found";
        chip.title = status.logos_dir || "Install TF2 through Steam, or set TF2SPRAY_TF2_DIR";
    } catch {
        label.textContent = "TF2 status unknown";
    }
}

initLibrary({
    onMediaDropped: (file) => {
        location.hash = "#create";
        importIntoEditor(file);
    },
});
initEditor({ onSaved: (filename) => loadLibrary({ highlight: filename }) });
refreshTf2Status();
window.addEventListener("hashchange", route);
route();
