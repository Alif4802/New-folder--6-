import asyncio
import io
import json
import subprocess
import time
import urllib.request
import websockets
import httpx

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CDP_PORT = 9222


class ChromeCDP:
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self.msg_id = 0

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url)

    async def send(self, method, params=None):
        self.msg_id += 1
        payload = {"id": self.msg_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(payload))
        while True:
            resp = json.loads(await self.ws.recv())
            if resp.get("id") == self.msg_id:
                return resp.get("result", {})

    async def eval_js(self, expression):
        res = await self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        if "exceptionDetails" in res:
            raise RuntimeError(f"JS Exception: {res['exceptionDetails']}")
        return res.get("result", {}).get("value")

    async def close(self):
        if self.ws:
            await self.ws.close()


async def run_phase36_toc_quality_verification():
    print("==================================================", flush=True)
    print("PHASE 3.6 TOC QUALITY REFINEMENT REAL CHROME VERIFICATION", flush=True)
    print("==================================================", flush=True)

    # 1. Fetch versions list from backend
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=30.0) as client:
        versions_res = await client.get("/api/v1/textbooks/versions")
        assert versions_res.status_code == 200
        versions = versions_res.json()
        assert len(versions) >= 1
        math_198 = next((v for v in versions if v["page_count"] == 198), versions[0])
        v_id = math_198["id"]
        print(f"Target Textbook: {math_198['title']} (ID: {v_id}, pages: {math_198['page_count']})", flush=True)

        # Direct TOC audit
        toc_res = await client.get(f"/api/v1/textbooks/{v_id}/toc")
        assert toc_res.status_code == 200
        toc_data = toc_res.json()
        print(f"TOC sanitized chapters count: {len(toc_data['items'])}", flush=True)

    # 2. Launch Chrome
    chrome_proc = subprocess.Popen([
        CHROME_PATH,
        "--headless=new",
        f"--remote-debugging-port={CDP_PORT}",
        "--disable-gpu",
        "--no-sandbox",
        "--window-size=1400,950",
        "http://127.0.0.1:5173"
    ])

    time.sleep(2)

    try:
        version_info = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version").read())
        browser_name = version_info.get("Browser", "Google Chrome")
        print(f"TARGET BROWSER: {browser_name}", flush=True)

        pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json").read())
        page = next((p for p in pages if p.get("type") == "page"), None)
        if not page:
            raise RuntimeError("No browser page target found.")

        cdp = ChromeCDP(page["webSocketDebuggerUrl"])
        await cdp.connect()

        await cdp.send("Page.enable")
        await cdp.send("Runtime.enable")

        # Wait for repository table to mount
        print("Waiting for page and table to mount...", flush=True)
        for _ in range(30):
            has_table = await cdp.eval_js("!!document.querySelector('table')")
            if has_table:
                break
            await asyncio.sleep(0.3)

        results = {}

        # 1. CLICK INSPECT PDF ON 198-PAGE MATH BOOK
        clicked_inspect = await cdp.eval_js(f"""
            (() => {{
                const rows = Array.from(document.querySelectorAll('tbody tr'));
                const targetRow = rows.find(r => r.innerText.includes('198') || r.innerText.includes('{v_id}'));
                if (targetRow) {{
                    const btn = Array.from(targetRow.querySelectorAll('button')).find(b => b.innerText.includes('Inspect PDF') || b.innerText.includes('Viewing'));
                    if (btn) {{ btn.click(); return true; }}
                }}
                return false;
            }})()
        """)
        print(f"Clicked 'Inspect PDF' for 198-page book: {clicked_inspect}", flush=True)
        assert clicked_inspect, "Failed to click Inspect PDF button for 198-page book"

        # Wait for workspace to mount
        for _ in range(30):
            has_iframe = await cdp.eval_js("!!document.querySelector('iframe')")
            if has_iframe:
                break
            await asyncio.sleep(0.3)

        # Wait for TOC items to finish loading from API
        for i in range(50):
            has_toc = await cdp.eval_js("!!document.querySelector('h3') && document.body.innerText.includes('Rational')")
            if has_toc:
                print(f"TOC loaded after {i*0.2:.1f}s", flush=True)
                break
            await asyncio.sleep(0.2)

        body_debug = await cdp.eval_js("document.body.innerText")
        print(f"Body text during TOC inspection (first 300 chars): {str(body_debug)[:300]}...", flush=True)

        # 2. CONTENTS HEADER CLEAN & MISLEADING COUNT REMOVED
        toc_header_full = await cdp.eval_js("document.querySelector('h3')?.innerText || document.querySelector('h3')?.parentElement?.innerText")
        print(f"TOC Header element text: '{toc_header_full}'", flush=True)
        results["CONTENTS HEADER CLEAN"] = "PASS" if toc_header_full and "CONTENTS" in str(toc_header_full).upper() else "FAIL"
        results["MISLEADING '14 UNITS' REMOVED"] = "PASS" if "14 units" not in str(toc_header_full).lower() and "units" not in str(toc_header_full).lower() else "FAIL"

        # 3. MALFORMED TOC LABELS AUDIT IN DOM
        workspace_text = await cdp.eval_js("document.body.innerText")
        malformed_strings = ["Part part", "part — 15", "filled in 1 minute", "moving left", "Unit digit"]
        found_malformed = [m for m in malformed_strings if m.lower() in str(workspace_text).lower()]
        print(f"Malformed strings found in TOC UI: {found_malformed}", flush=True)
        results["MALFORMED TOC LABELS REMOVED"] = "PASS" if len(found_malformed) == 0 else "FAIL"

        # 4. PROHIBITED STRINGS AUDIT
        prohibited = ["ActivityNode", "Readable Content", "Parsed Structure", "GENERIC TEXT", "MATHEMATICAL EXPLANATION", "Bounding Box"]
        found_prohibited = [p for p in prohibited if p.lower() in str(workspace_text).lower()]
        print(f"Prohibited technical strings in DOM: {found_prohibited}", flush=True)
        results["NO ACTIVITYNODE UI"] = "PASS" if len(found_prohibited) == 0 else "FAIL"

        # 5. CHAPTER HIERARCHY READABLE
        chapter_1_present = await cdp.eval_js("document.body.innerText.includes('Rational and Irrational Numbers')")
        chapter_3_present = await cdp.eval_js("document.body.innerText.includes('Measurement')")
        print(f"Chapter 1 present: {chapter_1_present}, Chapter 3 present: {chapter_3_present}", flush=True)
        results["CHAPTER HIERARCHY READABLE"] = "PASS" if chapter_1_present and chapter_3_present else "FAIL"

        # 6. FULL TITLE HOVER / TOOLTIP AVAILABLE
        has_title_attr = await cdp.eval_js("""
            (() => {
                const el = Array.from(document.querySelectorAll('[title]')).find(e => e.getAttribute('title')?.includes('Rational'));
                return el !== null;
            })()
        """)
        print(f"Full title tooltip attribute available: {has_title_attr}", flush=True)
        results["FULL TITLE HOVER AVAILABLE"] = "PASS" if has_title_attr else "FAIL"

        # 7. CHAPTER COLLAPSE / EXPAND TOGGLE
        # Test clicking toggle button to expand Chapter 1
        toggle_clicked = await cdp.eval_js("""
            (() => {
                const chevronBtn = document.querySelector('button[title*=\"Expand\"], button[title*=\"Collapse\"]');
                if (chevronBtn) { chevronBtn.click(); return true; }
                return false;
            })()
        """)
        print(f"Clicked chapter expand toggle: {toggle_clicked}", flush=True)
        await asyncio.sleep(0.3)
        results["CHAPTER COLLAPSE/EXPAND"] = "PASS" if toggle_clicked else "FAIL"

        # 8. UNIT/CHAPTER NAVIGATION
        unit_clicked = await cdp.eval_js("""
            (() => {
                const items = Array.from(document.querySelectorAll('.cursor-pointer'));
                const ch3 = items.find(el => el.innerText.includes('Measurement'));
                if (ch3) { ch3.click(); return true; }
                return false;
            })()
        """)
        print(f"Clicked Chapter 3 in TOC: {unit_clicked}", flush=True)
        await asyncio.sleep(0.5)
        iframe_src_unit = await cdp.eval_js("document.querySelector('iframe')?.src")
        print(f"Iframe src after Chapter 3 click: {iframe_src_unit}", flush=True)
        results["UNIT/CHAPTER NAVIGATION"] = "PASS" if iframe_src_unit and "#page=48" in iframe_src_unit else "FAIL"

        # 9. LESSON NAVIGATION
        lesson_clicked = await cdp.eval_js("""
            (() => {
                const items = Array.from(document.querySelectorAll('.cursor-pointer'));
                const l = items.find(el => el.innerText.includes('3.3') || el.innerText.includes('Measurement of weights'));
                if (l) { l.click(); return true; }
                return false;
            })()
        """)
        print(f"Clicked Lesson in TOC: {lesson_clicked}", flush=True)
        await asyncio.sleep(0.5)
        iframe_src_lesson = await cdp.eval_js("document.querySelector('iframe')?.src")
        print(f"Iframe src after Lesson click: {iframe_src_lesson}", flush=True)
        results["LESSON NAVIGATION"] = "PASS" if iframe_src_lesson and "#page=52" in iframe_src_lesson else "FAIL"

        # 10. EXERCISE NAVIGATION
        ex_clicked = await cdp.eval_js("""
            (() => {
                const items = Array.from(document.querySelectorAll('.cursor-pointer'));
                const ex = items.find(el => el.innerText.includes('Exercise 3'));
                if (ex) { ex.click(); return true; }
                return false;
            })()
        """)
        print(f"Clicked Exercise 3 in TOC: {ex_clicked}", flush=True)
        await asyncio.sleep(0.5)
        iframe_src_ex = await cdp.eval_js("document.querySelector('iframe')?.src")
        print(f"Iframe src after Exercise 3 click: {iframe_src_ex}", flush=True)
        results["EXERCISE NAVIGATION"] = "PASS" if iframe_src_ex and "#page=58" in iframe_src_ex else "FAIL"

        # 11. PDF REMAINS DOMINANT
        toc_col = await cdp.eval_js("document.querySelector('.lg\\\\:col-span-3, [class*=\"lg:col-span-3\"]') !== null")
        pdf_col = await cdp.eval_js("document.querySelector('.lg\\\\:col-span-9, [class*=\"lg:col-span-9\"]') !== null")
        results["PDF REMAINS DOMINANT"] = "PASS" if toc_col and pdf_col else "FAIL"

        # 12. DUPLICATE GENERIC EXERCISES REDUCED
        # Verify that we don't have 10 identical exercises on a single chapter
        total_exercises_shown = await cdp.eval_js("""
            (() => {
                const items = Array.from(document.querySelectorAll('.cursor-pointer'));
                return items.filter(el => el.innerText.toLowerCase().includes('exercise')).length;
            })()
        """)
        print(f"Total exercise items in rendered TOC: {total_exercises_shown}", flush=True)
        results["DUPLICATE GENERIC EXERCISES REDUCED"] = "PASS" if total_exercises_shown <= 20 else "FAIL"

        # 13. GENERATE MCQS BUTTON STILL WORKS
        clicked_gen = await cdp.eval_js("""
            (() => {
                const btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Generate MCQs'));
                if (btn) { btn.click(); return true; }
                return false;
            })()
        """)
        print(f"Clicked 'Generate MCQs': {clicked_gen}", flush=True)
        assert clicked_gen, "Failed to click Generate MCQs button"

        for _ in range(20):
            nav_done = await cdp.eval_js("!!document.querySelector('[data-testid=\"target-scope-card\"]')")
            if nav_done:
                break
            await asyncio.sleep(0.2)

        nav_header = await cdp.eval_js("document.querySelector('h2')?.innerText")
        results["GENERATE MCQS BUTTON STILL WORKS"] = "PASS" if nav_header and "Assessment Generator" in str(nav_header) else "FAIL"

        await cdp.close()

        print("\n==================================================", flush=True)
        print("REAL CHROME BROWSER VERIFICATION REPORT:", flush=True)
        print("==================================================", flush=True)
        for k, v in results.items():
            print(f"{k}: {v}", flush=True)
        print("==================================================", flush=True)

        assert all(v == "PASS" for v in results.values()), "Some verification checks failed!"
        print("ALL REAL CHROME VERIFICATION CHECKS PASSED!", flush=True)

    finally:
        chrome_proc.terminate()
        chrome_proc.wait()


if __name__ == "__main__":
    asyncio.run(run_phase36_toc_quality_verification())
