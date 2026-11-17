"""Find and launch a headless Chromium-family browser through Playwright.

On Windows the default is the installed Microsoft Edge (channel 'msedge'), so
nothing has to be downloaded. Software GL (SwiftShader) is allowed because a
headless browser on a server or VM usually has no GPU.
"""
from __future__ import annotations

import glob
import os
import sys

ARGS = ["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows"]


def _known_paths() -> list[str]:
    out = []
    env = os.environ.get("S57TOTPK_BROWSER")
    if env:
        out.append(env)
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if base:
                out.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
                out.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    else:
        out += sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"), reverse=True)
        out += ["/usr/bin/microsoft-edge", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    return [p for p in out if p and os.path.exists(p)]


async def launch(pw, browser_path: str | None = None, channel: str | None = None, log=print):
    """Launch with, in order: explicit path, explicit channel, Edge, Chrome,
    any known install path, Playwright's own Chromium."""
    tried = []
    attempts = []
    if browser_path:
        attempts.append(dict(executable_path=browser_path))
    if channel:
        attempts.append(dict(channel=channel))
    if not browser_path and not channel:
        attempts += [dict(channel="msedge"), dict(channel="chrome")]
        attempts += [dict(executable_path=p) for p in _known_paths()]
        attempts.append({})
    for kw in attempts:
        try:
            b = await pw.chromium.launch(headless=True, args=ARGS, **kw)
            log(f"Browser: {kw.get('channel') or kw.get('executable_path') or 'playwright chromium'} {b.version}")
            return b
        except Exception as e:  # noqa: BLE001
            tried.append(f"{kw or 'bundled'}: {str(e).splitlines()[0]}")
    raise RuntimeError("Could not start a browser (Edge/Chrome). Tried:\n  " + "\n  ".join(tried))
