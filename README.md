# NCTB Intelligence & Assessment Demo — Phase 3.5 Active

A standalone Bangladesh/NCTB-focused textbook intelligence, student-friendly readable textbook reconstruction, raw PDF viewer, and dynamic assessment generation platform, designed for clean independent operation and seamless institutional LMS integration.

---

## 1. Project Purpose

This project provides an intelligent curriculum analysis and textbook reconstruction suite tailored specifically for Bangladesh National Curriculum and Textbook Board (NCTB) textbooks. It transforms raw, fragmented textbook PDF extractions into continuous, student-friendly readable textbook documents (with typography, KaTeX math formulas, geometric tables, and pedagogical callouts) while maintaining 100% provenance back to the original PDF pages.

---

## 2. Implemented Capabilities (Phase 3.5 Status)

### Implemented & Verified in Phase 3.5
* **Student-Friendly Textbook Reconstruction Engine (`ReconstructionEngine`)**:
  - Reconstructs fragmented PDF text blocks into continuous, legible textbook chapters, sections, and paragraphs.
  - Dynamically extracts raw-PDF span geometry (baselines, font sizes, font flags, vector drawings) from stored original PDFs for exact layout authority.
  - Generates semantic blocks: `heading` ($h_1, h_2, h_3$), `paragraph`, `example` (worked solutions), `activity` (pair work/tasks), `exercise` (practice sets), `table`, `list`, `math_display`, `definition`, and `note`.
* **Configurable Reconstruction Rules (`backend/config/reconstruction_rules.json`)**:
  - Centralized heuristic thresholds: paragraph alignment tolerance, line gap ratios, heading font ratios, superscript/subscript ratios, baseline displacement offsets, table column cluster tolerances, and header/footer exclusion ratios.
  - Centralized pedagogical semantic markers: Example, Solution, Activity, Work in pairs, Look at the picture, Exercise, Questions and Exercises.
* **Conservative Geometry-Driven Math & Formula Reconstruction (`MathNormalizer`)**:
  - Exponents and superscripts ($x^2, a^n, (807)^2$) produced only with physical baseline offset and font-size reduction proof.
  - Raw math formulas preserved without blind textual guessing or prose-to-equation rewriting.
* **High-Confidence Geometric Table Detection (`TableDetector`)**:
  - Distinguishes genuine tables from casual 2-line alignment using column cluster density and vector ruling lines.
* **In-Memory Cached Header/Footer Removal (`HeaderFooterFilter`)**:
  - Version-level bounded pattern detection with in-memory caching to eliminate redundant page scans.
* **Bounded Scope Resolution (`GET /api/v1/textbooks/{version_id}/readable`)**:
  - Enforces bounded scope (`lesson_id`, `unit_id`, or `page`).
  - Deterministically resolves nullable `lesson.end_page` and `unit.end_page`.
* **Degraded AST Fallback**:
  - If the original PDF is missing, safely falls back to persisted `ActivityNode` records with `RAW_PDF_LAYOUT_UNAVAILABLE` warning.
* **Student-Friendly Educational Viewer (`ReadableDocumentViewer`)**:
  - Clean institutional reading surface with typographic hierarchy, styled callout boxes, semantic HTML tables, and KaTeX mathematics.
  - Interactive block selection and source-page jumping (`p. N`).
* **Balanced ~50%/50% Desktop Workspace (`TextbookWorkspace`)**:
  - Mode Switcher: `[ 📖 Readable Content ]` (Default) | `[ 🔍 Parsed Structure ]` (Technical AST).
  - Synchronized raw PDF viewer on desktop.
* **Automated & Real Browser Verification**:
  - 46 passing backend pytest tests (100% pass).
  - Full TypeScript / Vite production bundle (`npm run build`).
  - Chrome / Chromium CDP end-to-end browser verification verified.

### Not Implemented Yet (Phase 4+ Scope)
* Assessment Generator blueprint configuration & question generation
* Mathematics templates & questions
* SVG question diagrams
* Question Bank & Question Set persistence
* Vector database / Embeddings / RAG
* Full-text search / FTS backend
* Authentication & RBAC

---

## 3. Supported Initial Scope & Zero-Hardcoding Principle

Initial content scope:
* **English for Today**
* **English Grammar and Composition**
* **Mathematics**

> **Zero-Hardcoding Principle**: The architecture is fully data- and capability-driven. No textbook IDs, database keys, page mappings, or subject-specific viewer rules are hardcoded. All reconstruction thresholds and pedagogical markers are configured via `backend/config/reconstruction_rules.json`.

---

## 4. Phase 3.5 Browser Verification Status

```text
TARGET BROWSER: Google Chrome 151.0
READABLE CONTENT MODE (DEFAULT): PASS
PARSED STRUCTURE MODE PRESERVED: PASS
TAB SWITCHING: PASS
50/50 BALANCED DESKTOP LAYOUT: PASS
PARAGRAPH CONTINUITY: PASS
HEADING HIERARCHY (H1/H2/H3): PASS
MATH SUPERSCRIPT RENDERING (KATEX): PASS
ROOT SYMBOL RENDERING: PASS
TABLE RENDERING: PASS
LIST RENDERING: PASS
READABLE BLOCK -> PDF SOURCE PAGE: PASS
PDF VIEWER STILL WORKS: PASS
```

---

## 5. Setup & Execution Instructions

### Prerequisites
* Windows 10/11 (with English OCR language pack for Windows Media OCR)
* Python 3.11+
* Node.js v18+ & npm

### Backend Setup

1. **Navigate to backend directory**:
   ```bash
   cd backend
   ```

2. **Create and activate virtual environment**:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run backend automated tests (isolated test DB)**:
   ```bash
   pytest
   ```

5. **Start backend server**:
   ```bash
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

### Frontend Setup

1. **Navigate to frontend directory**:
   ```bash
   cd frontend
   ```

2. **Install dependencies**:
   ```bash
   npm install
   ```

3. **Verify production build**:
   ```bash
   npm run build
   ```

4. **Start Vite development server**:
   ```bash
   npm run dev
   ```

5. **Open in browser**:
   `http://localhost:5173`
