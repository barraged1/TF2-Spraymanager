# 🎨 TF2 Spray EasyImport

A local web app for managing your **Team Fortress 2 sprays**:

- **My Sprays** — see every spray installed in TF2 (with animated previews),
  import `.vtf` files, delete with undo, and control a **random spray each game**
  rotation.
- **Create Spray** — turn images, GIFs, and videos (uploaded or from a URL)
  into sprays sized for the best possible quality under TF2's 512 KB limit, with
  crop, frame-accurate trimming, and automatic **seamless-loop detection**.

---

## Features

### My Sprays (library)

- **Every installed spray at a glance** — previews are decoded from the real
  `.vtf` (animated sprays play at TF2's 5 fps, stretched square like in-game).
- **Search & sort** by name, newest, file size, or frame count.
- **Details** — resolution, frames and in-game loop length, format, mipmaps, and
  how much of the 512 KB limit it uses.
- **Health badges** — *Current* (TF2's selected spray), *Over 512 KB* (TF2 ignores
  it), *Damaged* (the file is cut short, so TF2 most likely can't load it; the
  preview shows the frames that survived), and *Unreadable*.
- **Import `.vtf` files** — button or drag & drop (validated, names cleaned up,
  never overwrites). Dropping a picture or video instead opens it in *Create Spray*.
- **Delete with Undo** — the spray and its `.vmt` files go to a trash folder
  (`backend/data/trash`, kept 7 days), so the *Undo* button can restore them.
- **Random spray each game** — one switch installs/removes the rotation; 🎲 on
  each spray includes it or leaves it out; *Reshuffle* re-deals the order. See
  [Random spray rotation](#random-spray-rotation).

### Create Spray (editor)

- **Drop-in conversion** — images (`png/jpg/gif/webp/bmp/tga`) and video
  (`mp4/webm/mov/mkv/avi/gif`), or paste a **URL** (YouTube/social via `yt-dlp`,
  or direct media links).
- **Best-quality auto-sizing** — picks `DXT1` (opaque) or `DXT5` (transparency) at the
  largest resolution that fits under **512 KB** (up to **1020×1020**).
- **Live size preview** — resolution, format, and file size update as you tweak
  options, *before* you convert.
- **Animated sprays** — resamples to TF2's ~5 FPS and fits as many frames as the
  budget allows.
- **Automatic loop detection** — runs as soon as a video loads; the most seamless
  loops are listed *and* marked under the timeline. One click trims to a loop.
- **Filmstrip timeline** — thumbnails of the clip with draggable in/out handles,
  typed times, **±1 frame nudges**, and *Play selection* (loops inside the trim).
- **Seam preview** — shows the last frame next to the first frame so you can
  see whether the spray will loop smoothly.
- **Boomerang loop** — plays the clip forward then backward, which always loops
  seamlessly.
- **Interactive crop** — drag a crop box right on the image or video preview
  (with an optional **1:1 lock** for a perfect square).
- **Square-fit controls** — letterbox, **transparent padding** (keeps the source
  aspect ratio with see-through bars, via DXT5), crop, or stretch.
- **Background removal** — chroma-key a solid background into transparency.
- **Fading sprays** — a different "far" image revealed at distance via mipmaps.
- **True preview** — the result is decoded back from the finished `.vtf` at 5 fps,
  so you see exactly what players will see.
- **Save to My Sprays** — writes the spray (plus its `.vmt` and TF2's picker
  thumbnail `.vmt`) into `…\tf\materials\vgui\logos`, asks before replacing an
  existing spray, and adds it to the rotation if that's on.

---

## Requirements

- **Python 3.12+** (a virtual environment is created during setup).
- Windows is fully supported (TF2 detection + save). FFmpeg is bundled via
  `imageio-ffmpeg`; no separate install needed.

## Setup

```powershell
# from the project root
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

Double-click **`start.bat`** (it creates the environment and installs
dependencies on first run), or run manually:

```powershell
.\.venv\Scripts\python.exe run.py
```

This starts the server on <http://127.0.0.1:8790/> (localhost only) and opens
your browser. Set `TF2SPRAY_NO_BROWSER=1` to skip auto-opening. If another app
already uses port 8790, set `TF2SPRAY_PORT` to a free port.

---

## How to use

### My Sprays

- Click a spray for details, download, delete, or rotation options.
- **⬆ Import .vtf** (or drag `.vtf` files onto the page) to add sprays you
  already have.
- **🗑** deletes; click **Undo** in the notification to bring it back.
- Flip **Random spray each game** on, then use **🎲** to choose which sprays take
  part.

### Create Spray

1. **Choose media** — drop a file, choose one, or paste a link.
2. **Crop, trim & loop** — for video, pick a detected loop (**Use**) or drag the
   in/out handles and fine-tune with **− / +** (one frame). Check the seam
   preview, or tick **Boomerang** in step 3. Tick **Crop** to frame the shot.
3. **Spray options** — name, fit mode, format, fps, boomerang, mipmaps, chroma
   key, fading. The estimate updates live (including the in-game loop length).
4. **Preview & save** — check the true preview, then **Save to My Sprays** (or
   download the `.vtf` + `.vmt`).

### In-game

1. Saved sprays are already in `…\Team Fortress 2\tf\materials\vgui\logos`.
2. TF2 → **Options → Multiplayer** → pick the spray (or turn on the random
   rotation and let it choose).
3. Enable sprays in **Advanced Options** (or `cl_spraydisable 0`).
4. Spray with **T** on a community server (sprays are hidden in Casual).

---

## Random spray rotation

TF2 has no built-in "random spray", so the rotation is done with TF2 config
scripts that the app writes for you (no launcher or `.bat` needed — start TF2
from Steam as usual):

- `tf/cfg/easyimport_sprays.cfg` holds a freshly shuffled order of your sprays.
  Every step through it (picking a class, pressing the spray key, and
  optionally jumping or switching weapons) sets `cl_logofile` to the spray it
  lands on right away. TF2 sends your spray whenever a map loads (a map change
  or joining a server), so the next map gets wherever all your key presses
  during the last one left off, which is hard to predict.
- It's hooked in from `autoexec.cfg` and the class configs — or, if
  [mastercomfig](https://mastercomfig.com) is installed, from its
  `cfg/overrides/autoexec.cfg` and `cfg/overrides/game_overrides.cfg` hooks.
  Every added line is tagged `// tf2-spray-easyimport`.
- Sprays you leave out are listed in `tf/cfg/easyimport_sprays_exclude.txt`.
- **Start every launch with** (next to the switch, or 🏁 in a spray's details)
  picks the spray TF2 uses for the first game after each launch. TF2 configs
  can't remember where the rotation stopped, so otherwise every launch begins
  at the top of the same shuffle. The choice is saved in
  `tf/cfg/easyimport_sprays_start.txt`.
- **Also move it on with every jump and weapon switch** (checkbox under the
  switch) makes the *next* spray feel random even if you rarely spray. Keys
  bound to jump, `slot1`–`slot10`, `lastinv` (Q), and the mouse wheel
  (`invnext`/`invprev`) keep their normal action and also step the shuffle.
  For example, `bind "SPACE" "+jump; easyspray_cycle"`. These binds are set
  by the rotation file every time TF2 starts, the same way as the spray key,
  because with Steam Cloud on TF2 loads `config.cfg` from
  `Steam\userdata\<id>\440\remote\cfg` and ignores edits to the copy in the
  game folder. The app reads your current binds from whichever copy is newest,
  so key changes you make in TF2's options are followed the next time the
  rotation is rewritten. If the rotation is ever removed, those keys still
  work; TF2 just prints "Unknown command" in the console. Movement and
  shooting are left alone.
- **Log every step in TF2's console** (checkbox) prints a line for every step
  and every spray change, e.g. `[EasyImport] step=12/72 next-map-spray=P_Foo`.
  Open the console with `~`; it has to be enabled under Options → Advanced.
  Type `con_filter_enable 1; con_filter_text EasyImport` to see only these
  lines. Without this option the console still shows when the rotation loads
  and, on every class pick, which spray the next map will get. The app's own window also
  logs each time it rewrites the rotation or your key binds.
- Importing, saving, or deleting sprays keeps the rotation up to date.
- Turning it off removes the hooks and the rotation file, and strips the
  stepping from your key binds in every `config.cfg` copy. That one step needs
  TF2 to be closed, because TF2 rewrites `config.cfg` when it quits. All other
  options take effect from your next TF2 launch and can be changed any time.

Notes: TF2 sends your spray when a map loads, so a new spray shows up from the
**next map** (a map change on the same server counts), not mid-round. Only sprays with
simple names (letters, numbers, `_ . -`) that are under 512 KB and not damaged
can join. `install_random_sprays.bat` / `uninstall_random_sprays.bat` do the same
as the switch, for use without the web app.

---

## How TF2 sprays work (the short version)

- A spray is a `.vtf` texture (Valve Texture Format). It must be **< 512 KB**.
- Max quality is at **non-power-of-two** sizes: **1020×1020** (DXT1, opaque) or
  **724×724** (DXT5, with transparency). Non-square images are stretched to 1:1.
- Animated sprays play at a fixed engine framerate (~**5 FPS**); higher frame
  counts force lower resolution to stay under the size limit.

This tool writes a VTF **7.1** container (the format TF2 happily imports) and uses
the MIT-licensed libsquish DXT compressor bundled in
[`srctools`](https://github.com/TeamSpen210/srctools). The header layout, on-disk
mip/frame ordering, texture flags, and low-res thumbnail were cross-checked
against the [Source SDK 2013](https://github.com/ValveSoftware/source-sdk-2013)
(`VTFFileHeaderV7_1_t`), and the output is validated in the test suite by reading
it back with `srctools`.

---

## Configuration

Environment variables (all optional):

| Variable | Default | Purpose |
| --- | --- | --- |
| `TF2SPRAY_HOST` | `127.0.0.1` | Bind address (keep local). |
| `TF2SPRAY_PORT` | `8790` | Port. |
| `TF2SPRAY_URL_IMPORT` | `1` | Set `0` to disable URL importing. |
| `TF2SPRAY_MAX_UPLOAD_BYTES` | `268435456` | Max upload size (256 MiB). |
| `TF2SPRAY_MAX_DOWNLOAD_BYTES` | `536870912` | Max URL download size (512 MiB). |
| `TF2SPRAY_DATA_DIR` | `backend/data` | Working files, preview cache, and trash. |
| `TF2SPRAY_TF2_DIR` | auto-detect | Use this `Team Fortress 2` folder instead of the Steam one. |
| `TF2SPRAY_COOKIES_FROM_BROWSER` | unset | Let URL import use your logins from this browser, e.g. `firefox` or `firefox:Profile Name`. |
| `TF2SPRAY_COOKIES_FILE` | `backend/data/cookies.txt` if present | Exported `cookies.txt` for URL import (used instead of the browser). |
| `TF2SPRAY_NO_BROWSER` | unset | Set to skip auto-opening the browser. |

### Links that need a login (X/Twitter and others)

X only shows age-restricted videos to logged-in accounts, so URL import fails on
those posts ("Video #1 is unavailable" / "No video could be found"). To let the
app use your X login:

1. While logged into X in your browser, export your **x.com** cookies to a
   `cookies.txt` (Netscape format) with a cookie-export extension such as
   *Get cookies.txt LOCALLY*.
2. Save it as **`backend\data\cookies.txt`**. The app picks it up automatically
   on the next import; no restart needed. Re-export it if X logs you out.

The file contains your X login, so keep it private. `backend\data` is excluded
from git. The cookies are only used by the local downloader, on the sites they
belong to. Firefox users can instead run `setx TF2SPRAY_COOKIES_FROM_BROWSER firefox`
and restart the app. Chrome and Edge don't allow this on Windows because they
lock and encrypt their cookies. Keeping yt-dlp up to date also helps, because
sites change often: `.\.venv\Scripts\python.exe -m pip install -U yt-dlp`.

---

## Testing

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

The suite covers VTF encoding (round-tripped through `srctools`) and damaged-file
detection, the size budget solver, image geometry/chroma key, ffmpeg extraction,
loop detection, SSRF protection, TF2 detection, the spray library (previews,
delete/undo, import), the rotation config writer, and the full API via
`TestClient`.

---

## Project structure

```
backend/
  app/
    main.py            FastAPI app + static frontend mount
    config.py          settings + TF2 spray constants
    models.py          request/response models
    routes/            media, spray, and library HTTP routes
    services/
      library.py       installed sprays: list, previews, delete/undo, import
      spray_randomizer.py  random-spray-each-game TF2 configs
      vtf_writer.py    custom VTF 7.1 writer (+ libsquish DXT), damaged-file check
      vmt_writer.py    VMT generation
      sizing.py        format + resolution budget solver
      imageproc.py     fit modes, chroma key
      spray_builder.py orchestration (frames -> spray)
      ffmpeg_utils.py  probe / extract / trim / transcode
      loopfinder.py    seamless-loop search
      ingest.py        uploads + yt-dlp/HTTP (SSRF guarded)
      tf2_locate.py    Steam/TF2 detection + save
      storage.py       per-job working dirs
      jobs.py          job helpers (frames, filmstrip)
  tests/               pytest suite
frontend/              vanilla HTML/CSS/JS app (My Sprays + Create Spray tabs)
run.py                 launcher
testdata/              sample-media generator for manual testing
```

---

## Security & legal notes

- The server binds to **localhost** and is intended for personal use.
- URL importing validates the scheme and **blocks private/loopback addresses**
  (basic SSRF protection); it can be disabled with `TF2SPRAY_URL_IMPORT=0`.
- Only convert media you have the rights to use.

## Credits

- DXT compression & VTF read-back: [`srctools`](https://github.com/TeamSpen210/srctools) (MIT).
- Spray format reference: the TF2 Wiki and the
  [Mishcatt/VTF-Editor](https://github.com/Mishcatt/VTF-Editor) browser tool.
