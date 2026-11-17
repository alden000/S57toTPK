"""Window for people who don't use a command line.

The window collects the settings, then runs the converter as a child
process (the same exe with `run ...`) and follows its progress lines
(see progress.py). Stop is safe at any time: Start again continues where
it stopped.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading

from . import progress

APP_TITLE = "ENC charts to ArcGIS tile package"

DETAIL_PRESETS = [
    # label, minzoom, maxzoom, hint
    ("Overview", 8, 13, "Whole area down to about 1:72,000. Small and quick."),
    ("Standard (recommended)", 9, 16, "Down to about 1:9,000: good for navigation and harbour approaches."),
    ("Maximum", 9, 17, "Down to about 1:4,500. Can take many hours and a lot of disk space for big areas."),
    ("Custom", None, None, "Choose the zoom levels yourself."),
]
SCALE0 = 591657527.591555


def scale_text(z: int) -> str:
    s = SCALE0 / (1 << int(z))  # nominal scale, as ArcGIS shows it
    if s >= 10000:
        s = round(s / 1000) * 1000
    elif s >= 1000:
        s = round(s / 100) * 100
    return f"1:{int(s):,}"


def _settings_path() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "s57totpk", "settings.json")


def load_settings() -> dict:
    try:
        with open(_settings_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_settings(d: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_settings_path()), exist_ok=True)
        with open(_settings_path(), "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=1)
    except OSError:
        pass


def _hide_own_console():
    """Double-clicked exe: drop the console window Windows opened for us
    (but keep it when started from an existing console)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        buf = (ctypes.c_uint * 4)()
        if k.GetConsoleProcessList(buf, 4) <= 1:
            k.FreeConsole()
    except Exception:  # noqa: BLE001
        pass


def _self_cmd() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "s57totpk"]


def _fmt_time(sec) -> str:
    if sec is None:
        return ""
    sec = int(sec)
    if sec < 90:
        return "less than 2 minutes left"
    if sec < 3600:
        return f"about {round(sec / 60)} minutes left"
    return f"about {sec // 3600} h {round(sec % 3600 / 60)} min left"


class Child:
    """A converter child process whose output lines go to a queue."""

    def __init__(self, args: list[str], q: queue.Queue, tag: str, hold_stdin: bool = False):
        kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # no console window
        env = dict(os.environ, PYTHONUNBUFFERED="1", S57TOTPK_PROGRESS="1")
        self.p = subprocess.Popen(_self_cmd() + args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  stdin=subprocess.PIPE if hold_stdin else subprocess.DEVNULL, env=env, **kw)
        self.tag = tag
        threading.Thread(target=self._pump, args=(q,), daemon=True).start()

    def _pump(self, q):
        for raw in iter(self.p.stdout.readline, b""):
            q.put((self.tag, raw.decode("utf-8", "replace").rstrip("\r\n")))
        self.p.wait()
        q.put((self.tag, None))

    def running(self) -> bool:
        return self.p.poll() is None

    def stop(self):
        if self.running():
            self.p.terminate()


def main(_test_hook=None):
    """_test_hook(ns) is called once the window is up (used by tests)."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText

    _hide_own_console()
    st = load_settings()
    root = tk.Tk()
    root.title(APP_TITLE)
    root.minsize(760, 560)
    style = ttk.Style()
    if sys.platform == "win32" and "vista" in style.theme_names():
        style.theme_use("vista")
    style.configure("Head.TLabel", font=("Segoe UI", 11, "bold") if sys.platform == "win32" else ("TkDefaultFont", 11, "bold"))
    style.configure("Hint.TLabel", foreground="#555")
    style.configure("Big.TButton", padding=(18, 6))

    V = {
        "enc": tk.StringVar(value=st.get("enc", "")),
        "out": tk.StringVar(value=st.get("out", "")),
        "name": tk.StringVar(value=st.get("name", "ENC")),
        "preset": tk.IntVar(value=st.get("preset", 1)),
        "minzoom": tk.IntVar(value=st.get("minzoom", 9)),
        "maxzoom": tk.IntVar(value=st.get("maxzoom", 16)),
        "detail_on": tk.BooleanVar(value=st.get("detail_on", False)),
        "detail_maxzoom": tk.IntVar(value=st.get("detail_maxzoom", 18)),
        "day": tk.BooleanVar(value=st.get("day", True)),
        "dusk": tk.BooleanVar(value=st.get("dusk", False)),
        "night": tk.BooleanVar(value=st.get("night", False)),
        "tpkx": tk.BooleanVar(value=st.get("tpkx", True)),
        "tpk": tk.BooleanVar(value=st.get("tpk", False)),
        "tile_size": tk.StringVar(value=st.get("tile_size", "High-DPI (sharp on modern screens)")),
        "format": tk.StringVar(value=st.get("format", "PNG (best quality)")),
        "safety_depth": tk.DoubleVar(value=st.get("safety_depth", 10.0)),
        "safety_contour": tk.DoubleVar(value=st.get("safety_contour", 10.0)),
        "shallow_contour": tk.DoubleVar(value=st.get("shallow_contour", 2.0)),
        "deep_contour": tk.DoubleVar(value=st.get("deep_contour", 30.0)),
        "browser": tk.StringVar(value=st.get("browser", "Automatic")),
        "browser_path": tk.StringVar(value=st.get("browser_path", "")),
        "workers": tk.StringVar(value=st.get("workers", "Automatic")),
    }
    detail_bbox = list(st.get("detail_bbox") or []) or None
    state = {"run": None, "preview": None, "schemes": [], "files": [], "error": None, "scan": 0}
    q: queue.Queue = queue.Queue()

    outer = ttk.Frame(root, padding=14)
    outer.pack(fill="both", expand=True)
    outer.columnconfigure(1, weight=1)
    row = [0]

    def head(text):
        ttk.Label(outer, text=text, style="Head.TLabel").grid(row=row[0], column=0, columnspan=3, sticky="w", pady=(10, 2))
        row[0] += 1

    def line(label, widget, button=None, hint=None):
        if label:
            ttk.Label(outer, text=label).grid(row=row[0], column=0, sticky="w", padx=(0, 8))
        widget.grid(row=row[0], column=1, sticky="ew", pady=2)
        if button:
            button.grid(row=row[0], column=2, padx=(6, 0))
        row[0] += 1
        if hint is not None:
            hint.grid(row=row[0], column=1, columnspan=2, sticky="w")
            row[0] += 1

    # 1 charts --------------------------------------------------------------
    head("1.  Charts")
    found = ttk.Label(outer, text="", style="Hint.TLabel", wraplength=520)

    def scan_charts(*_):
        path = V["enc"].get().strip()
        state["scan"] += 1
        token = state["scan"]
        if not path or not os.path.isdir(path):
            found.config(text="Choose the ENC_ROOT folder (it holds a folder per chart).")
            return
        found.config(text="Looking for charts...")

        def work():
            try:
                from .cells import discover
                cells = discover(path, log=lambda *_: None)
                if not cells:
                    txt = "No S-57 charts (.000 files) found in this folder."
                else:
                    sc = sorted(c.scale for c in cells if c.scale)
                    upd = sum(len(c.updates) for c in cells)
                    txt = f"Found {len(cells)} chart(s)"
                    if sc:
                        txt += f", scales 1:{sc[0]:,} to 1:{sc[-1]:,}"
                    if upd:
                        txt += f", {upd} update file(s) to apply"
            except Exception as e:  # noqa: BLE001
                txt = f"Could not read the folder: {e}"
            q.put(("scan", (token, txt)))
        threading.Thread(target=work, daemon=True).start()

    def pick_enc():
        d = filedialog.askdirectory(title="Choose the ENC_ROOT folder", initialdir=V["enc"].get() or None)
        if d:
            V["enc"].set(os.path.normpath(d))
            if not V["out"].get():
                parent = os.path.dirname(os.path.normpath(d))
                V["out"].set(os.path.join(parent, "ArcGIS tile packages"))
            scan_charts()

    line("Charts folder (ENC_ROOT)", ttk.Entry(outer, textvariable=V["enc"]),
         ttk.Button(outer, text="Browse...", command=pick_enc), found)
    V["enc"].trace_add("write", lambda *_: root.after(600, scan_charts))

    # 2 output ----------------------------------------------------------------
    head("2.  Where to save")

    def pick_out():
        d = filedialog.askdirectory(title="Choose where to save the package", initialdir=V["out"].get() or None)
        if d:
            V["out"].set(os.path.normpath(d))

    line("Save to folder", ttk.Entry(outer, textvariable=V["out"]), ttk.Button(outer, text="Browse...", command=pick_out))
    line("Package name", ttk.Entry(outer, textvariable=V["name"], width=30))

    # 3 detail ----------------------------------------------------------------
    head("3.  How much detail")
    pf = ttk.Frame(outer)
    custom = ttk.Frame(pf)
    for i, (label, _a, _b, hint) in enumerate(DETAIL_PRESETS):
        ttk.Radiobutton(pf, text=label, value=i, variable=V["preset"]).grid(row=i, column=0, sticky="w", pady=1)
        ttk.Label(pf, text=hint, style="Hint.TLabel", wraplength=300).grid(row=i, column=1, sticky="w", padx=(10, 0))
    custom.grid(row=len(DETAIL_PRESETS), column=0, columnspan=2, sticky="w", padx=(24, 0))
    line("Detail level", pf)
    ttk.Label(custom, text="from zoom").pack(side="left")
    ttk.Spinbox(custom, from_=0, to=19, width=4, textvariable=V["minzoom"]).pack(side="left", padx=4)
    ttk.Label(custom, text="to zoom").pack(side="left")
    ttk.Spinbox(custom, from_=0, to=19, width=4, textvariable=V["maxzoom"]).pack(side="left", padx=4)
    custom_scale = ttk.Label(custom, style="Hint.TLabel")
    custom_scale.pack(side="left", padx=8)

    def on_preset(*_):
        i = V["preset"].get()
        if DETAIL_PRESETS[i][1] is not None:
            V["minzoom"].set(DETAIL_PRESETS[i][1])
            V["maxzoom"].set(DETAIL_PRESETS[i][2])
            custom.grid_remove()
        else:
            custom.grid()
        on_zoom()

    def on_zoom(*_):
        try:
            a, b = V["minzoom"].get(), V["maxzoom"].get()
            custom_scale.config(text=f"({scale_text(a)} to {scale_text(b)})")
        except tk.TclError:
            pass

    V["preset"].trace_add("write", on_preset)
    V["minzoom"].trace_add("write", on_zoom)
    V["maxzoom"].trace_add("write", on_zoom)

    df = ttk.Frame(outer)
    ttk.Checkbutton(df, text="Add extra detail in one area (for example a harbour)",
                    variable=V["detail_on"]).grid(row=0, column=0, columnspan=4, sticky="w")
    ttk.Label(df, text="down to zoom").grid(row=1, column=0, sticky="w", padx=(24, 4))
    ttk.Spinbox(df, from_=10, to=20, width=4, textvariable=V["detail_maxzoom"]).grid(row=1, column=1, sticky="w")
    area_btn = ttk.Button(df, text="Choose area on map...")
    area_btn.grid(row=1, column=2, sticky="w", padx=8)
    area_lbl = ttk.Label(df, style="Hint.TLabel", wraplength=300)
    area_lbl.grid(row=1, column=3, sticky="w")
    line("Extra detail", df)

    def show_area():
        if detail_bbox:
            w, s, e, n = detail_bbox
            import math
            wkm = abs(e - w) * 111.32 * math.cos(math.radians((s + n) / 2))
            area_lbl.config(text=f"Area chosen: about {wkm:.1f} km x {abs(n - s) * 111.32:.1f} km.")
        else:
            area_lbl.config(text="No area chosen yet." if V["detail_on"].get() else "")

    V["detail_on"].trace_add("write", lambda *_: show_area())

    # 4 colours & package type -----------------------------------------------
    head("4.  Colours and package type")
    cf = ttk.Frame(outer)
    for k, t in (("day", "Day"), ("dusk", "Dusk"), ("night", "Night")):
        ttk.Checkbutton(cf, text=t, variable=V[k]).pack(side="left", padx=(0, 12))
    ttk.Label(cf, text="(one package each)", style="Hint.TLabel").pack(side="left")
    line("Colours", cf)
    kf = ttk.Frame(outer)
    ttk.Checkbutton(kf, text=".tpkx  (ArcGIS Pro 2.3+, Field Maps, ArcGIS Online)", variable=V["tpkx"]).pack(anchor="w")
    ttk.Checkbutton(kf, text=".tpk  (older ArcGIS apps)", variable=V["tpk"]).pack(anchor="w")
    line("Package type", kf)

    # advanced ------------------------------------------------------------------
    adv_open = tk.BooleanVar(value=False)
    adv_btn = ttk.Button(outer, text="Show advanced settings")
    adv_btn.grid(row=row[0], column=0, columnspan=2, sticky="w", pady=(10, 0))
    row[0] += 1
    adv = ttk.LabelFrame(outer, text="Advanced settings", padding=8)
    adv.grid(row=row[0], column=0, columnspan=3, sticky="ew")
    adv.columnconfigure(1, weight=1)
    adv_row = row[0]
    row[0] += 1

    def arow(r, label, w):
        ttk.Label(adv, text=label).grid(row=r, column=0, sticky="w", padx=(0, 8), pady=2)
        w.grid(row=r, column=1, sticky="w", pady=2)

    arow(0, "Tile sharpness", ttk.Combobox(adv, state="readonly", width=36, textvariable=V["tile_size"],
                                           values=("High-DPI (sharp on modern screens)", "Standard (smaller files)")))
    arow(1, "Image format", ttk.Combobox(adv, state="readonly", width=36, textvariable=V["format"],
                                         values=("PNG (best quality)", "JPEG (smallest)", "Mixed (JPEG inside, PNG at edges)")))
    dp = ttk.Frame(adv)
    for i, (lbl, key) in enumerate((("Safety depth", "safety_depth"), ("Safety contour", "safety_contour"),
                                    ("Shallow contour", "shallow_contour"), ("Deep contour", "deep_contour"))):
        ttk.Label(dp, text=lbl).grid(row=i // 2, column=(i % 2) * 2, sticky="w", padx=(0 if i % 2 == 0 else 16, 4))
        ttk.Entry(dp, width=6, textvariable=V[key]).grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w", pady=1)
    arow(2, "Depths (metres)", dp)
    bf = ttk.Frame(adv)
    bcombo = ttk.Combobox(bf, state="readonly", width=16, textvariable=V["browser"],
                          values=("Automatic", "Microsoft Edge", "Google Chrome", "Other..."))
    bcombo.pack(side="left")
    bpath = ttk.Label(bf, textvariable=V["browser_path"], style="Hint.TLabel")
    bpath.pack(side="left", padx=6)

    def on_browser(*_):
        if V["browser"].get() == "Other...":
            f = filedialog.askopenfilename(title="Choose a Chromium-based browser (e.g. brave.exe, vivaldi.exe)",
                                           filetypes=[("Programs", "*.exe"), ("All files", "*.*")])
            if f:
                V["browser_path"].set(os.path.normpath(f))
            elif not V["browser_path"].get():
                V["browser"].set("Automatic")
        else:
            V["browser_path"].set("")

    bcombo.bind("<<ComboboxSelected>>", on_browser)
    arow(3, "Browser used to draw", bf)
    arow(4, "Parallel browsers", ttk.Combobox(adv, state="readonly", width=12, textvariable=V["workers"],
                                              values=("Automatic", "1", "2", "3", "4", "6", "8")))
    ttk.Label(adv, text="Any Chromium-based browser can draw the chart (Edge, Chrome, Brave, Vivaldi, Opera). "
              "Firefox cannot. The preview opens in your normal browser, whichever it is.",
              style="Hint.TLabel", wraplength=560).grid(row=5, column=0, columnspan=2, sticky="w")
    adv.grid_remove()

    def toggle_adv():
        if adv_open.get():
            adv.grid_remove()
            adv_btn.config(text="Show advanced settings")
        else:
            adv.grid(row=adv_row, column=0, columnspan=3, sticky="ew")
            adv_btn.config(text="Hide advanced settings")
        adv_open.set(not adv_open.get())
        root.geometry("")  # fit the window to its content

    adv_btn.config(command=toggle_adv)

    # buttons + progress ---------------------------------------------------------
    bar = ttk.Frame(outer)
    bar.grid(row=row[0], column=0, columnspan=3, sticky="ew", pady=(14, 4))
    row[0] += 1
    start_btn = ttk.Button(bar, text="Start", style="Big.TButton")
    stop_btn = ttk.Button(bar, text="Stop", state="disabled")
    prev_btn = ttk.Button(bar, text="Preview chart")
    open_btn = ttk.Button(bar, text="Open output folder")
    start_btn.pack(side="left")
    stop_btn.pack(side="left", padx=6)
    prev_btn.pack(side="left", padx=6)
    open_btn.pack(side="right")

    status = ttk.Label(outer, text="Ready.")
    status.grid(row=row[0], column=0, columnspan=3, sticky="w")
    row[0] += 1
    pbar = ttk.Progressbar(outer, maximum=1000)
    pbar.grid(row=row[0], column=0, columnspan=3, sticky="ew", pady=4)
    row[0] += 1
    eta = ttk.Label(outer, text="", style="Hint.TLabel")
    eta.grid(row=row[0], column=0, columnspan=3, sticky="w")
    row[0] += 1
    log_btn = ttk.Button(outer, text="Show details")
    log_btn.grid(row=row[0], column=0, sticky="w", pady=(6, 0))
    row[0] += 1
    log = ScrolledText(outer, height=10, font=("Consolas", 9) if sys.platform == "win32" else None)
    log.grid(row=row[0], column=0, columnspan=3, sticky="nsew")
    log_row = row[0]
    log.grid_remove()

    def toggle_log():
        if log.winfo_ismapped():
            log.grid_remove()
            log_btn.config(text="Show details")
        else:
            log.grid(row=log_row, column=0, columnspan=3, sticky="nsew")
            outer.rowconfigure(log_row, weight=1)
            log_btn.config(text="Hide details")
        root.geometry("")

    log_btn.config(command=toggle_log)

    # ------------------------------------------------------------------------
    def current_settings() -> dict:
        d = {}
        for k, v in V.items():
            try:
                d[k] = v.get()
            except tk.TclError:
                pass
        d["detail_bbox"] = detail_bbox
        return d

    def common_args(out) -> list[str]:
        return ["--out", out,
                "--safety-depth", str(V["safety_depth"].get()), "--safety-contour", str(V["safety_contour"].get()),
                "--shallow-contour", str(V["shallow_contour"].get()), "--deep-contour", str(V["deep_contour"].get())]

    def check_inputs(need_out=True) -> str | None:
        enc = V["enc"].get().strip()
        if not enc or not os.path.isdir(enc):
            return "Please choose the charts folder (ENC_ROOT) first."
        if need_out and not V["out"].get().strip():
            return "Please choose where to save the package."
        return None

    def run_args() -> list[str]:
        schemes = [k for k in ("day", "dusk", "night") if V[k].get()]
        kinds = [k for k in ("tpkx", "tpk") if V[k].get()]
        if not schemes:
            raise ValueError("Tick at least one colour scheme.")
        if not kinds:
            raise ValueError("Tick at least one package type.")
        mn, mx = V["minzoom"].get(), V["maxzoom"].get()
        if mn > mx:
            raise ValueError("The first zoom level must not be larger than the last one.")
        name = "".join(ch for ch in V["name"].get().strip() if ch not in '\\/:*?"<>|') or "ENC"
        a = ["run", "--enc", V["enc"].get().strip(), *common_args(V["out"].get().strip()),
             "--name", name, "--minzoom", str(mn), "--maxzoom", str(mx),
             "--schemes", ",".join(schemes), "--package", ",".join(kinds),
             "--tile-size", "512" if V["tile_size"].get().startswith("High") else "256",
             "--format", {"P": "png", "J": "jpeg", "M": "mixed"}[V["format"].get()[0]]]
        if V["detail_on"].get():
            if not detail_bbox:
                raise ValueError("You ticked 'Extra detail in one area' but no area is chosen yet.\n"
                                 "Click 'Choose area on map...' or untick it.")
            if V["detail_maxzoom"].get() <= mx:
                raise ValueError(f"The extra-detail zoom must be deeper than {mx}.")
            a += ["--detail-bbox=" + ",".join(f"{v:.6f}" for v in detail_bbox),
                  "--detail-maxzoom", str(V["detail_maxzoom"].get())]
        b = V["browser"].get()
        if b == "Microsoft Edge":
            a += ["--channel", "msedge"]
        elif b == "Google Chrome":
            a += ["--channel", "chrome"]
        elif b == "Other..." and V["browser_path"].get():
            a += ["--browser", V["browser_path"].get()]
        if V["workers"].get() != "Automatic":
            a += ["--workers", V["workers"].get()]
        state["schemes"] = schemes
        return a

    def set_running(on: bool):
        start_btn.config(state="disabled" if on else "normal")
        stop_btn.config(state="normal" if on else "disabled")

    def on_start():
        err = check_inputs()
        if err:
            return messagebox.showwarning(APP_TITLE, err)
        try:
            args = run_args()
        except (ValueError, tk.TclError) as e:
            return messagebox.showwarning(APP_TITLE, str(e))
        save_settings(current_settings())
        if state["preview"]:
            state["preview"].stop()
        os.makedirs(V["out"].get().strip(), exist_ok=True)
        state.update(files=[], error=None)
        log.insert("end", "\n=== Start ===\n")
        pbar["value"] = 0
        status.config(text="Starting...")
        eta.config(text="")
        state["run"] = Child(args, q, "run")
        set_running(True)

    def on_stop():
        if state["run"] and state["run"].running():
            state["run"].stop()
            status.config(text="Stopped. Press Start to continue from where it stopped.")

    def start_preview(select: bool):
        err = check_inputs()
        if err:
            return messagebox.showwarning(APP_TITLE, err)
        if state["run"] and state["run"].running():
            return messagebox.showinfo(APP_TITLE, "Please wait until the conversion has finished (or press Stop).")
        if state["preview"]:
            state["preview"].stop()
        out = V["out"].get().strip()
        os.makedirs(out, exist_ok=True)
        scheme = next((k for k in ("day", "dusk", "night") if V[k].get()), "day")
        args = ["preview", "--enc", V["enc"].get().strip(), *common_args(out), "--scheme", scheme, "--exit-with-stdin"]
        if select:
            args.append("--select")
        state["preview"] = Child(args, q, "preview", hold_stdin=True)
        status.config(text="Preparing the chart for the map (first time can take a minute)...")
        pbar["value"] = 0

    area_btn.config(command=lambda: start_preview(True))
    prev_btn.config(command=lambda: start_preview(False))
    start_btn.config(command=on_start)
    stop_btn.config(command=on_stop)

    def on_open():
        o = V["out"].get().strip()
        if o and os.path.isdir(o):
            if sys.platform == "win32":
                os.startfile(o)  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", o])

    open_btn.config(command=on_open)

    def handle_progress(tag, msg):
        nonlocal detail_bbox
        if "event" in msg:
            ev = msg["event"]
            if ev == "selection":
                detail_bbox = msg["bbox"]
                V["detail_on"].set(True)
                show_area()
                save_settings(current_settings())
                status.config(text="Extra-detail area chosen.")
                root.lift()
            elif ev == "preview":
                status.config(text="The chart is open in your web browser.")
                pbar["value"] = 0
            elif ev == "result":
                state["files"] = msg.get("files", [])
            elif ev == "error":
                state["error"] = msg.get("message")
            return
        stage, done, total = msg.get("stage"), msg.get("done", 0), max(1, msg.get("total", 1))
        f = done / total
        if stage == "composite":
            overall = 0.08 * f
            text = f"Reading charts ({done} of {total})"
        elif stage == "render":
            sch = state["schemes"] or ["day"]
            i = sch.index(msg.get("scheme")) if msg.get("scheme") in sch else 0
            overall = 0.08 + 0.88 * (i + f) / len(sch)
            text = f"Drawing {msg.get('scheme', '')} chart tiles: {f * 100:.0f}%" + (f" (zoom {msg['zoom']})" if "zoom" in msg else "")
            eta.config(text=_fmt_time(msg.get("eta")) if f < 1 else "")
        elif stage == "package":
            overall = 0.96 + 0.04 * f
            text = "Writing the package file"
            eta.config(text="")
        else:
            return
        if tag == "run":
            pbar["value"] = overall * 1000
        else:
            pbar["value"] = f * 1000
        status.config(text=text)

    def on_finished(tag, child):
        if tag == "run":
            set_running(False)
            code = child.p.returncode
            if code == 0 and state["files"]:
                pbar["value"] = 1000
                eta.config(text="")
                status.config(text="Finished.")
                names = "\n".join("  " + os.path.basename(p) for p in state["files"])
                if messagebox.askyesno(APP_TITLE, "Finished! Your tile package(s):\n\n" + names +
                                       "\n\nAdd them in ArcGIS Pro with Add Data, or copy them to your device "
                                       "for Field Maps.\n\nOpen the folder now?"):
                    on_open()
            elif state["error"]:
                status.config(text="Stopped because of a problem.")
                messagebox.showerror(APP_TITLE, state["error"] + "\n\nPress Start to try again; "
                                     "finished work is kept.")
            elif code not in (0, None):
                if "Stopped" not in status.cget("text"):
                    status.config(text="Stopped. Press Start to continue from where it stopped.")
        elif tag == "preview" and state["error"]:
            status.config(text="The preview could not be opened.")
            messagebox.showerror(APP_TITLE, state["error"])
            state["error"] = None

    def poll():
        try:
            while True:
                tag, item = q.get_nowait()
                if tag == "scan":
                    token, txt = item
                    if token == state["scan"]:
                        found.config(text=txt)
                    continue
                child = state.get(tag)
                if item is None:
                    if child:
                        on_finished(tag, child)
                    continue
                msg = progress.parse(item)
                if msg is not None:
                    handle_progress(tag, msg)
                    continue
                log.insert("end", item + "\n")
                log.see("end")
        except queue.Empty:
            pass
        root.after(150, poll)

    def on_close():
        if state["run"] and state["run"].running():
            if not messagebox.askyesno(APP_TITLE, "A conversion is running. Stop it and close?\n"
                                       "(Start again later to continue where it stopped.)"):
                return
            state["run"].stop()
        if state["preview"]:
            state["preview"].stop()
        save_settings(current_settings())
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    on_preset()
    show_area()
    scan_charts()
    poll()
    if _test_hook:
        ns = dict(root=root, V=V, start=start_btn, stop=stop_btn, preview=prev_btn, area=area_btn,
                  status=status, eta=eta, pbar=pbar, found=found, area_lbl=area_lbl, state=state,
                  toggle_adv=toggle_adv, toggle_log=toggle_log, messagebox=messagebox, log=log)
        root.after(300, lambda: _test_hook(ns))
    root.mainloop()
    return 0
