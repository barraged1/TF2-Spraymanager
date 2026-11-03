// Thin wrapper around the backend API.

async function asJson(resp) {
    let data = null;
    try {
        data = await resp.json();
    } catch {
        /* empty body */
    }
    if (!resp.ok) {
        const error = new Error((data && (data.detail || data.error)) || resp.statusText);
        error.status = resp.status;
        throw error;
    }
    return data;
}

const send = (method, url, body) =>
    fetch(url, {
        method,
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
    }).then(asJson);

const upload = (url, field, files) => {
    const form = new FormData();
    for (const file of files) form.append(field, file);
    return fetch(url, { method: "POST", body: form }).then(asJson);
};

const enc = encodeURIComponent;

export const api = {
    config: () => send("GET", "/api/config"),
    tf2Status: () => send("GET", "/api/tf2/status"),

    // --- Create Spray ---
    uploadFile: (file) => upload("/api/import/upload", "file", [file]),
    importUrl: (url) => send("POST", "/api/import/url", { url }),
    loops: (jobId, params) => send("POST", `/api/job/${jobId}/loops`, params),
    estimate: (jobId, opts) => send("POST", `/api/job/${jobId}/estimate`, opts),
    convert: (jobId, opts) => send("POST", `/api/job/${jobId}/convert`, opts),
    uploadFade: (jobId, file) => upload(`/api/job/${jobId}/fade-image`, "file", [file]),
    saveToTf2: (jobId, name, overwrite = false) => send("POST", `/api/job/${jobId}/save-to-tf2`, { name, overwrite }),
    fileUrl: (jobId, name) => `/api/job/${jobId}/file/${name}`,
    frameUrl: (jobId, t, longEdge) => `/api/job/${jobId}/frame?t=${Math.max(0, t).toFixed(3)}&long_edge=${longEdge}`,
    filmstripUrl: (jobId) => `/api/job/${jobId}/filmstrip`,

    // --- My Sprays ---
    library: () => send("GET", "/api/library"),
    previewUrl: (spray, size) => `/api/library/sprays/${enc(spray.filename)}/preview?size=${size}&v=${spray.modified}`,
    downloadUrl: (filename) => `/api/library/sprays/${enc(filename)}/download`,
    deleteSpray: (filename) => send("DELETE", `/api/library/sprays/${enc(filename)}`),
    restoreSpray: (trashId) => send("POST", `/api/library/trash/${enc(trashId)}/restore`),
    importVtfs: (files) => upload("/api/library/import", "files", files),
    setIncluded: (filename, included) => send("PUT", `/api/library/sprays/${enc(filename)}/rotation`, { included }),
    setRotation: (enabled) => send("PUT", "/api/library/rotation", { enabled }),
    shuffleRotation: () => send("POST", "/api/library/rotation/shuffle"),
    setStartSpray: (filename) => send("PUT", "/api/library/rotation/start", { filename }),
    setStepKeys: (enabled) => send("PUT", "/api/library/rotation/step-keys", { enabled }),
    setVerbose: (enabled) => send("PUT", "/api/library/rotation/verbose", { enabled }),
};
