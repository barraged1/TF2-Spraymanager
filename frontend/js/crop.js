// Interactive crop overlay for an image or video preview.
// Reports the selection as a normalized rectangle {x, y, w, h} in 0..1 of the
// source, so it is independent of the displayed (scaled) size.

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const MIN = 0.04; // minimum crop edge (fraction)

export class Cropper {
    constructor({ onChange = () => {} } = {}) {
        this.onChange = onChange;
        this.enabled = false;
        this.lock = false;
        this.rect = { x: 0, y: 0, w: 1, h: 1 };
        this.media = null;
        this.overlay = this._buildDom();
        this._observer = new ResizeObserver(() => this._reposition());
        window.addEventListener("resize", () => this._reposition());
    }

    _buildDom() {
        const overlay = document.createElement("div");
        overlay.className = "crop-overlay hidden";
        const box = document.createElement("div");
        box.className = "crop-box";
        overlay.appendChild(box);
        for (const pos of ["nw", "ne", "sw", "se"]) {
            const h = document.createElement("div");
            h.className = "crop-handle " + pos;
            h.dataset.pos = pos;
            box.appendChild(h);
        }
        this.box = box;
        this._bind(box);
        return overlay;
    }

    attachTo(wrapEl, mediaEl) {
        this.media = mediaEl;
        if (this.overlay.parentElement !== wrapEl) wrapEl.appendChild(this.overlay);
        this._observer.disconnect();
        this._observer.observe(mediaEl);
        const onReady = () => this._reposition();
        mediaEl.addEventListener("load", onReady);
        mediaEl.addEventListener("loadedmetadata", onReady);
        this._reposition();
    }

    _reposition() {
        const wrap = this.overlay.parentElement;
        if (!this.media || !wrap) return;
        const mr = this.media.getBoundingClientRect();
        const wr = wrap.getBoundingClientRect();
        if (mr.width < 2 || mr.height < 2) return;
        Object.assign(this.overlay.style, {
            left: `${mr.left - wr.left}px`,
            top: `${mr.top - wr.top}px`,
            width: `${mr.width}px`,
            height: `${mr.height}px`,
        });
        this._render();
    }

    setEnabled(on) {
        this.enabled = on;
        this.overlay.classList.toggle("hidden", !on);
        if (on && this.rect.w > 0.999 && this.rect.h > 0.999) {
            this.reset(0.7);
        } else {
            this._reposition();
        }
        this._emit();
    }

    setLock(on) {
        this.lock = on;
        if (on) {
            this._squareFromWidth("se");
            this._render();
            this._emit();
        }
    }

    reset(frac = 1) {
        const s = clamp(frac, MIN, 1);
        this.rect = { x: (1 - s) / 2, y: (1 - s) / 2, w: s, h: s };
        if (this.lock) this._squareFromWidth("se");
        this._render();
        this._emit();
    }

    getCrop() {
        if (!this.enabled) return null;
        const r = this.rect;
        if (r.x <= 0.002 && r.y <= 0.002 && r.w >= 0.998 && r.h >= 0.998) return null;
        return {
            x: +r.x.toFixed(4),
            y: +r.y.toFixed(4),
            w: +r.w.toFixed(4),
            h: +r.h.toFixed(4),
        };
    }

    sourcePixels() {
        const w = this.media?.naturalWidth || this.media?.videoWidth || 0;
        const h = this.media?.naturalHeight || this.media?.videoHeight || 0;
        return {
            w: Math.round(this.rect.w * w),
            h: Math.round(this.rect.h * h),
        };
    }

    _srcAspect() {
        const w = this.media?.naturalWidth || this.media?.videoWidth || 1;
        const h = this.media?.naturalHeight || this.media?.videoHeight || 1;
        return w / h;
    }

    _squareFromWidth(corner) {
        // Make the crop square in *source* pixels: h_norm = w_norm * (srcW/srcH).
        const a = this._srcAspect();
        let { x, y, w, h } = this.rect;
        let targetH = w * a;
        if (targetH > 1) {
            targetH = 1;
            w = targetH / a;
        }
        if (corner.includes("n")) y = y + h - targetH;
        h = targetH;
        y = clamp(y, 0, 1 - h);
        x = clamp(x, 0, 1 - w);
        this.rect = { x, y, w, h };
    }

    _emit() {
        this.onChange(this.getCrop());
    }

    _render() {
        const r = this.rect;
        Object.assign(this.box.style, {
            left: `${r.x * 100}%`,
            top: `${r.y * 100}%`,
            width: `${r.w * 100}%`,
            height: `${r.h * 100}%`,
        });
    }

    _bind(box) {
        box.addEventListener("pointerdown", (e) => {
            if (e.target.classList.contains("crop-handle")) return;
            e.preventDefault();
            this._drag(e, "move");
        });
        box.querySelectorAll(".crop-handle").forEach((h) => {
            h.addEventListener("pointerdown", (e) => {
                e.preventDefault();
                e.stopPropagation();
                this._drag(e, h.dataset.pos);
            });
        });
    }

    _drag(e, mode) {
        const overlayRect = this.overlay.getBoundingClientRect();
        const start = { mx: e.clientX, my: e.clientY, ...this.rect };
        const move = (ev) => {
            const dx = (ev.clientX - start.mx) / overlayRect.width;
            const dy = (ev.clientY - start.my) / overlayRect.height;
            this._apply(mode, start, dx, dy);
            this._render();
        };
        const up = () => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", up);
            this._emit();
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
    }

    _apply(mode, start, dx, dy) {
        if (mode === "move") {
            this.rect = {
                x: clamp(start.x + dx, 0, 1 - start.w),
                y: clamp(start.y + dy, 0, 1 - start.h),
                w: start.w,
                h: start.h,
            };
            return;
        }

        let left = start.x;
        let top = start.y;
        let right = start.x + start.w;
        let bottom = start.y + start.h;

        if (mode.includes("w")) left = clamp(start.x + dx, 0, right - MIN);
        if (mode.includes("e")) right = clamp(right + dx, left + MIN, 1);
        if (mode.includes("n")) top = clamp(start.y + dy, 0, bottom - MIN);
        if (mode.includes("s")) bottom = clamp(bottom + dy, top + MIN, 1);

        let rect = { x: left, y: top, w: right - left, h: bottom - top };

        if (this.lock) {
            const a = this._srcAspect();
            let targetH = rect.w * a;
            if (mode.includes("n")) {
                top = bottom - targetH;
                if (top < 0) {
                    top = 0;
                    targetH = bottom - top;
                    rect.w = targetH / a;
                    if (mode.includes("w")) left = right - rect.w;
                    else right = left + rect.w;
                }
            } else {
                bottom = top + targetH;
                if (bottom > 1) {
                    bottom = 1;
                    targetH = bottom - top;
                    rect.w = targetH / a;
                    if (mode.includes("w")) left = right - rect.w;
                    else right = left + rect.w;
                }
            }
            rect = { x: left, y: top, w: right - left, h: bottom - top };
        }

        this.rect = rect;
    }
}
