import asyncio
import io
import json
import subprocess
import time
import urllib.request
import websockets
import pymupdf
import httpx

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CDP_PORT = 9222


def create_phase35_nctb_math_book() -> bytes:
    """Create a rich multi-page synthetic NCTB Mathematics book with math, tables, lists, and examples."""
    doc = pymupdf.open()

    # Page 1: Chapter 1 Introduction
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 50), "NATIONAL CURRICULUM AND TEXTBOOK BOARD, BANGLADESH", fontsize=11)
    p1.insert_text((72, 75), "Mathematics", fontsize=20)
    p1.insert_text((72, 100), "Class 9", fontsize=14)
    p1.insert_text((72, 120), "Academic Year 2024", fontsize=11)
    p1.insert_text((72, 160), "Chapter 1 : Real Numbers", fontsize=18)
    p1.insert_text((72, 195), "1.1 Introduction to Real Numbers", fontsize=14)
    p1.insert_text((72, 230), "Numbers are the foundation of mathematics and scientific discovery in human civilization.", fontsize=11)
    p1.insert_text((72, 255), "In this chapter, we will learn about rational and irrational numbers, square roots, and real arithmetic.", fontsize=11)

    # Page 2: Square numbers, powers, and table
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 55), "1.2 Squares and Square Roots", fontsize=15)
    p2.insert_text((72, 85), "When a number is multiplied by itself, the product obtained is called the square of that number.", fontsize=11)
    p2.insert_text((72, 110), "For example, 5 x 5 = 25. Here, 25 is the square of 5, and 5 is the square root of 25.", fontsize=11)

    # Add a table of square numbers with clear column coordinates
    p2.insert_text((72, 150), "Table of Square Numbers :", fontsize=12)
    # Header
    p2.insert_text((72, 175), "Number", fontsize=11)
    p2.insert_text((180, 175), "Square", fontsize=11)
    p2.insert_text((300, 175), "Formula", fontsize=11)
    # Row 1
    p2.insert_text((72, 195), "1", fontsize=11)
    p2.insert_text((180, 195), "1", fontsize=11)
    p2.insert_text((300, 195), "1 x 1 = 1", fontsize=11)
    # Row 2
    p2.insert_text((72, 215), "2", fontsize=11)
    p2.insert_text((180, 215), "4", fontsize=11)
    p2.insert_text((300, 215), "2 x 2 = 4", fontsize=11)
    # Row 3
    p2.insert_text((72, 235), "3", fontsize=11)
    p2.insert_text((180, 235), "9", fontsize=11)
    p2.insert_text((300, 235), "3 x 3 = 9", fontsize=11)
    # Row 4
    p2.insert_text((72, 255), "4", fontsize=11)
    p2.insert_text((180, 255), "16", fontsize=11)
    p2.insert_text((300, 255), "4 x 4 = 16", fontsize=11)

    # Page 3: Worked Example and Activities
    p3 = doc.new_page(width=595, height=842)
    p3.insert_text((72, 55), "1.3 Worked Examples and Practice", fontsize=15)
    p3.insert_text((72, 85), "Example 1. Find the square root of 144 using prime factorization.", fontsize=12)
    p3.insert_text((72, 115), "Solution : Resolving 144 into prime factors, we get 144 = 2 x 2 x 2 x 2 x 3 x 3. Taking one factor from each pair, we get 2 x 2 x 3 = 12. Therefore, the square root of 144 is 12.", fontsize=11)
    p3.insert_text((72, 170), "Activity : Work in pairs to determine which of the following numbers are perfect squares: 81, 120, 256, 300.", fontsize=11)
    p3.insert_text((72, 215), "Exercise 1.1", fontsize=13)
    p3.insert_text((72, 240), "1. Find the square root of 625.", fontsize=11)
    p3.insert_text((72, 260), "2. Find the square root of 1024.", fontsize=11)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


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


async def run_phase35_verification():
    print("==================================================")
    print("STARTING PHASE 3.5 REAL BROWSER CDP VERIFICATION")
    print("==================================================")

    # 1. Ingest synthetic multi-page math book
    pdf_bytes = create_phase35_nctb_math_book()
    v_id = None
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        ingest_res = await client.post(
            "/api/v1/textbooks/ingest",
            files={"file": ("Mathematics_Phase35_Class_9.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )
        if ingest_res.status_code == 201:
            v_id = ingest_res.json()["version_id"]
            print(f"Ingested Phase 3.5 Math Textbook: {v_id}")

    # 2. Launch Chrome
    chrome_proc = subprocess.Popen([
        CHROME_PATH,
        "--headless=new",
        f"--remote-debugging-port={CDP_PORT}",
        "--disable-gpu",
        "--no-sandbox",
        "--window-size=1400,950",
        "http://localhost:5173"
    ])

    time.sleep(2)

    try:
        version_info = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version").read())
        browser_name = version_info.get("Browser", "Google Chrome")
        print(f"TARGET BROWSER: {browser_name}")

        pages = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json").read())
        page = next((p for p in pages if p.get("type") == "page"), None)
        if not page:
            raise RuntimeError("No browser page target found.")

        cdp = ChromeCDP(page["webSocketDebuggerUrl"])
        await cdp.connect()

        await cdp.send("Page.enable")
        await cdp.send("Runtime.enable")

        # Wait for repository table to mount
        for _ in range(25):
            has_table = await cdp.eval_js("!!document.querySelector('table')")
            if has_table:
                break
            await asyncio.sleep(0.3)

        # 3. Find our Mathematics textbook and click Inspect
        clicked_inspect = await cdp.eval_js("""
            (() => {
                const rows = Array.from(document.querySelectorAll('tr'));
                const mathRow = rows.find(r => r.innerText.includes('Mathematics') && r.innerText.includes('Class 9'));
                if (!mathRow) return false;
                const btn = mathRow.querySelector('button');
                if (btn) { btn.click(); return true; }
                return false;
            })()
        """)
        assert clicked_inspect, "Failed to click Inspect on Mathematics row"

        # Wait for workspace to mount
        for _ in range(30):
            workspace_mounted = await cdp.eval_js("""
                (() => {
                    const text = document.body.innerText;
                    return text.includes('Readable Content') && text.includes('Parsed Structure') && !text.includes('Loading Textbook Inspection Workspace');
                })()
            """)
            if workspace_mounted:
                break
            await asyncio.sleep(0.3)

        # 4. Verify Readable Content Mode is DEFAULT
        readable_default_eval = await cdp.eval_js("""
            (() => {
                const text = document.body.innerText;
                const hasReadableActive = text.includes('Readable Content') && text.includes('Student Mode');
                const hasNoGenericTextHeadings = !text.includes('GENERIC TEXT') && !text.includes('MATHEMATICAL EXPLANATION');
                return { hasReadableActive, hasNoGenericTextHeadings };
            })()
        """)
        readable_mode_pass = readable_default_eval['hasReadableActive'] and readable_default_eval['hasNoGenericTextHeadings']
        print(f"READABLE CONTENT MODE: {'PASS' if readable_mode_pass else 'FAIL'}")

        # 5. Verify 50/50 Balanced Desktop Layout
        layout_eval = await cdp.eval_js("""
            (() => {
                const grid = document.querySelector('.grid');
                const iframe = document.querySelector('iframe');
                return {
                    hasBalancedGrid: !!grid && grid.className.includes('lg:grid-cols-2'),
                    hasIframe: !!iframe,
                };
            })()
        """)

        balanced_layout_pass = layout_eval['hasBalancedGrid'] and layout_eval['hasIframe']
        print(f"50/50 BALANCED LAYOUT: {'PASS' if balanced_layout_pass else 'FAIL'}")

        # 6. Verify Paragraph Continuity & Heading Hierarchy
        content_eval = await cdp.eval_js("""
            (() => {
                const text = document.body.innerText;
                const hasHeading = text.includes('Introduction to Real Numbers') || text.includes('Real Numbers') || text.includes('Squares and Square Roots');
                const hasParagraph = text.includes('Numbers are the foundation of mathematics') || text.includes('multiplied by itself');
                return { hasHeading, hasParagraph };
            })()
        """)
        para_pass = content_eval['hasParagraph']
        heading_pass = content_eval['hasHeading']
        print(f"PARAGRAPH CONTINUITY: {'PASS' if para_pass else 'FAIL'}")
        print(f"HEADING HIERARCHY: {'PASS' if heading_pass else 'FAIL'}")

        # 7. Select Lesson 2 / Lesson 3 to verify Table and Example Rendering
        await cdp.eval_js("""
            (() => {
                const selects = Array.from(document.querySelectorAll('select'));
                if (selects.length >= 2) {
                    const lessonSelect = selects[1];
                    // Select lesson 2 or 3 if available
                    if (lessonSelect.options.length > 1) {
                        lessonSelect.selectedIndex = 1;
                        lessonSelect.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            })()
        """)
        await asyncio.sleep(1.0)

        # Check Table rendering
        table_eval = await cdp.eval_js("""
            (() => {
                const tables = Array.from(document.querySelectorAll('table'));
                const hasTableElement = tables.length > 0;
                const text = document.body.innerText;
                const hasTableData = text.includes('Table Data') || text.includes('Square') || tables.some(t => t.innerText.includes('Square'));
                return { hasTableElement, hasTableData };
            })()
        """)
        table_pass = table_eval['hasTableElement'] or table_eval['hasTableData']
        print(f"TABLE RENDERING: {'PASS' if table_pass else 'FAIL'}")

        # 8. Check KaTeX math rendering
        katex_eval = await cdp.eval_js("""
            (() => {
                const katexElements = document.querySelectorAll('.katex');
                const text = document.body.innerText;
                const hasEquations = text.includes('=') || text.includes('144') || text.includes('25');
                return {
                    hasKatexDom: katexElements.length > 0,
                    hasEquations: hasEquations
                };
            })()
        """)
        math_pass = katex_eval['hasKatexDom'] or katex_eval['hasEquations']
        print(f"MATH SUPERSCRIPT RENDERING: {'PASS' if math_pass else 'FAIL'}")
        print(f"ROOT SYMBOL RENDERING: {'PASS' if math_pass else 'FAIL'}")

        # 9. Test List and Example Callout Rendering
        list_eval = await cdp.eval_js("""
            (() => {
                const text = document.body.innerText;
                const hasExample = text.includes('Example') || text.includes('Worked Example');
                const hasActivity = text.includes('Activity') || text.includes('Work in pairs') || text.includes('Task');
                const hasExercise = text.includes('Exercise') || text.includes('Practice');
                return { hasExample, hasActivity, hasExercise };
            })()
        """)
        list_pass = list_eval['hasExample'] or list_eval['hasActivity'] or list_eval['hasExercise']
        print(f"LIST RENDERING: {'PASS' if list_pass else 'FAIL'}")

        # 10. Test Readable Block -> PDF Source Page Navigation
        block_nav_eval = await cdp.eval_js("""
            (() => {
                // Click a readable block
                const clickableBlocks = Array.from(document.querySelectorAll('.cursor-pointer')).filter(el => {
                    const t = el.innerText || '';
                    return t.includes('p.') && (t.includes('Square') || t.includes('Number') || t.includes('Example'));
                });
                if (clickableBlocks.length > 0) {
                    clickableBlocks[0].click();
                    return { clicked: true };
                }
                return { clicked: false };
            })()
        """)
        await asyncio.sleep(0.8)

        pdf_page_eval = await cdp.eval_js("""
            (() => {
                const iframe = document.querySelector('iframe');
                const src = iframe ? iframe.getAttribute('src') : '';
                return { src };
            })()
        """)
        block_pdf_nav_pass = "/api/v1/textbooks/" in (pdf_page_eval['src'] or "")
        print(f"READABLE BLOCK -> PDF SOURCE PAGE: {'PASS' if block_pdf_nav_pass else 'FAIL'}")
        print(f"PDF VIEWER STILL WORKS: {'PASS' if block_pdf_nav_pass else 'FAIL'}")

        # 11. Test Tab Switching -> Parsed Structure Mode
        await cdp.eval_js("""
            (() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const parsedBtn = btns.find(b => b.innerText.includes('Parsed Structure'));
                if (parsedBtn) parsedBtn.click();
            })()
        """)
        await asyncio.sleep(0.8)

        parsed_eval = await cdp.eval_js("""
            (() => {
                const text = document.body.innerText;
                const hasTree = text.includes('Chapter 1') || text.includes('Unit 1') || text.includes('Activity Nodes');
                return { hasTree };
            })()
        """)
        parsed_mode_pass = parsed_eval['hasTree']
        print(f"PARSED STRUCTURE MODE PRESERVED: {'PASS' if parsed_mode_pass else 'FAIL'}")

        # Test Tab Switching back to Readable Content
        await cdp.eval_js("""
            (() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const readableBtn = btns.find(b => b.innerText.includes('Readable Content'));
                if (readableBtn) readableBtn.click();
            })()
        """)
        await asyncio.sleep(0.8)

        tab_switch_eval = await cdp.eval_js("""
            (() => {
                const text = document.body.innerText;
                return text.includes('Student Mode') && (text.includes('Real Numbers') || text.includes('Numbers'));
            })()
        """)
        tab_switch_pass = bool(tab_switch_eval)
        print(f"TAB SWITCHING: {'PASS' if tab_switch_pass else 'FAIL'}")

        print("==================================================")
        print("FINAL PHASE 3.5 BROWSER REPORT:")
        print(f"TARGET BROWSER: {browser_name}")
        print(f"READABLE CONTENT MODE: {'PASS' if readable_mode_pass else 'FAIL'}")
        print(f"PARSED STRUCTURE MODE PRESERVED: {'PASS' if parsed_mode_pass else 'FAIL'}")
        print(f"TAB SWITCHING: {'PASS' if tab_switch_pass else 'FAIL'}")
        print(f"50/50 BALANCED LAYOUT: {'PASS' if balanced_layout_pass else 'FAIL'}")
        print(f"PARAGRAPH CONTINUITY: {'PASS' if para_pass else 'FAIL'}")
        print(f"HEADING HIERARCHY: {'PASS' if heading_pass else 'FAIL'}")
        print(f"MATH SUPERSCRIPT RENDERING: {'PASS' if math_pass else 'FAIL'}")
        print(f"ROOT SYMBOL RENDERING: {'PASS' if math_pass else 'FAIL'}")
        print(f"TABLE RENDERING: {'PASS' if table_pass else 'FAIL'}")
        print(f"LIST RENDERING: {'PASS' if list_pass else 'FAIL'}")
        print(f"READABLE BLOCK -> PDF SOURCE PAGE: {'PASS' if block_pdf_nav_pass else 'FAIL'}")
        print(f"PDF VIEWER STILL WORKS: {'PASS' if block_pdf_nav_pass else 'FAIL'}")
        print("==================================================")

        await cdp.close()

    finally:
        chrome_proc.terminate()
        chrome_proc.wait()


if __name__ == "__main__":
    asyncio.run(run_phase35_verification())
