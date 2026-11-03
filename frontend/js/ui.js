// Small DOM helpers shared by the views: element builder, toasts, confirm dialog.

export const $ = (selector, root = document) => root.querySelector(selector);
export const show = (node) => node.classList.remove("hidden");
export const hide = (node) => node.classList.add("hidden");

// Builds elements without innerHTML so file names can never inject markup.
export function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
        if (value === false || value == null) continue;
        if (key === "class") node.className = value;
        else if (key === "dataset") Object.assign(node.dataset, value);
        else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
        else node.setAttribute(key, value === true ? "" : String(value));
    }
    node.append(...children.flat().filter((child) => child != null && child !== false));
    return node;
}

export function toast(message, { kind = "info", action, onAction, timeout = 5000 } = {}) {
    const box = el("div", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" }, el("span", {}, message));
    const dismiss = () => {
        clearTimeout(timer);
        box.remove();
    };
    if (action) {
        box.append(el("button", { class: "btn small", onclick: () => { dismiss(); onAction(); } }, action));
    }
    $("#toasts").append(box);
    const timer = setTimeout(dismiss, timeout);
}

export function confirmDialog(message, okLabel = "OK") {
    const dialog = $("#confirmDialog");
    $("#confirmText").textContent = message;
    $("#confirmOk").textContent = okLabel;
    dialog.returnValue = "";
    dialog.showModal();
    return new Promise((resolve) =>
        dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true })
    );
}

export function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KiB`;
}
