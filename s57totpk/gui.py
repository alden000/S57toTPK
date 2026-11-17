"""Small Tk front end (shown when the exe is started without arguments).
It builds a `run` command line and runs it as a child process, so Stop is
safe at any time: the next Run resumes from the staged tiles."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading


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


def main():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText

    _hide_own_console()
    root = tk.Tk()
    root.title("S-57 to ArcGIS tile package")
    root.minsize(760, 600)
    v = {
        "enc": tk.StringVar(), "out": tk.StringVar(), "name": tk.StringVar(value="ENC"),
        "minzoom": tk.IntVar(value=9), "maxzoom": tk.IntVar(value=16),
        "detail_bbox": tk.StringVar(), "detail_maxzoom": tk.StringVar(),
        "tile_size": tk.StringVar(value="512"), "format": tk.StringVar(value="png"),
        "workers": tk.IntVar(value=0), "safety_depth": tk.DoubleVar(value=10.0),
        "shallow": tk.DoubleVar(value=2.0), "safety": tk.DoubleVar(value=10.0), "deep": tk.DoubleVar(value=30.0),
        "day": tk.BooleanVar(value=True), "dusk": tk.BooleanVar(), "night": tk.BooleanVar(),
        "tpkx": tk.BooleanVar(value=True), "tpk": tk.BooleanVar(), "recomposite": tk.BooleanVar(),
    }
    frm = ttk.Frame(root, padding=8)
    frm.pack(fill="both", expand=True)
    frm.columnconfigure(1, weight=1)
    r = 0

    def row(label, widget, browse=None):
        nonlocal r
        ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=2)
        widget.grid(row=r, column=1, sticky="ew", pady=2)
        if browse:
            ttk.Button(frm, text="Browse...", command=browse).grid(row=r, column=2, padx=4)
        r += 1

    row("ENC_ROOT folder", ttk.Entry(frm, textvariable=v["enc"]),
        lambda: v["enc"].set(filedialog.askdirectory() or v["enc"].get()))
    row("Output folder", ttk.Entry(frm, textvariable=v["out"]),
        lambda: v["out"].set(filedialog.askdirectory() or v["out"].get()))
    row("Package name", ttk.Entry(frm, textvariable=v["name"]))

    z = ttk.Frame(frm)
    ttk.Label(z, text="min").pack(side="left")
    ttk.Spinbox(z, from_=0, to=20, width=4, textvariable=v["minzoom"]).pack(side="left", padx=2)
    ttk.Label(z, text="max").pack(side="left")
    ttk.Spinbox(z, from_=0, to=20, width=4, textvariable=v["maxzoom"]).pack(side="left", padx=2)
    ttk.Label(z, text="   tile size").pack(side="left")
    ttk.Combobox(z, values=("512", "256"), width=5, textvariable=v["tile_size"], state="readonly").pack(side="left")
    ttk.Label(z, text="   image").pack(side="left")
    ttk.Combobox(z, values=("png", "jpeg", "mixed"), width=6, textvariable=v["format"], state="readonly").pack(side="left")
    ttk.Label(z, text="   browsers (0=auto)").pack(side="left")
    ttk.Spinbox(z, from_=0, to=8, width=3, textvariable=v["workers"]).pack(side="left")
    row("Zoom levels", z)

    d = ttk.Frame(frm)
    ttk.Entry(d, textvariable=v["detail_bbox"]).pack(side="left", fill="x", expand=True)
    ttk.Label(d, text=" up to zoom").pack(side="left")
    ttk.Spinbox(d, from_=0, to=20, width=4, textvariable=v["detail_maxzoom"]).pack(side="left")
    row("Detail area (minlon,minlat,maxlon,maxlat)", d)

    s = ttk.Frame(frm)
    for k in ("day", "dusk", "night"):
        ttk.Checkbutton(s, text=k, variable=v[k]).pack(side="left")
    ttk.Label(s, text="     packages:").pack(side="left")
    ttk.Checkbutton(s, text=".tpkx", variable=v["tpkx"]).pack(side="left")
    ttk.Checkbutton(s, text=".tpk", variable=v["tpk"]).pack(side="left")
    ttk.Checkbutton(s, text="   redo composite", variable=v["recomposite"]).pack(side="left")
    row("Colour schemes", s)

    dp = ttk.Frame(frm)
    for lbl, key in (("safety depth", "safety_depth"), ("shallow", "shallow"), ("safety contour", "safety"), ("deep", "deep")):
        ttk.Label(dp, text=lbl).pack(side="left")
        ttk.Entry(dp, width=6, textvariable=v[key]).pack(side="left", padx=(2, 10))
    row("Depths (m)", dp)

    btns = ttk.Frame(frm)
    btns.grid(row=r, column=0, columnspan=3, sticky="w", pady=6)
    r += 1
    log = ScrolledText(frm, height=18, font=("Consolas", 9) if sys.platform == "win32" else None)
    log.grid(row=r, column=0, columnspan=3, sticky="nsew")
    frm.rowconfigure(r, weight=1)

    q: queue.Queue = queue.Queue()
    state = {"proc": None}

    def args():
        if not v["enc"].get() or not v["out"].get():
            raise ValueError("Choose the ENC_ROOT and output folders")
        schemes = [k for k in ("day", "dusk", "night") if v[k].get()] or ["day"]
        pk = [k for k in ("tpkx", "tpk") if v[k].get()] or ["tpkx"]
        a = ["run", "--enc", v["enc"].get(), "--out", v["out"].get(), "--name", v["name"].get() or "ENC",
             "--minzoom", str(v["minzoom"].get()), "--maxzoom", str(v["maxzoom"].get()),
             "--tile-size", v["tile_size"].get(), "--format", v["format"].get(),
             "--workers", str(v["workers"].get()), "--schemes", ",".join(schemes), "--package", ",".join(pk),
             "--safety-depth", str(v["safety_depth"].get()), "--shallow-contour", str(v["shallow"].get()),
             "--safety-contour", str(v["safety"].get()), "--deep-contour", str(v["deep"].get())]
        if v["detail_bbox"].get().strip():
            a += ["--detail-bbox=" + v["detail_bbox"].get().strip()]
            if v["detail_maxzoom"].get().strip():
                a += ["--detail-maxzoom", v["detail_maxzoom"].get().strip()]
        if v["recomposite"].get():
            a.append("--recomposite")
        return a

    def start(cmd_args):
        if state["proc"]:
            return
        kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        p = subprocess.Popen(_self_cmd() + cmd_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env=env, **kw)
        state["proc"] = p
        run_b.state(["disabled"])

        def pump():
            for line in iter(p.stdout.readline, b""):
                q.put(line.decode("utf-8", "replace"))
            p.wait()
            q.put(f"[finished, exit code {p.returncode}]\n")
            q.put(None)
        threading.Thread(target=pump, daemon=True).start()

    def on_run():
        try:
            start(args())
        except ValueError as e:
            messagebox.showerror("Missing input", str(e))

    def on_preview():
        if not v["out"].get():
            return messagebox.showerror("Missing input", "Choose the output folder (with a finished composite)")
        start(["preview", "--out", v["out"].get(), "--scheme", next((k for k in ("day", "dusk", "night") if v[k].get()), "day")])

    def on_stop():
        p = state["proc"]
        if p and p.poll() is None:
            p.terminate()

    def on_open():
        o = v["out"].get()
        if o and os.path.isdir(o):
            if sys.platform == "win32":
                os.startfile(o)  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", o])

    run_b = ttk.Button(btns, text="Run", command=on_run)
    run_b.pack(side="left")
    ttk.Button(btns, text="Stop", command=on_stop).pack(side="left", padx=4)
    ttk.Button(btns, text="Preview map", command=on_preview).pack(side="left", padx=4)
    ttk.Button(btns, text="Open output folder", command=on_open).pack(side="left", padx=4)

    def poll():
        try:
            while True:
                item = q.get_nowait()
                if item is None:
                    state["proc"] = None
                    run_b.state(["!disabled"])
                    continue
                log.insert("end", item)
                log.see("end")
        except queue.Empty:
            pass
        root.after(200, poll)

    def on_close():
        on_stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    poll()
    root.mainloop()
    return 0
