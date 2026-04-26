from __future__ import annotations
import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "jetson_resource_probe.py"
SPEC = importlib.util.spec_from_file_location("jetson_resource_probe", SCRIPT)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def test_section_uses_line_anchored_markers() -> None:
    output = """SECTION one
keep
cmd echo SECTION two should not split
SECTION two
actual
"""

    assert probe.section(output, "one") == "keep\ncmd echo SECTION two should not split"
    assert probe.section(output, "two") == "actual"


def test_extract_lfb_from_tegrastats() -> None:
    text = "RAM 4468/7620MB (lfb 39x4MB) SWAP 1076/32768MB (cached 568MB)"

    assert probe.extract_lfb(text) == "39x4MB"


def test_extract_codex_peak_kb() -> None:
    assert probe.extract_codex_peak_kb("CODEX_PEAK_KB=57448\n") == 57448
    assert probe.extract_codex_peak_kb("no peak") is None


def test_docker_cgroup_summary_formats_memory_and_swap() -> None:
    docker = """assistant-llm 2.665GiB / 7.441GiB 0.00%
cgroup 62429d688b3c pid=8062 path=/sys/fs/cgroup/system.slice/docker.scope memory.current=2879574016 memory.swap.current=880742400
"""

    assert probe.docker_cgroup_summary(docker) == "62429d688b3c current=2.68 GiB, swap=0.82 GiB"


def test_build_resource_snapshot_from_probe_sections() -> None:
    output = """SECTION meminfo
MemAvailable:    3088980 kB
CmaFree:            4268 kB
SECTION top_rss
PID COMMAND RSS
1 llama-server 2546308
SECTION known_process_status
SECTION docker
assistant-llm 2.665GiB / 7.441GiB 0.00%
cgroup 62429d688b3c pid=8062 path=/sys/fs/cgroup/system.slice/docker.scope memory.current=2879574016 memory.swap.current=880742400
SECTION tegrastats
RAM 4457/7620MB (lfb 39x4MB) SWAP 1074/32768MB
"""

    snapshot = probe.build_resource_snapshot(output)

    assert round(snapshot.mem_available_mib, 1) == 3016.6
    assert round(snapshot.cma_free_mib or 0, 1) == 4.2
    assert snapshot.largest_free_block_count == 39
    assert snapshot.largest_free_block_mb == 4
    assert snapshot.gemma_running is True
    assert round(snapshot.gemma_memory_gib or 0, 2) == 2.68
    assert round(snapshot.gemma_swap_gib or 0, 2) == 0.82


def test_post_resource_policy_sends_normalized_snapshot(monkeypatch) -> None:
    sent: list[tuple[str, str, dict]] = []

    class Args:
        bridge_url = "http://bridge"
        requested_mode = "voice_realtime"
        http_timeout = 1

    def fake_http_json(method: str, url: str, body: dict, timeout: float = 10) -> None:
        sent.append((method, url, body))

    monkeypatch.setattr(probe, "http_json", fake_http_json)
    output = """SECTION meminfo
MemAvailable:    3088980 kB
CmaFree:            4268 kB
SECTION top_rss
PID COMMAND RSS
1 llama-server 2546308
SECTION known_process_status
SECTION docker
assistant-llm 2.665GiB / 7.441GiB 0.00%
cgroup 62429d688b3c pid=8062 path=/sys/fs/cgroup/system.slice/docker.scope memory.current=2879574016 memory.swap.current=880742400
SECTION tegrastats
RAM 4457/7620MB (lfb 39x4MB) SWAP 1074/32768MB
"""

    result = probe.post_resource_policy(Args(), output)

    assert result["ok"] is True
    assert sent[0][0] == "POST"
    assert sent[0][1] == "http://bridge/resource/policy"
    assert sent[0][2]["requested_mode"] == "voice_realtime"
    assert round(sent[0][2]["snapshot"]["gemma_swap_gib"], 2) == 0.82


def test_resource_warnings_flags_claude_fragmentation_and_cma() -> None:
    snapshot = """SECTION meminfo
MemAvailable:    2000000 kB
CmaFree:            2392 kB
SECTION top_rss
PID COMMAND RSS
1 claude login 344000
2 llama-server 2546308
SECTION tegrastats
RAM 4813/7620MB (lfb 39x4MB) SWAP 1113/32768MB
"""

    warnings = probe.resource_warnings(snapshot)

    assert any("MemAvailable" in warning for warning in warnings)
    assert any("CmaFree" in warning for warning in warnings)
    assert any("largest free block" in warning for warning in warnings)
    assert any("claude login" in warning for warning in warnings)
    assert any("Gemma llama-server" in warning for warning in warnings)
