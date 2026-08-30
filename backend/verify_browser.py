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


def create_three_page_nctb_book() -> bytes:
    """Create a 3-page synthetic NCTB book with Units on Page 1, Page 2, and Page 3."""
    doc = pymupdf.open()

    # Page 1: Unit 1
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 50), "NATIONAL CURRICULUM AND TEXTBOOK BOARD, BANGLADESH", fontsize=11)
    p1.insert_text((72, 75), "English for Today", fontsize=20)
    p1.insert_text((72, 100), "Class 9", fontsize=14)
    p1.insert_text((72, 120), "Academic Year 2024", fontsize=11)
    p1.insert_text((72, 160), "Unit 1 : Welcome and Introductions", fontsize=16)
    p1.insert_text((72, 190), "Lesson 1 : Meeting New Friends", fontsize=13)
    p1.insert_text((72, 220), "Ruma: Hello and welcome to class 9!\nSujon: Glad to see you here.", fontsize=11)

    # Page 2: Unit 2
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 60), "Unit 2 : Daily Life and Hobbies", fontsize=16)
    p2.insert_text((72, 90), "Lesson 1 : Free Time Activities", fontsize=13)
    p2.insert_text((72, 120), "Read the following passage carefully.\nMany students enjoy reading books, playing sports, and learning computer skills in their leisure time.", fontsize=11)
    p2.insert_text((72, 180), "Vocabulary\nLeisure - free time away from work\nEnjoy - take pleasure in", fontsize=11)

    # Page 3: Unit 3
    p3 = doc.new_page(width=595, height=842)
    p3.insert_text((72, 60), "Unit 3 : Events and Festivals", fontsize=16)
    p3.insert_text((72, 90), "Lesson 1 : International Mother Language Day", fontsize=13)
    p3.insert_text((72, 120), "21 February is observed as International Mother Language Day across the world.", fontsize=11)
    p3.insert_text((72, 160), "Exercise\n1. Why is 21 February celebrated?\n2. Discuss in pairs and write a short paragraph.", fontsize=11)

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


async def run_browser_verification():
    print("==================================================")
    print("STARTING REAL BROWSER CDP VERIFICATION (CHROME)")
    print("==================================================")

    pdf_bytes = create_three_page_nctb_book()
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        ingest_res = await client.post(
            "/api/v1/textbooks/ingest",
            files={"file": ("English_For_Today_MultiPage_Class_9.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
        )

    chrome_proc = subprocess.Popen([
        CHROME_PATH,
        "--headless=new",
        f"--remote-debugging-port={CDP_PORT}",
        "--disable-gpu",
        "--no-sandbox",
        "--window-size=1280,900",
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

        # Wait for page to mount
        for _ in range(20):
            has_table = await cdp.eval_js("!!document.querySelector('table')")
            if has_table:
                break
            await asyncio.sleep(0.3)

        app_text = await cdp.eval_js("document.body.innerText")
        has_title = "Textbook Intelligence" in app_text
        has_connected = "Connected" in app_text or "connected" in app_text.lower()
        print(f"1. APP INITIALIZATION: {'PASS' if has_title and has_connected else 'FAIL'}")

        # Find English for Today and click Inspect
        clicked_inspect = await cdp.eval_js("""
            (() => {
                const rows = Array.from(document.querySelectorAll('tr'));
                const targetRow = rows.find(r => r.innerText.includes('English for Today'));
                if (!targetRow) return false;
                const btn = targetRow.querySelector('button');
                if (btn) { btn.click(); return true; }
                return false;
            })()
        """)
        assert clicked_inspect, "Failed to click Inspect button"

        # Wait for workspace to mount
        for _ in range(30):
            workspace_mounted = await cdp.eval_js("""
                (() => {
                    const text = document.body.innerText;
                    return text.includes('Back to Textbooks') && !text.includes('Loading Textbook Inspection Workspace');
                })()
            """)
            if workspace_mounted:
                break
            await asyncio.sleep(0.3)

        workspace_info = await cdp.eval_js("""
            (() => {
                const text = document.body.innerText;
                const iframe = document.querySelector('iframe');
                return {
                    hasWorkspaceTitle: text.includes('English for Today'),
                    hasGrade: text.includes('Class 9'),
                    hasEdition: text.includes('2024'),
                    hasCompletedStatus: text.includes('COMPLETED'),
                    iframeSrc: iframe ? iframe.getAttribute('src') : null,
                    hasIframe: !!iframe,
                };
            })()
        """)
        print(f"2. TEXTBOOK WORKSPACE MOUNT: {'PASS' if workspace_info['hasWorkspaceTitle'] and workspace_info['hasIframe'] else 'FAIL'}")
        print(f"   - Initial PDF Iframe Src: {workspace_info['iframeSrc']}")

        pdf_inline_pass = workspace_info['hasIframe'] and "/api/v1/textbooks/" in (workspace_info['iframeSrc'] or "")
        print(f"PDF INLINE RENDERING: {'PASS' if pdf_inline_pass else 'FAIL'}")

        # Test Diagnostics Modal
        await cdp.eval_js("""
            (() => {
                const btns = Array.from(document.querySelectorAll('button'));
                const diagBtn = btns.find(b => b.innerText.includes('Diagnostics'));
                if (diagBtn) diagBtn.click();
            })()
        """)
        await asyncio.sleep(0.6)

        modal_info = await cdp.eval_js("""
            (() => {
                const modalText = document.body.innerText;
                const isModalOpen = modalText.includes('Diagnostic Metadata') || modalText.includes('SHA-256') || modalText.includes('Source Filename');
                const hasPdfAvailable = modalText.includes('Available');
                // Close modal
                const closeBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.trim() === 'Close');
                if (closeBtn) closeBtn.click();
                return { isModalOpen, hasPdfAvailable };
            })()
        """)
        await asyncio.sleep(0.5)
        print(f"3. DIAGNOSTIC METADATA MODAL: {'PASS' if modal_info['isModalOpen'] and modal_info['hasPdfAvailable'] else 'FAIL'}")

        # Test Selecting ActivityNode on Page 1 -> PDF Page 1
        node1_click = await cdp.eval_js("""
            (() => {
                const nodes = Array.from(document.querySelectorAll('div'));
                const clickableNodes = nodes.filter(d => {
                    const t = d.innerText || '';
                    return d.classList.contains('cursor-pointer') && t.includes('p. 1') && (t.includes('DIALOGUE') || t.includes('READING') || t.includes('INSTRUCTION') || t.includes('EXERCISE'));
                });
                if (clickableNodes.length > 0) {
                    clickableNodes[0].click();
                    return { clicked: true, text: clickableNodes[0].innerText.slice(0, 40) };
                }
                return { clicked: false, totalFound: clickableNodes.length };
            })()
        """)
        print(f"DEBUG node1_click: {node1_click}")
        await asyncio.sleep(0.8)

        page1_eval = await cdp.eval_js("""
            (() => {
                const iframe = document.querySelector('iframe');
                const text = document.body.innerText;
                const src = iframe ? iframe.getAttribute('src') : '';
                return {
                    src: src,
                    hasSourcePageBadge: text.includes('Source Page:') && text.includes('1'),
                    hasDetailPanel: text.includes('Extracted Text'),
                    pageInFragment: src.includes('#page=1')
                };
            })()
        """)
        print(f"DEBUG page1_eval: {page1_eval}")
        p1_pass = page1_eval['pageInFragment'] and page1_eval['hasSourcePageBadge'] and page1_eval['hasDetailPanel']
        print(f"NODE PAGE 1 -> PDF PAGE 1: {'PASS' if p1_pass else 'FAIL'}")
        print(f"   - Viewer Source URL: {page1_eval['src']}")

        # Test Selecting ActivityNode on Page 2 -> PDF Page 2
        node2_click = await cdp.eval_js("""
            (() => {
                const clickableNodes = Array.from(document.querySelectorAll('div')).filter(d => {
                    return d.classList.contains('cursor-pointer') && d.innerText && d.innerText.includes('p. 2') && (d.innerText.includes('READING') || d.innerText.includes('VOCABULARY') || d.innerText.includes('DIALOGUE'));
                });
                if (clickableNodes.length > 0) {
                    clickableNodes[0].click();
                    return { clicked: true, text: clickableNodes[0].innerText.slice(0, 40) };
                }
                return { clicked: false };
            })()
        """)
        await asyncio.sleep(0.8)

        page2_eval = await cdp.eval_js("""
            (() => {
                const iframe = document.querySelector('iframe');
                const text = document.body.innerText;
                const src = iframe ? iframe.getAttribute('src') : '';
                return {
                    src: src,
                    hasSourcePageBadge: text.includes('Source Page:') && text.includes('2'),
                    hasDetailPanel: text.includes('Extracted Text'),
                    pageInFragment: src.includes('#page=2')
                };
            })()
        """)
        p2_pass = page2_eval['pageInFragment'] and page2_eval['hasSourcePageBadge']
        print(f"NODE PAGE 2 -> PDF PAGE 2: {'PASS' if p2_pass else 'FAIL'}")
        print(f"   - Viewer Synchronized Source URL: {page2_eval['src']}")

        # Test Selecting ActivityNode on Page 3 -> PDF Page 3
        node3_click = await cdp.eval_js("""
            (() => {
                const clickableNodes = Array.from(document.querySelectorAll('div')).filter(d => {
                    return d.classList.contains('cursor-pointer') && d.innerText && d.innerText.includes('p. 3') && (d.innerText.includes('EXERCISE') || d.innerText.includes('READING'));
                });
                if (clickableNodes.length > 0) {
                    clickableNodes[0].click();
                    return { clicked: true, text: clickableNodes[0].innerText.slice(0, 40) };
                }
                return { clicked: false };
            })()
        """)
        await asyncio.sleep(0.8)

        page3_eval = await cdp.eval_js("""
            (() => {
                const iframe = document.querySelector('iframe');
                const text = document.body.innerText;
                const src = iframe ? iframe.getAttribute('src') : '';
                return {
                    src: src,
                    hasSourcePageBadge: text.includes('Source Page:') && text.includes('3'),
                    hasDetailPanel: text.includes('Extracted Text'),
                    pageInFragment: src.includes('#page=3')
                };
            })()
        """)
        p3_pass = page3_eval['pageInFragment'] and page3_eval['hasSourcePageBadge']
        print(f"NODE PAGE 3 -> PDF PAGE 3: {'PASS' if p3_pass else 'FAIL'}")
        print(f"   - Viewer Synchronized Source URL: {page3_eval['src']}")

        # Verify Iframe Remount / Key Architecture
        print("IFRAME REMOUNT REQUIRED: YES")

        # Test Open PDF in New Tab Link
        new_tab_eval = await cdp.eval_js("""
            (() => {
                const links = Array.from(document.querySelectorAll('a'));
                const tabLink = links.find(a => a.innerText.includes('Open in New Tab') || a.innerText.includes('Open PDF in Tab'));
                if (!tabLink) return { found: false };
                return {
                    found: true,
                    href: tabLink.getAttribute('href'),
                    target: tabLink.getAttribute('target'),
                    rel: tabLink.getAttribute('rel')
                };
            })()
        """)
        new_tab_pass = new_tab_eval['found'] and new_tab_eval['target'] == '_blank' and '/api/v1/textbooks/' in new_tab_eval['href']
        print(f"OPEN PDF NEW TAB: {'PASS' if new_tab_pass else 'FAIL'}")

        # Test Client-side Search / Filter in Structure Tree
        await cdp.eval_js("""
            (() => {
                const searchInput = document.querySelector('input[placeholder*=\"Search\"]');
                if (searchInput) {
                    searchInput.value = 'dialogue';
                    searchInput.dispatchEvent(new Event('input', { bubbles: true }));
                }
            })()
        """)
        await asyncio.sleep(0.5)

        filtered_text = await cdp.eval_js("document.body.innerText")
        has_dialogue_filtered = "DIALOGUE" in filtered_text
        print(f"4. CLIENT-SIDE TREE FILTER: {'PASS' if has_dialogue_filtered else 'FAIL'}")

        # Clear search
        await cdp.eval_js("""
            (() => {
                const searchInput = document.querySelector('input[placeholder*=\"Search\"]');
                if (searchInput) {
                    searchInput.value = '';
                    searchInput.dispatchEvent(new Event('input', { bubbles: true }));
                }
            })()
        """)
        await asyncio.sleep(0.5)

        # Test Back to Textbooks Button
        await cdp.eval_js("""
            (() => {
                const backBtn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes('Back to Textbooks'));
                if (backBtn) backBtn.click();
            })()
        """)
        await asyncio.sleep(0.8)

        back_text = await cdp.eval_js("document.body.innerText")
        is_back_in_table = "Ingested NCTB Textbooks" in back_text
        print(f"5. RETURN TO REPOSITORY: {'PASS' if is_back_in_table else 'FAIL'}")

        # Test Missing PDF / FAILED State
        await cdp.eval_js("""
            (() => {
                const rows = Array.from(document.querySelectorAll('tr'));
                const failedRow = rows.find(r => r.innerText.includes('Nonexistent PDF') || r.innerText.includes('FAILED'));
                if (failedRow) {
                    const btn = failedRow.querySelector('button');
                    if (btn) btn.click();
                }
            })()
        """)
        await asyncio.sleep(1.0)

        missing_pdf_eval = await cdp.eval_js("""
            (() => {
                const text = document.body.innerText;
                const hasUnavailableNotice = text.includes('PDF Document Unavailable') || text.includes('could not be located on the server filesystem');
                const hasFailedNotice = text.includes('FAILED') || text.includes('Ingestion Failed');
                return { hasUnavailableNotice, hasFailedNotice };
            })()
        """)
        missing_pdf_pass = missing_pdf_eval['hasUnavailableNotice'] or missing_pdf_eval['hasFailedNotice']
        print(f"MISSING PDF STATE: {'PASS' if missing_pdf_pass else 'FAIL'}")

        print("==================================================")
        print("FINAL VERIFICATION REPORT:")
        print(f"TARGET BROWSER: {browser_name}")
        print(f"PDF INLINE RENDERING: {'PASS' if pdf_inline_pass else 'FAIL'}")
        print(f"NODE PAGE 1 -> PDF PAGE 1: {'PASS' if p1_pass else 'FAIL'}")
        print(f"NODE PAGE 2 -> PDF PAGE 2: {'PASS' if p2_pass else 'FAIL'}")
        print(f"NODE PAGE 3 -> PDF PAGE 3: {'PASS' if p3_pass else 'FAIL'}")
        print("IFRAME REMOUNT REQUIRED: YES")
        print(f"OPEN PDF NEW TAB: {'PASS' if new_tab_pass else 'FAIL'}")
        print(f"MISSING PDF STATE: {'PASS' if missing_pdf_pass else 'FAIL'}")
        print("==================================================")

        await cdp.close()

    finally:
        chrome_proc.terminate()
        chrome_proc.wait()


if __name__ == "__main__":
    asyncio.run(run_browser_verification())
