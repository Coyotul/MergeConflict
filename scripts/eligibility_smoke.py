"""Live loopback HTTP smoke test with temporary data and a fixed synthetic clock."""

import json
import socket
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import uvicorn

from src.api.gateway.eligibility_demo import create_app
from src.core.eligibility_demo import build_demo_service, load_reference_fixture


def smoke() -> dict:
    reference_time = load_reference_fixture().reference_time
    with TemporaryDirectory(prefix="eligibility-http-") as directory:
        service = build_demo_service(Path(directory) / "smoke.sqlite3", lambda: reference_time)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(
                create_app(service), host="127.0.0.1", port=port,
                log_level="warning", access_log=False, lifespan="off",
            ))
            thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            thread.start()
            deadline = time.monotonic() + 10

            def call(method, path, payload=None, token=None):
                headers = {"Content-Type": "application/json"}
                if token is not None:
                    headers["Authorization"] = f"Bearer {token}"
                data = json.dumps(payload).encode() if payload is not None else None
                request = Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers, method=method)
                try:
                    with urlopen(request, timeout=5) as response:
                        return response.status, json.load(response)
                except HTTPError as response:
                    try:
                        return response.code, json.load(response)
                    finally:
                        response.close()

            try:
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.01)
                if not server.started:
                    raise RuntimeError("The loopback smoke server did not start.")
                status, health = call("GET", "/health")
                if status != 200 or health["mode"] != "synthetic-demo":
                    raise AssertionError("Synthetic healthcheck failed.")
                payload = {"application_id": "demo-app-eligible", "pricing_scenario_id": "demo-quote-eligible",
                           "idempotency_key": "http-smoke-0001"}
                status, first = call("POST", "/api/eligibility/assessments", payload, "demo-customer-key")
                if status != 200 or first["data"]["status"] != "PRELIMINARY_REQUIREMENTS_SATISFIED":
                    raise AssertionError("Live HTTP preliminary assessment failed.")
                status, replay = call("POST", "/api/eligibility/assessments", payload, "demo-customer-key")
                if status != 200 or first != replay:
                    raise AssertionError("Live HTTP retry was not idempotent.")
                status, saved = call("GET", f"/api/eligibility/assessments/{first['data']['assessment_id']}", token="demo-customer-key")
                if status != 200 or saved != first:
                    raise AssertionError("Live HTTP saved assessment did not match.")
                status, denied = call("POST", "/api/eligibility/assessments", payload, "invalid-key")
                if status != 401 or denied["error"]["code"] != "UNAUTHORIZED":
                    raise AssertionError("Live HTTP authentication failure was not enforced.")
                status, denied = call("POST", "/api/eligibility/assessments",
                                      {**payload, "application_id": "demo-app-high-dti"}, "demo-customer-key")
                if status != 403:
                    raise AssertionError("Live HTTP customer isolation failed.")
                status, invalid = call("POST", "/api/eligibility/assessments", {**payload, "consent": True}, "demo-customer-key")
                if status != 422 or invalid["error"]["code"] != "VALIDATION_ERROR":
                    raise AssertionError("Live HTTP request boundary failed.")
                return {"status": "ok", "transport": "live-loopback-http", "checks": 7,
                        "assessmentStatus": first["data"]["status"], "simulated": True,
                        "referenceTime": reference_time.isoformat()}
            finally:
                server.should_exit = True
                thread.join(timeout=5)
                if thread.is_alive():
                    raise RuntimeError("The smoke server did not stop cleanly.")


if __name__ == "__main__":
    print(json.dumps(smoke(), indent=2))