import asyncio, sys, glob
from playwright.async_api import async_playwright
src, dst, example = sys.argv[1], sys.argv[2], sys.argv[3]
html = open(src, encoding="utf-8").read().replace("{{EXAMPLE}}", example)
open("guide_final.html", "w", encoding="utf-8").write(html)
async def m():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(executable_path=glob.glob('/opt/pw-browsers/chromium-*/chrome-linux*/chrome')[0])
        p = await b.new_page()
        await p.goto(__import__("pathlib").Path("guide_final.html").resolve().as_uri())
        await p.wait_for_timeout(500)
        await p.pdf(path=dst, format="A4", print_background=True, display_header_footer=True,
                    header_template="<span></span>",
                    footer_template='<div style="font-size:8pt;color:#777;width:100%;text-align:center;font-family:Arial">ENC Chart Converter – User Guide · page <span class="pageNumber"></span> of <span class="totalPages"></span></div>',
                    margin={"top": "14mm", "bottom": "16mm", "left": "14mm", "right": "14mm"})
        await b.close()
asyncio.run(m())
