import io
import json
import sys
from pathlib import Path
import httpx

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tests.utils import (
    create_synthetic_english_today_pdf,
    create_synthetic_english_grammar_pdf,
    create_synthetic_mathematics_pdf,
)

BASE_URL = "http://127.0.0.1:8000"


def run_full_api_verification():
    client = httpx.Client(base_url=BASE_URL, timeout=30.0)

    print("=================================================================")
    print("      PHASE 2 REAL RUNNING HTTP API VERIFICATION SUITE")
    print("=================================================================\n")

    # 1. Health check
    print("1. Testing GET /api/v1/health...")
    health_res = client.get("/api/v1/health")
    print(f"Status: {health_res.status_code}")
    print(f"Response: {health_res.json()}\n")
    assert health_res.status_code == 200
    assert health_res.json()["status"] == "ok"
    assert health_res.json()["database"] == "ok"

    # 2. Ingest 3 Separate Synthetic PDFs
    fixtures = [
        ("English for Today (Class 9)", "English_For_Today_Class_9.pdf", create_synthetic_english_today_pdf()),
        ("English Grammar and Composition (Class 9)", "English_Grammar_Class_9.pdf", create_synthetic_english_grammar_pdf()),
        ("Mathematics (Class 9)", "Mathematics_Class_9.pdf", create_synthetic_mathematics_pdf()),
    ]

    ingestion_results = []

    for title, filename, pdf_bytes in fixtures:
        print(f"2. Ingesting fixture: '{title}' ({filename}, {len(pdf_bytes)} bytes)...")
        files = {"file": (filename, io.BytesIO(pdf_bytes), "application/pdf")}
        res = client.post("/api/v1/textbooks/ingest", files=files)
        print(f"HTTP Status: {res.status_code}")
        assert res.status_code == 201, res.text
        data = res.json()
        print(f"Ingested Version ID: {data['version_id']}")
        print(f"Detected Title: {data['title']}")
        print(f"Detected Grade: {data['detected_grade']}")
        print(f"Detected Subject: {data['detected_subject']}")
        print(f"Detected Domain: {data['detected_domain']}")
        print(f"Page Count: {data['page_count']}")
        print(f"Unit Count: {data['unit_count']}")
        print(f"Lesson Count: {data['lesson_count']}")
        print(f"Activity Nodes: {data['activity_node_count']}")
        print(f"OCR Pages: {data['ocr_pages_count']}")
        print(f"Status: {data['ingestion_status']}")
        print(f"Warnings: {data['warnings']}\n")
        ingestion_results.append(data)

    # 3. Verify GET /api/v1/textbooks/versions
    print("3. Testing GET /api/v1/textbooks/versions...")
    versions_res = client.get("/api/v1/textbooks/versions")
    assert versions_res.status_code == 200
    versions_data = versions_res.json()
    print(f"Total Ingested Versions in SQLite: {len(versions_data)}")
    for v in versions_data:
        print(f" - [{v['id']}] {v['title']} | Grade: {v['grade']} | Subject: {v['subject']} | Domain: {v['domain']} | Pages: {v['page_count']} | Status: {v['ingestion_status']}")
    print()
    assert len(versions_data) == 3

    # 4. Verify GET /api/v1/textbooks/{version_id}/tree for each
    print("4. Testing GET /api/v1/textbooks/{version_id}/tree for all 3...")
    first_node_ref = None
    for item in ingestion_results:
        vid = item["version_id"]
        tree_res = client.get(f"/api/v1/textbooks/{vid}/tree")
        assert tree_res.status_code == 200
        tree = tree_res.json()
        print(f"Tree for '{tree['title']}' ({vid}):")
        print(f"  Domain: {tree['domain']}, Units: {len(tree['units'])}")
        for u in tree["units"]:
            print(f"   * Unit {u['detected_number']}: {u['title']} (p. {u['start_page']}-{u['end_page']}) | Lessons: {len(u['lessons'])}, Direct Nodes: {len(u['direct_activity_nodes'])}")
            for l in u["lessons"]:
                print(f"     - Lesson {l['detected_number']}: {l['title']} (p. {l['start_page']}) | Nodes: {len(l['activity_nodes'])}")
                for node in l["activity_nodes"]:
                    if first_node_ref is None:
                        first_node_ref = (vid, node["id"])
                    print(f"       + [{node['node_type']}] p.{node['page_number']}: {node['content_preview'][:40]}... (hash: {node['content_hash'][:8]}...)")
            for node in u["direct_activity_nodes"]:
                if first_node_ref is None:
                    first_node_ref = (vid, node["id"])
                print(f"     + Direct Node [{node['node_type']}] p.{node['page_number']}: {node['content_preview'][:40]}...")
    print()

    # 5. Fetch Full ActivityNode via GET /api/v1/textbooks/{version_id}/nodes/{node_id}
    print("5. Testing GET /api/v1/textbooks/{version_id}/nodes/{node_id}...")
    assert first_node_ref is not None
    test_vid, test_nid = first_node_ref
    node_res = client.get(f"/api/v1/textbooks/{test_vid}/nodes/{test_nid}")
    assert node_res.status_code == 200
    node_data = node_res.json()
    print(f"Retrieved Node #{test_nid} for Version {test_vid}:")
    print(f"  Type: {node_data['node_type']}")
    print(f"  Title: {node_data['title']}")
    print(f"  Page: {node_data['page_number']}")
    print(f"  Bounding Box: {node_data['bounding_box']}")
    print(f"  Content Hash: {node_data['content_hash']}")
    print(f"  Parser Metadata: {node_data['parser_metadata']}")
    print(f"  Full Content Text:\n    \"{node_data['content_text'][:120]}...\"\n")

    # 6. Verify GET /api/v1/textbooks/{version_id}/pdf-metadata
    print("6. Testing GET /api/v1/textbooks/{version_id}/pdf-metadata...")
    meta_res = client.get(f"/api/v1/textbooks/{test_vid}/pdf-metadata")
    assert meta_res.status_code == 200
    meta_data = meta_res.json()
    print(f"PDF Metadata Response:")
    print(json.dumps(meta_data, indent=2))
    # Security check: Ensure no local filesystem absolute paths are exposed
    meta_str = json.dumps(meta_data)
    assert "E:\\" not in meta_str and "C:\\" not in meta_str and "/storage/" not in meta_str
    print("Verified: Zero local filesystem absolute paths exposed in /pdf-metadata.\n")

    # 7. Verify GET /api/v1/textbooks/{version_id}/pdf
    print("7. Testing GET /api/v1/textbooks/{version_id}/pdf...")
    pdf_stream_res = client.get(f"/api/v1/textbooks/{test_vid}/pdf")
    assert pdf_stream_res.status_code == 200
    assert pdf_stream_res.headers.get("content-type") == "application/pdf"
    content_disp = pdf_stream_res.headers.get("content-disposition", "")
    print(f"Content-Type: {pdf_stream_res.headers.get('content-type')}")
    print(f"Content-Disposition: {content_disp}")
    print(f"Streamed Bytes Length: {len(pdf_stream_res.content)}")
    assert "inline" in content_disp
    assert pdf_stream_res.content.startswith(b"%PDF-")
    print("Verified: Successfully streamed valid PDF binary with inline disposition.\n")

    print("=================================================================")
    print("   ALL REAL HTTP API VERIFICATION CHECKS COMPLETED SUCCESSFULLY")
    print("=================================================================")

    return ingestion_results


if __name__ == "__main__":
    results = run_full_api_verification()
