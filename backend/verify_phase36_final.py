import asyncio
import json
import subprocess
import httpx
import websockets
from pathlib import Path

BACKEND_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://localhost:5173"
CDP_PORT = 9222
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

class ChromeCDP:
    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws = None
        self.msg_id = 0

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url)

    async def send(self, method: str, params: dict = None):
        self.msg_id += 1
        msg = {"id": self.msg_id, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(msg))
        while True:
            resp = await self.ws.recv()
            data = json.loads(resp)
            if data.get("id") == self.msg_id:
                return data.get("result", {})

    async def eval_js(self, expression: str):
        res = await self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        return res.get("result", {}).get("value")

    async def close(self):
        if self.ws:
            await self.ws.close()


async def run_phase36_final_verification():
    print("==================================================", flush=True)
    print("PHASE 3.6 FINAL TOC + PDF NAVIGATION QUALITY PASS VERIFICATION", flush=True)
    print("==================================================", flush=True)

    # 1. Fetch versions list from backend
    async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=30.0) as client:
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
        FRONTEND_URL,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    results = {}
    try:
        await asyncio.sleep(2.0)

        # Get CDP page target
        async with httpx.AsyncClient() as http_client:
            targets_res = await http_client.get(f"http://127.0.0.1:{CDP_PORT}/json")
            targets = targets_res.json()
            page = next(t for t in targets if t["type"] == "page")
            version_res = await http_client.get(f"http://127.0.0.1:{CDP_PORT}/json/version")
            browser_info = version_res.json().get("Browser", "Chrome")
            print(f"TARGET BROWSER: {browser_info}", flush=True)

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

        # Wait for workspace to mount and TOC items to load
        for _ in range(50):
            has_toc = await cdp.eval_js("!!document.querySelector('h3') && document.body.innerText.includes('Rational')")
            if has_toc:
                break
            await asyncio.sleep(0.2)

        # 2. CONTENTS HEADER & MISLEADING COUNT CHECK
        toc_header_text = await cdp.eval_js("document.querySelector('h3')?.innerText")
        print(f"TOC Header text: '{toc_header_text}'", flush=True)
        results["CONTENTS HEADER CLEAN"] = "PASS" if toc_header_text and "CONTENTS" in toc_header_text.upper() else "FAIL"
        results["MISLEADING UNIT COUNT ABSENT"] = "PASS" if "14 units" not in str(toc_header_text).lower() else "FAIL"

        # 3. PUBLIC SURFACE STRING AUDIT
        body_text = await cdp.eval_js("document.body.innerText")
        prohibited = [
            "ActivityNode", "Readable Content", "Parsed Structure",
            "GENERIC TEXT", "MATHEMATICAL EXPLANATION", "Bounding Box",
            "Year Not Detected"
        ]
        found_prohibited = [p for p in prohibited if p.lower() in str(body_text).lower()]
        print(f"Prohibited strings in rendered UI: {found_prohibited}", flush=True)
        results["NO ACTIVITYNODE UI"] = "PASS" if not found_prohibited else "FAIL"
        results["HEADER 'YEAR NOT DETECTED' HIDDEN WHEN UNKNOWN"] = "PASS" if "year not detected" not in str(body_text).lower() else "FAIL"

        # Check STEM badge removed from primary header
        header_chips = await cdp.eval_js("document.querySelector('h2')?.parentElement?.innerText || ''")
        results["STEM BADGE REMOVED FROM PRIMARY HEADER"] = "PASS" if "STEM" not in header_chips else "FAIL"

        # 4. EXERCISE AT PAGE 32 (BOOK PAGE 27) AUDIT
        await asyncio.sleep(0.8)
        # Click Chapter 2 row to select and auto-expand
        step4_debug = await cdp.eval_js("""
            (() => {
                const rows = Array.from(document.querySelectorAll('.cursor-pointer'));
                const ch2 = rows.find(r => r.innerText.includes('Proportion'));
                if (!ch2) return 'ch2_not_found';
                ch2.click();
                return 'ch2_clicked';
            })()
        """)
        print(f"Step 4 expand debug: {step4_debug}", flush=True)
        await asyncio.sleep(0.8)

        ex_21_text = await cdp.eval_js("""
            (() => {
                const items = Array.from(document.querySelectorAll('.cursor-pointer'));
                const ex = items.find(el => el.innerText.includes('p.27'));
                return ex ? ex.innerText.replace(/\\n/g, ' ') : null;
            })()
        """)
        print(f"Page 32 (Book p.27) row text: '{ex_21_text}'", flush=True)
        results["EXERCISE 2.1 TOC DISPLAY"] = "PASS" if ex_21_text and "p.27" in ex_21_text else "FAIL"










        # 5. FIVE REAL NAVIGATION JUMPS
        print("\n--- 5 REAL NAVIGATION JUMPS TEST ---", flush=True)
        jumps_results = []

        # Jump 1: Chapter 3 (PDF p.48, Book p.43)
        await cdp.eval_js("""
            (() => {
                const items = Array.from(document.querySelectorAll('.cursor-pointer'));
                const ch3 = items.find(el => el.innerText.includes('Measurement'));
                if (ch3) ch3.click();
            })()
        """)
        await asyncio.sleep(0.4)
        src_j1 = await cdp.eval_js("document.querySelector('iframe')?.src")
        badge_j1 = await cdp.eval_js("document.querySelector('.border-blue-200')?.innerText")
        j1_pass = "#page=48" in str(src_j1)
        jumps_results.append(("Chapter 3 (Measurement)", "43", 48, src_j1, badge_j1, "PASS" if j1_pass else "FAIL"))

        # Jump 2: Lesson 3.3 (PDF p.52, Book p.47)
        await cdp.eval_js("""
            (() => {
                const items = Array.from(document.querySelectorAll('.cursor-pointer'));
                const l = items.find(el => el.innerText.includes('3.3') || el.innerText.includes('weights'));
                if (l) l.click();
            })()
        """)
        await asyncio.sleep(0.4)
        src_j2 = await cdp.eval_js("document.querySelector('iframe')?.src")
        badge_j2 = await cdp.eval_js("document.querySelector('.border-blue-200')?.innerText")
        j2_pass = "#page=52" in str(src_j2)
        jumps_results.append(("Lesson 3.3 (Measurement of weights)", "47", 52, src_j2, badge_j2, "PASS" if j2_pass else "FAIL"))

        # Jump 3: Numbered Exercise 3 (PDF p.58, Book p.53)
        await cdp.eval_js("""
            (() => {
                const items = Array.from(document.querySelectorAll('.cursor-pointer'));
                const ex = items.find(el => el.innerText.includes('Exercise 3'));
                if (ex) ex.click();
            })()
        """)
        await asyncio.sleep(0.4)
        src_j3 = await cdp.eval_js("document.querySelector('iframe')?.src")
        badge_j3 = await cdp.eval_js("document.querySelector('.border-blue-200')?.innerText")
        j3_pass = "#page=58" in str(src_j3)
        jumps_results.append(("Exercise 3", "53", 58, src_j3, badge_j3, "PASS" if j3_pass else "FAIL"))

        # Jump 4: Exercise on page 32 (Book p.27)
        await cdp.eval_js("""
            (() => {
                const items = Array.from(document.querySelectorAll('.cursor-pointer'));
                const ch2 = items.find(el => el.innerText.includes('Proportion'));
                if (ch2) ch2.click();
            })()
        """)
        await asyncio.sleep(0.5)
        await cdp.eval_js("""
            (() => {
                const items = Array.from(document.querySelectorAll('.cursor-pointer'));
                const ex = items.find(el => el.innerText.includes('p.27'));
                if (ex) ex.click();
            })()
        """)
        await asyncio.sleep(0.5)
        src_j4 = await cdp.eval_js("document.querySelector('iframe')?.src")
        badge_j4 = await cdp.eval_js("document.querySelector('.border-blue-200')?.innerText")
        j4_pass = "#page=32" in str(src_j4)
        jumps_results.append(("Exercise (p.32, Book p.27)", "27", 32, src_j4, badge_j4, "PASS" if j4_pass else "FAIL"))




        # Jump 5: Long-distance Jump -> Chapter 10 (Congruence, PDF p.166, Book p.161)
        await cdp.eval_js("""
            (() => {
                const items = Array.from(document.querySelectorAll('.cursor-pointer'));
                const ch10 = items.find(el => el.innerText.includes('Congruence and Similarity'));
                if (ch10) ch10.click();
            })()
        """)
        await asyncio.sleep(0.4)
        src_j5 = await cdp.eval_js("document.querySelector('iframe')?.src")
        badge_j5 = await cdp.eval_js("document.querySelector('.border-blue-200')?.innerText")
        j5_pass = "#page=166" in str(src_j5)
        jumps_results.append(("Chapter 10 (Congruence & Similarity)", "161", 166, src_j5, badge_j5, "PASS" if j5_pass else "FAIL"))

        for label, b_lbl, pdf_p, src, badge, st in jumps_results:
            print(f"  JUMP [{label}]: Target PDF #{pdf_p}, Book p.{b_lbl} -> Iframe: '{src}', Badge: '{badge}' [{st}]", flush=True)

        results["PRINTED PAGE / PDF PAGE SEPARATION"] = "PASS" if all(r[5] == "PASS" for r in jumps_results) else "FAIL"
        results["CHAPTER NAVIGATION"] = "PASS" if j1_pass else "FAIL"
        results["LESSON NAVIGATION"] = "PASS" if j2_pass else "FAIL"
        results["EXERCISE NAVIGATION"] = "PASS" if j3_pass and j4_pass else "FAIL"
        results["LONG-DISTANCE NAVIGATION"] = "PASS" if j5_pass else "FAIL"

        # 6. RAPID CLICK TEST
        print("\n--- RAPID CLICK TEST ---", flush=True)
        rapid_targets = await cdp.eval_js("""
            (() => {
                const items = Array.from(document.querySelectorAll('.cursor-pointer'));
                const ch1 = items.find(el => el.innerText.includes('Rational'));
                const ch3 = items.find(el => el.innerText.includes('Measurement'));
                const ch10 = items.find(el => el.innerText.includes('Congruence'));

                // Rapid successive clicks without waiting
                if (ch1) ch1.click();
                if (ch3) ch3.click();
                if (ch10) ch10.click();
                return true;
            })()
        """)
        await asyncio.sleep(0.8)
        final_rapid_src = await cdp.eval_js("document.querySelector('iframe')?.src")
        print(f"Final iframe src after rapid clicks (Ch1 -> Ch3 -> Ch10): {final_rapid_src}", flush=True)
        results["RAPID TOC CLICK FINAL TARGET CORRECT"] = "PASS" if final_rapid_src and "#page=166" in final_rapid_src else "FAIL"

        # 7. UI LAYOUT & BUTTONS AUDIT
        toc_col = await cdp.eval_js("document.querySelector('.lg\\\\:col-span-3, [class*=\"lg:col-span-3\"]') !== null")
        pdf_col = await cdp.eval_js("document.querySelector('.lg\\\\:col-span-9, [class*=\"lg:col-span-9\"]') !== null")
        results["PDF REMAINS DOMINANT"] = "PASS" if toc_col and pdf_col else "FAIL"

        open_tab = await cdp.eval_js("!!document.querySelector('a[href*=\"/pdf\"][target=\"_blank\"]')")
        results["OPEN PDF IN TAB"] = "PASS" if open_tab else "FAIL"

        gen_mcq_btn = await cdp.eval_js("!!Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Generate MCQs'))")
        results["GENERATE MCQS NAVIGATION"] = "PASS" if gen_mcq_btn else "FAIL"

        print("\n==================================================", flush=True)
        print("REAL CHROME FINAL REPORT:", flush=True)
        print("==================================================", flush=True)
        for k, v in results.items():
            print(f"{k}: {v}", flush=True)
        print("==================================================", flush=True)

        assert all(v == "PASS" for v in results.values()), "Some verification checks failed!"
        print("ALL REAL CHROME VERIFICATION CHECKS PASSED!", flush=True)

    finally:
        try:
            await cdp.close()
        except Exception:
            pass
        chrome_proc.terminate()
        try:
            chrome_proc.wait(timeout=2)
        except Exception:
            chrome_proc.kill()


if __name__ == "__main__":
    asyncio.run(run_phase36_final_verification())
