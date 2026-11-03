// Video timeline: filmstrip track, loop markers, draggable start/end handles, frame stepping.

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

export class Timeline {
    constructor(root, video, { onChange = () => {} } = {}) {
        this.root = root;
        this.video = video;
        this.onChange = onChange;
        this.fps = 30;
        this.duration = 0;
        this.inT = 0;
        this.outT = 0;
        this.markerData = { candidates: [], onPick: null };

        this.track = root.querySelector("#track");
        this.selection = root.querySelector("#selection");
        this.handleIn = root.querySelector("#handleIn");
        this.handleOut = root.querySelector("#handleOut");
        this.playhead = root.querySelector("#playhead");
        this.markers = root.querySelector("#markers");
        this.playBtn = root.querySelector("#playBtn");
        this.timeReadout = root.querySelector("#timeReadout");
        this.selReadout = root.querySelector("#selReadout");
        this.inTime = root.querySelector("#inTime");
        this.outTime = root.querySelector("#outTime");
        this._bind();
    }

    load(src, { fps, filmstrip }) {
        this.fps = fps > 0 ? fps : 30;
        this.duration = 0;
        this.setMarkers([], null);
        this.track.style.backgroundImage = filmstrip ? `url("${filmstrip}")` : "none";
        this.video.src = src;
    }

    unload() {
        this.video.pause();
        this.video.removeAttribute("src");
        this.video.load();
        this.duration = 0;
        this.setMarkers([], null);
    }

    get frame() {
        return 1 / this.fps;
    }

    _bind() {
        const video = this.video;
        video.addEventListener("loadedmetadata", () => this._reset(video.duration));
        video.addEventListener("seeked", () => this._renderPlayhead());
        video.addEventListener("play", () => {
            this.playBtn.textContent = "⏸ Pause";
            requestAnimationFrame(this._tick);
        });
        video.addEventListener("pause", () => {
            this.playBtn.textContent = "▶ Play selection";
            this._renderPlayhead();
        });

        this.playBtn.addEventListener("click", () => this.togglePlay());
        this.root.querySelector("#stepBack").addEventListener("click", () => this.step(-1));
        this.root.querySelector("#stepFwd").addEventListener("click", () => this.step(1));
        this.root.querySelector("#setIn").addEventListener("click", () => this.setIn(video.currentTime));
        this.root.querySelector("#setOut").addEventListener("click", () => this.setOut(video.currentTime));
        this.root.querySelectorAll("[data-nudge]").forEach((btn) =>
            btn.addEventListener("click", () => this.nudge(btn.dataset.nudge, Number(btn.dataset.dir)))
        );
        this.inTime.addEventListener("change", () => this._typed(this.inTime, (t) => this.setIn(t)));
        this.outTime.addEventListener("change", () => this._typed(this.outTime, (t) => this.setOut(t)));

        this.track.addEventListener("pointerdown", (e) => this._scrub(e));
        this._dragHandle(this.handleIn, (t) => this.setIn(t));
        this._dragHandle(this.handleOut, (t) => this.setOut(t));
    }

    // Runs every animation frame while playing, so the selection loops precisely.
    _tick = () => {
        if (this.video.paused) return;
        if (this.video.currentTime >= this.outT || this.video.currentTime < this.inT) {
            this.video.currentTime = this.inT;
        }
        this._renderPlayhead();
        requestAnimationFrame(this._tick);
    };

    _reset(duration) {
        this.duration = Number.isFinite(duration) ? duration : 0;
        this.inT = 0;
        this.outT = this.duration;
        this._renderMarkers();
        this._changed();
        this._renderPlayhead();
    }

    _typed(input, apply) {
        const value = parseFloat(input.value);
        if (Number.isFinite(value)) apply(value);
        else this._renderRange();
    }

    _pxToTime(clientX) {
        const rect = this.track.getBoundingClientRect();
        return clamp((clientX - rect.left) / rect.width, 0, 1) * this.duration;
    }

    _scrub(e) {
        if (!this.duration || e.target.closest(".handle")) return;
        this.video.pause();
        this.track.setPointerCapture(e.pointerId);
        const seekTo = (ev) => this.seek(this._pxToTime(ev.clientX));
        const up = () => {
            this.track.removeEventListener("pointermove", seekTo);
            this.track.removeEventListener("pointerup", up);
        };
        seekTo(e);
        this.track.addEventListener("pointermove", seekTo);
        this.track.addEventListener("pointerup", up);
    }

    _dragHandle(handle, apply) {
        handle.addEventListener("pointerdown", (e) => {
            e.preventDefault();
            e.stopPropagation();
            handle.setPointerCapture(e.pointerId);
            const move = (ev) => apply(this._pxToTime(ev.clientX));
            const up = () => {
                handle.removeEventListener("pointermove", move);
                handle.removeEventListener("pointerup", up);
            };
            handle.addEventListener("pointermove", move);
            handle.addEventListener("pointerup", up);
        });
    }

    togglePlay() {
        if (!this.duration) return;
        if (this.video.paused) {
            if (this.video.currentTime < this.inT || this.video.currentTime >= this.outT - 0.01) {
                this.video.currentTime = this.inT;
            }
            this.video.play();
        } else {
            this.video.pause();
        }
    }

    seek(t) {
        this.video.currentTime = clamp(t, 0, this.duration);
        this._renderPlayhead();
    }

    step(dir) {
        this.video.pause();
        this.seek(this.video.currentTime + dir * this.frame);
    }

    setIn(t) {
        if (!this.duration) return;
        this.inT = clamp(t, 0, this.outT - this.frame);
        this._changed();
    }

    setOut(t) {
        if (!this.duration) return;
        this.outT = clamp(t, this.inT + this.frame, this.duration);
        this._changed();
    }

    setRange(start, end) {
        if (!this.duration) return;
        this.inT = clamp(start, 0, Math.max(0, this.duration - this.frame));
        this.outT = clamp(end, this.inT + this.frame, this.duration);
        this._changed();
    }

    nudge(which, dir) {
        this.video.pause();
        if (which === "in") {
            this.setIn(this.inT + dir * this.frame);
            this.seek(this.inT);
        } else {
            this.setOut(this.outT + dir * this.frame);
            this.seek(Math.max(this.inT, this.outT - this.frame));
        }
    }

    setMarkers(candidates, onPick) {
        this.markerData = { candidates, onPick };
        this._renderMarkers();
    }

    _renderMarkers() {
        const { candidates, onPick } = this.markerData;
        if (!this.duration) {
            this.markers.replaceChildren();
            return;
        }
        // Drawn worst-first so the best candidate sits on top.
        const items = [...candidates].reverse().map((c) => {
            const marker = document.createElement("button");
            marker.type = "button";
            marker.className = "loop-marker" + (c === candidates[0] ? " best" : "");
            marker.style.left = `${(c.start_time / this.duration) * 100}%`;
            marker.style.width = `${((c.end_time - c.start_time) / this.duration) * 100}%`;
            marker.title = `${Math.round(c.similarity * 100)}% seamless loop (${c.duration.toFixed(2)}s) — click to use`;
            marker.addEventListener("click", () => onPick && onPick(c));
            return marker;
        });
        this.markers.replaceChildren(...items);
    }

    _changed() {
        this._renderRange();
        this.onChange(this.getSelection());
    }

    _renderRange() {
        if (!this.duration) return;
        const inPct = (this.inT / this.duration) * 100;
        const outPct = (this.outT / this.duration) * 100;
        this.handleIn.style.left = `${inPct}%`;
        this.handleOut.style.left = `${outPct}%`;
        this.selection.style.left = `${inPct}%`;
        this.selection.style.width = `${outPct - inPct}%`;
        this.inTime.value = this.inT.toFixed(2);
        this.outTime.value = this.outT.toFixed(2);
        this.selReadout.textContent = `${(this.outT - this.inT).toFixed(2)}s selected`;
    }

    _renderPlayhead() {
        if (!this.duration) return;
        this.playhead.style.left = `${(this.video.currentTime / this.duration) * 100}%`;
        this.timeReadout.textContent = `${this.video.currentTime.toFixed(2)} / ${this.duration.toFixed(2)}s`;
    }

    getSelection() {
        return { start: this.inT, end: this.outT, duration: this.outT - this.inT };
    }
}
