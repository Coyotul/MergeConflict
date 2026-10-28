"""Generate/check versioned HTTP, tool and assessment contracts from actual models."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from src.agent.tools.eligibility import tool_definition
from src.api.gateway.eligibility_demo import create_app
from src.core.eligibility_demo import ROOT, build_demo_service, load_reference_fixture
from src.models.eligibility import EligibilityAssessment, IncomeVerificationData, VerificationResult


def contract_contents() -> dict[Path, str]:
    with TemporaryDirectory(prefix="eligibility-contract-") as directory:
        now = load_reference_fixture().reference_time
        app = create_app(build_demo_service(Path(directory) / "contract.sqlite3", lambda: now))
        documents = {
            ROOT / "contracts" / "http" / "eligibility.openapi.json": app.openapi(),
            ROOT / "contracts" / "schemas" / "eligibility-assessment.schema.json": EligibilityAssessment.model_json_schema(mode="serialization"),
            ROOT / "contracts" / "schemas" / "eligibility-tool.schema.json": tool_definition(),
            ROOT / "contracts" / "schemas" / "anaf-income-verification.schema.json": VerificationResult[IncomeVerificationData].model_json_schema(mode="serialization"),
        }
        return {path: json.dumps(data, indent=2, sort_keys=True) + "\n" for path, data in documents.items()}


def export(check: bool = False) -> None:
    for path, content in contract_contents().items():
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                raise RuntimeError(f"Generated contract is missing/outdated: {path}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        print(f"{'Checked' if check else 'Generated'} {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check artifacts without changing them.")
    export(check=parser.parse_args().check)