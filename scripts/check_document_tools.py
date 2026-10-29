"""Run the real document checks and print a plain-language summary (exit 1 on failure)."""
import argparse
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    "test_secure_document_safety": "Safe uploads, customer/session isolation, original-file integrity and persistence",
    "test_document_verification_safety": "No guessed amounts, strict checks and document-to-document consistency",
    "test_ocr_documents": "Actual OCR: PDF, PNG/JPEG, upside-down scans and mixed-page PDFs",
    "test_documents": "Assistant tools: real extraction, read-only access and blocked overrides",
    "test_document_tools_api": "Full API: upload, verification, recovery, restart and blocked unsafe submission",
    "test_chat_scenarios": "Complete conversational application journey using real synthetic PDFs",
}
TESTS = [
    ROOT / "tests" / "unit" / "test_secure_document_safety.py",
    ROOT / "tests" / "unit" / "test_document_verification_safety.py",
    ROOT / "tests" / "unit" / "test_ocr_documents.py",
    ROOT / "tests" / "unit" / "orchestrator" / "test_documents.py",
    ROOT / "tests" / "integration" / "orchestrator" / "test_document_tools_api.py",
    ROOT / "tests" / "e2e" / "test_chat_scenarios.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="Also show individual pytest output, even when everything passes.")
    args = parser.parse_args()
    report = ROOT / "data" / "local" / "document-checks" / "results.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)
    print("Checking the document pipeline with synthetic files only. No model API key or Docker is needed.\n", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *(str(path) for path in TESTS), "-q", "-p", "no:cacheprovider",
         "--tb=short", f"--junitxml={report}"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    report_failed = False
    if report.exists():
        cases = list(ET.parse(report).getroot().iter("testcase"))
        for module, label in GROUPS.items():
            group = [case for case in cases if case.get("classname", "").split(".")[-1] == module]
            failures = sum(case.find("failure") is not None or case.find("error") is not None for case in group)
            skipped = sum(case.find("skipped") is not None for case in group)
            passed = len(group) - failures - skipped
            status = "FAIL" if failures or not group else "PASS" if not skipped else "CHECK"
            report_failed = report_failed or status == "FAIL"
            print(f"[{status}] {label}: {passed} passed, {failures} failed, {skipped} skipped")
        for case in cases:
            skipped = case.find("skipped")
            if skipped is not None:
                print(f"  Not tested: {case.get('name')}: {skipped.get('message')}")
        print(f"\nDetailed test report: {report}")
    else:
        report_failed = True
    failed = result.returncode or (1 if report_failed else 0)
    if failed or args.verbose:
        print(result.stdout)
        print(result.stderr)
    if failed:
        print("RESULT: checks failed. Do not treat this run as a verified working build.")
    else:
        print("RESULT: all runnable document checks passed. Skipped checks, if any, are listed above.")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())