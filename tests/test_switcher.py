import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from switcher.winpod_switcher import load_profiles, switch_profile, wake_all


class FakeRunner:
    def __init__(self, states: dict[str, str]):
        self.states = states
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **kwargs):
        self.calls.append(cmd)
        if cmd[:2] == ["docker", "inspect"]:
            name = cmd[-1]
            status = self.states.get(name, "missing")
            if status == "missing":
                return SimpleNamespace(returncode=1, stdout="")
            return SimpleNamespace(returncode=0, stdout=status + "\n")
        if cmd[:2] == ["docker", "pause"]:
            self.states[cmd[2]] = "paused"
        elif cmd[:2] == ["docker", "unpause"]:
            self.states[cmd[2]] = "running"
        elif cmd[:2] == ["docker", "start"]:
            self.states[cmd[2]] = "running"
        return SimpleNamespace(returncode=0, stdout="")


class SwitcherTests(unittest.TestCase):
    def test_switch_pauses_other_running_and_resumes_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profiles_path = root / "profiles.json"
            profiles_path.write_text(
                '{"profiles": {"dev": {"container": "winpod-dev", "rdp_port": 3389}, '
                '"sandbox": {"container": "winpod-sandbox", "rdp_port": 3390}}}',
                encoding="utf-8",
            )
            (root / "state" / "dev").mkdir(parents=True)
            (root / "state" / "dev" / "qmp.sock").write_text("", encoding="utf-8")
            (root / "state" / "sandbox").mkdir(parents=True)
            (root / "state" / "sandbox" / "qmp.sock").write_text("", encoding="utf-8")

            profiles = load_profiles(profiles_path)
            runner = FakeRunner({"winpod-dev": "running", "winpod-sandbox": "paused"})
            qmp_calls = []

            res = switch_profile(
                profiles,
                "sandbox",
                root_dir=root,
                launch_rdp=True,
                runner=runner,
                qmp_fn=lambda sock, cmd: qmp_calls.append((sock.parent.name, cmd)) or {},
            )

            self.assertEqual(res["action"], "resumed")
            self.assertEqual(res["paused"], ["dev"])
            self.assertIn(("dev", "stop"), qmp_calls)
            self.assertIn(("sandbox", "cont"), qmp_calls)
            self.assertEqual(runner.states["winpod-dev"], "paused")
            self.assertEqual(runner.states["winpod-sandbox"], "running")
            self.assertTrue(any("/v:127.0.0.1:3390" in c for c in runner.calls))

    def test_wake_all_syncs_only_running_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state" / "dev").mkdir(parents=True)
            (root / "state" / "dev" / "qga.sock").write_text("", encoding="utf-8")
            (root / "state" / "sandbox").mkdir(parents=True)
            (root / "state" / "sandbox" / "qga.sock").write_text("", encoding="utf-8")

            profiles = {
                "dev": {"container": "winpod-dev"},
                "sandbox": {"container": "winpod-sandbox"},
            }
            runner = FakeRunner({"winpod-dev": "running", "winpod-sandbox": "paused"})
            qga_calls = []

            synced = wake_all(
                profiles,
                root_dir=root,
                runner=runner,
                qga_fn=lambda sock: qga_calls.append(sock.parent.name) or {},
            )
            self.assertEqual(synced, ["dev"])
            self.assertEqual(qga_calls, ["dev"])


if __name__ == "__main__":
    unittest.main()
