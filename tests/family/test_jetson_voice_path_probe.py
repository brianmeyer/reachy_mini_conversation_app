from __future__ import annotations
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "jetson_voice_path_probe.py"
SPEC = importlib.util.spec_from_file_location("jetson_voice_path_probe", SCRIPT)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def test_report_names_policy_skipped_stt() -> None:
    report = probe.make_report(
        {
            "identity": {"ok": True},
            "voice": {
                "ok": True,
                "parsed": {
                    "resource_policy": {
                        "voice_realtime": {
                            "decision": {
                                "severity": "constrained",
                                "allow_gpu_stt": False,
                                "allow_local_gemma": False,
                                "warnings": ["CmaFree is low."],
                            }
                        }
                    },
                    "stt": {"skipped": True, "reason": "resource_policy_blocked_gpu_stt"},
                },
            },
        }
    )

    assert "Resource policy: constrained" in report
    assert "GPU STT=no" in report
    assert "STT: skipped (resource_policy_blocked_gpu_stt)" in report
    assert "load=Nones" not in report
