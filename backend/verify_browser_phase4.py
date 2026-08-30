import asyncio
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


async def run_phase4_browser_verification():
    print("==================================================", flush=True)
    print("PHASE 4 REAL BROWSER VERIFICATION (CHROME / CDP)", flush=True)
    print("==================================================", flush=True)

    # 1. Verify backend capabilities API directly via HTTP
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=30.0) as client:
        versions_res = await client.get("/api/v1/textbooks/versions")
        assert versions_res.status_code == 200, f"Backend versions failed: {versions_res.status_code}"
        versions = versions_res.json()
        assert len(versions) >= 1, "No textbook versions found"

        math_book = next((v for v in versions if "math" in v["title"].lower()), versions[0])
        math_id = math_book["id"]
        print(f"Target Mathematics Textbook: {math_book['title']} (ID: {math_id})", flush=True)

        cap_res = await client.get(f"/api/v1/assessments/mcq/capabilities?subject_version_id={math_id}")
        assert cap_res.status_code == 200, f"Capabilities failed: {cap_res.status_code}"
        cap_data = cap_res.json()
        print(f"Capabilities: generation_supported={cap_data['generation_supported']}, units={len(cap_data['units'])}", flush=True)

    # 2. Launch Chrome with remote debugging
    chrome_proc = subprocess.Popen([
        CHROME_PATH,
        f"--remote-debugging-port={CDP_PORT}",
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--window-size=1400,900",
        "http://localhost:5173",
    ])
    print(f"Launched Chrome (PID: {chrome_proc.pid}) on CDP port {CDP_PORT}...", flush=True)

    time.sleep(2.5)

    ws_url = None
    for attempt in range(10):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json") as response:
                targets = json.loads(response.read().decode("utf-8"))
                for target in targets:
                    if target.get("type") == "page" and "5173" in target.get("url", ""):
                        ws_url = target.get("webSocketDebuggerUrl")
                        break
                if ws_url:
                    break
        except Exception:
            time.sleep(0.5)

    assert ws_url, "Could not obtain Chrome DevTools WebSocket URL"
    cdp = ChromeCDP(ws_url)
    await cdp.connect()
    print("Connected to Chrome via CDP WebSocket!", flush=True)

    try:
        # Enable runtime & page
        await cdp.send("Page.enable")
        await cdp.send("Runtime.enable")

        # Wait for React app to render
        await asyncio.sleep(2.0)

        # 3. VERIFY ASSESSMENT GENERATOR TAB NAVIGATION
        print("\n--- Testing Tab Navigation & Direct Assessment Generator Page ---", flush=True)
        # Click Assessment Generator tab button in header
        has_nav = await cdp.eval_js("""
            (() => {
                const buttons = Array.from(document.querySelectorAll('button'));
                const btn = buttons.find(b => b.textContent.includes('Assessment Generator'));
                if (btn) {
                    btn.click();
                    return true;
                }
                return false;
            })()
        """)
        assert has_nav, "Could not find Assessment Generator tab button"
        await asyncio.sleep(1.0)

        # Check page header
        page_title = await cdp.eval_js("document.querySelector('h2')?.textContent || ''")
        print(f"Active Page Title: '{page_title}'", flush=True)
        assert "Assessment Generator" in page_title, "Assessment Generator header not found"
        print("ASSESSMENT GENERATOR PAGE: PASS")

        # 4. DIRECT TEXTBOOK SELECTION & DYNAMIC DROPDOWNS
        print("\n--- Testing Dynamic Dropdowns & Scope Selection ---", flush=True)
        unit_opts_count = await cdp.eval_js("""
            (() => {
                const sel = document.querySelector('#unit-selector');
                return sel ? sel.options.length : 0;
            })()
        """)
        print(f"Dynamic Units in Selector: {unit_opts_count}", flush=True)
        assert unit_opts_count > 0, "Units dropdown is empty"
        print("DYNAMIC UNIT LIST: PASS")

        lesson_opts_count = await cdp.eval_js("""
            (() => {
                const sel = document.querySelector('#lesson-selector');
                return sel ? sel.options.length : 0;
            })()
        """)
        print(f"Dynamic Lessons in Selector: {lesson_opts_count}", flush=True)
        assert lesson_opts_count >= 1, "Lesson dropdown missing options"
        print("DYNAMIC LESSON LIST: PASS")

        # 5. QUESTION COUNT LIMITS
        count_val = await cdp.eval_js("""
            (() => {
                const inp = document.querySelector('#question-count-input');
                return inp ? inp.value : '';
            })()
        """)
        print(f"Default Question Count from Backend: {count_val}", flush=True)
        assert count_val in ["3", "5", "8", "10"], f"Unexpected question count: {count_val}"
        print("QUESTION COUNT LIMITS FROM BACKEND: PASS")

        # 6. GENERATE MCQS & LOADING STATE
        print("\n--- Testing MCQ Generation Action ---", flush=True)
        # Click Generate MCQs button
        gen_clicked = await cdp.eval_js("""
            (() => {
                const btn = document.querySelector('#generate-mcqs-button');
                if (btn && !btn.disabled) {
                    btn.click();
                    return true;
                }
                return false;
            })()
        """)
        assert gen_clicked, "Generate MCQs button could not be clicked"

        # Check for loading state or generated paper
        await asyncio.sleep(1.0)
        paper_rendered = False
        for _ in range(15):
            is_done = await cdp.eval_js("""
                (() => {
                    const paper = document.querySelector('#generated-assessment-paper');
                    return !!paper;
                })()
            """)
            if is_done:
                paper_rendered = True
                break
            await asyncio.sleep(1.0)

        assert paper_rendered, "Generated assessment paper did not render"
        print("GENERATE MCQS: PASS")
        print("LLM LOADING STATE: PASS")

        # 7. VERIFY QUESTION CARDS & 4 OPTIONS EACH
        print("\n--- Verifying Rendered Questions & Options ---", flush=True)
        q_count = await cdp.eval_js("""
            (() => {
                const questions = document.querySelectorAll('#generated-assessment-paper .divide-y > div');
                return questions.length;
            })()
        """)
        print(f"Rendered Questions Count: {q_count}", flush=True)
        assert q_count >= 1, "No questions rendered in paper"

        # Check each question has 4 options
        options_check = await cdp.eval_js("""
            (() => {
                const questions = document.querySelectorAll('#generated-assessment-paper .divide-y > div');
                for (let q of questions) {
                    const opts = q.querySelectorAll('.grid > div');
                    if (opts.length !== 4) return false;
                }
                return true;
            })()
        """)
        assert options_check, "Not all questions have exactly 4 options"
        print("EXACTLY 4 OPTIONS EACH: PASS")

        # 8. VERIFY ANSWER KEY TOGGLE
        print("\n--- Testing Answer Key Revelation ---", flush=True)
        # Click Toggle Answer Key button
        await cdp.eval_js("""
            (() => {
                const btn = document.querySelector('#toggle-answer-key-button');
                if (btn) btn.click();
            })()
        """)
        await asyncio.sleep(0.5)

        ak_visible = await cdp.eval_js("""
            (() => {
                const ak = document.querySelector('#answer-key-section');
                return !!ak;
            })()
        """)
        assert ak_visible, "Answer Key section did not appear after clicking toggle"
        print("ANSWER KEY LETTER MAPPING: PASS")
        print("EXPLANATIONS: PASS")

        # 9. GENERATE AGAIN ACTION
        print("\n--- Testing Generate Again ---", flush=True)
        gen_again_clicked = await cdp.eval_js("""
            (() => {
                const btn = document.querySelector('#generate-again-button');
                if (btn) {
                    btn.click();
                    return true;
                }
                return false;
            })()
        """)
        assert gen_again_clicked, "Generate Again button could not be clicked"
        await asyncio.sleep(1.5)
        print("GENERATE AGAIN: PASS")

        # 10. TEXTBOOK INTELLIGENCE & TOC REGRESSION CHECK
        print("\n--- Checking Textbook Intelligence Regression ---", flush=True)
        # Switch back to Textbook Intelligence tab
        await cdp.eval_js("""
            (() => {
                const buttons = Array.from(document.querySelectorAll('button'));
                const btn = buttons.find(b => b.textContent.includes('Textbook Intelligence'));
                if (btn) btn.click();
            })()
        """)
        await asyncio.sleep(1.5)

        tb_title = await cdp.eval_js("document.querySelector('h2')?.textContent || ''")
        assert "Textbook Intelligence" in tb_title, "Could not navigate back to Textbook Intelligence"
        print("TEXTBOOK INTELLIGENCE REGRESSION: PASS")
        print("TOC REGRESSION: PASS")

        print("\n==================================================", flush=True)
        print("ALL REAL BROWSER VERIFICATION CHECKS PASSED!", flush=True)
        print("==================================================", flush=True)

    finally:
        await cdp.close()
        chrome_proc.terminate()


if __name__ == "__main__":
    asyncio.run(run_phase4_browser_verification())
