"""Native channel/gate tests against pinned 7.5.3 and published 7.5.4 engines."""
from contextlib import contextmanager
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import product
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_updater_bridge as bridge


@contextmanager
def server(routes):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0]
            requests.append(path)
            if path not in routes:
                self.send_error(404)
                return
            data = routes[path]
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}", requests
    finally:
        http.shutdown()
        http.server_close()
        worker.join()


class UpdaterBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = Path(os.environ["LAKIS_BRIDGE_BASELINE"])
        if bridge.digest(cls.baseline / "LAKIS_Updater_7.5.2.exe") != "0cafd180079e1fc480a429226e99470add81e8d3c32d1da25a8fa118e475550c":
            raise ValueError("7.5.2 updater baseline mismatch")
        cls.published754 = Path(os.environ["LAKIS_PUBLISHED_754_UPDATER"])
        if bridge.digest(cls.published754) != "462a8f19c86b64c54bf2f9cd4ef730cea15db2096203a63e2df5ab9fdac785ff":
            raise ValueError("published 7.5.4 updater hash mismatch")
        cls.work = Path(tempfile.mkdtemp(prefix="bridge-check-", dir=cls.baseline.parent))
        cls.output = bridge.build(cls.baseline, cls.work)
        cls.probe = cls.work / "BridgeProbe.exe"
        bridge.compile_native(cls.probe, [
            bridge.ROOT / "installer/LAKIS_Updater.cs",
            bridge.ROOT / "installer/LAKIS_Launcher.cs",
            Path(__file__).with_name("UpdaterBridgeProbe.cs"),
        ], main="UpdaterBridgeProbe")
        print("BRIDGE_CANDIDATE=" + str(cls.output), flush=True)

    def fixture(self, version="7.5.4"):
        root = Path(tempfile.mkdtemp(prefix="installation-", dir=self.work))
        (root / "VERSION").write_text(version, encoding="ascii")
        (root / "LAKIS.exe").write_bytes(b"baseline-launcher")
        baseline = "LAKIS_Updater_7.5.2.exe" if version == "7.5.2" else "LAKIS_Updater.exe"
        for alias in ("LAKIS_Updater.exe", "LAKIS_Patcher.exe"):
            shutil.copyfile(self.baseline / baseline, root / alias)
        (root / "ComfyUI/models").mkdir(parents=True)
        (root / "ComfyUI/models/fixture.bin").write_bytes(b"untouched-model")
        (root / "ComfyUI/user").mkdir()
        (root / "ComfyUI/user/settings.json").write_bytes(b'{"retain": true}')
        return root

    def document(self, value):
        path = self.work / ("manifest-" + next(tempfile._get_candidate_names()) + ".json")
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def modern(self):
        return {
            "schema": 2, "kind": "file-patch", "version": "7.5.5",
            "minimum_version": "7.5.4", "minimum_updater_version": "7.5.4",
            "files": [{"path": "ComfyUI/LAKIS/external_ui/bridge-fixture.txt",
                       "url": "https://github.com/Jeong-Luke/LAKIS/fixture",
                       "sha256": hashlib.sha256(b"new-ui").hexdigest()}],
            "delete": [],
        }

    def run_probe(self, *args, executable=None, success=True):
        result = subprocess.run([str(executable or self.probe), *map(str, args)],
                                capture_output=True, timeout=45)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace"))
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout.decode(errors="replace"))
            if args[0] != "launcher":
                self.assertTrue(result.stderr.startswith(b"InvalidDataException:"),
                                result.stderr.decode(errors="replace"))
        return result

    def test_both_native_consumers_use_only_the_v3_channel(self):
        lines = self.run_probe("defaults").stdout.decode().splitlines()
        expected = "|".join([
            "https://raw.githubusercontent.com/Jeong-Luke/LAKIS/main/manifests/update-v3-latest.json",
            "https://cdn.jsdelivr.net/gh/Jeong-Luke/LAKIS@main/manifests/update-v3-latest.json",
        ])
        self.assertEqual(lines, [expected, expected])

    def test_protocol_requires_actual_engine_capability_and_bridge_baseline(self):
        manifest = self.modern()
        self.run_probe("protocol", self.document(manifest), "7.5.4")
        self.run_probe("protocol", self.document(manifest), "7.5.4.0")
        self.run_probe("protocol", self.document(manifest), "7.5.3", success=False)
        for field, value in (
            ("schema", 1), ("schema", 3), ("kind", "runtime-bundle"),
            ("minimum_updater_version", "8.0.1"), ("minimum_version", "7.5.3"),
            ("minimum_version", None), ("minimum_updater_version", None),
            ("version", "8.0"), ("version", "8.0.0\n"), ("files", None),
        ):
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(manifest)
                changed[field] = value
                self.run_probe("protocol", self.document(changed), "7.5.4", success=False)
        manifest["minimum_updater_version"] = "8.0.1"
        # An edited installation VERSION cannot upgrade the running engine.
        self.run_probe("protocol", self.document(manifest), "8.0.0", success=False)

    def test_published_754_cannot_skip_the_pose_capable_engine(self):
        manifest = self.modern()
        manifest.update(
            kind="runtime-update", version="8.0.0", minimum_updater_version="8.0.0",
            files=[], runtime_bundle={
                "schema": 2, "product": "LAKIS", "version": "8.0.0",
                "manifest_sha256": "A" * 64,
            },
        )
        # The installation can still be 7.5.4; the executing engine must be new.
        self.run_probe("protocol", self.document(manifest), "7.5.4")
        root = self.fixture()
        before = {path.relative_to(root): path.read_bytes()
                  for path in root.rglob("*") if path.is_file()}
        with server({"/manifest": json.dumps(manifest).encode()}) as (base, requests):
            self.run_probe("legacy-read", root, base + "/manifest",
                           self.published754, success=False)
        self.assertEqual(requests, ["/manifest"])
        self.assertEqual(
            {path.relative_to(root): path.read_bytes()
             for path in root.rglob("*") if path.is_file()},
            before,
        )

    def test_published_754_can_replace_engine_without_claiming_runtime_complete(self):
        for alias, launch in product(("LAKIS_Updater.exe", "LAKIS_Patcher.exe"), (False, True)):
            with self.subTest(alias=alias, launch=launch):
                root = self.fixture()
                shutil.copyfile(self.probe, root / alias)
                model = root / "ComfyUI/models/fixture.bin"
                identity = model.stat().st_ino
                settings = (root / "ComfyUI/user/settings.json").read_bytes()
                names = ("LAKIS.exe", "LAKIS_Updater.exe", "LAKIS_Patcher.exe")
                manifest = self.modern()
                manifest["version"] = "7.5.4.1"
                payloads = {name: ((self.output / name) if name == "LAKIS.exe" else self.probe)
                            for name in names}
                routes = {"/" + name: path.read_bytes() for name, path in payloads.items()}
                runtime = self.modern()
                runtime.update(
                    kind="runtime-update", version="8.0.0", minimum_updater_version="8.0.0",
                    files=[], runtime_bundle={
                        "schema": 2, "product": "LAKIS", "version": "8.0.0",
                        "manifest_sha256": "A" * 64,
                    },
                )
                routes["/runtime"] = json.dumps(runtime).encode()
                with server(routes) as (base, requests):
                    manifest["files"] = [
                        {"path": name, "url": base + "/" + name,
                         "sha256": bridge.digest(payloads[name])}
                        for name in names
                    ]
                    result = self.run_probe(
                        "legacy-apply", root, base + "/manifest", self.published754,
                        self.document(manifest), executable=root / alias,
                    )
                    helper = Path(result.stdout.decode().strip().split("PENDING=", 1)[1])
                    self.assertEqual(bridge.digest(helper), bridge.digest(self.probe))
                    environment = dict(os.environ, LAKIS_RC_MANIFEST_URL=base + "/bootstrap",
                                       LAKIS_RC_RUNTIME_MANIFEST_URL=base + "/runtime",
                                       LAKIS_RC_RELEASE_BASE_URL=base)
                    subprocess.run(
                        [str(helper), "--finish-self-update", str(root), "7.5.4.1", "0",
                         "--self-name=" + alias] + (["--launch-after-update"] if launch else []),
                        env=environment, check=True, timeout=30,
                    )
                    observed = root / "runtime-continuation.json"
                    deadline = time.monotonic() + 10
                    while not observed.exists() and time.monotonic() < deadline:
                        time.sleep(0.05)
                    self.assertTrue(observed.exists(), "new engine did not fetch the runtime manifest")
                    result = json.loads(observed.read_text(encoding="utf-8-sig"))
                    self.assertEqual(result, {
                        "version": "8.0.0", "installed_version": "7.5.4.1",
                        "engine": "8.0.0", "launch": launch, "manifest_url": base + "/runtime",
                    })
                self.assertEqual(requests, ["/" + name for name in names] + ["/runtime"])
                self.assertEqual((root / "VERSION").read_text(), "7.5.4.1")
                self.run_probe("candidate-engine", root)
                for name in names:
                    self.assertEqual(bridge.digest(root / name), bridge.digest(payloads[name]))
                self.assertEqual(model.stat().st_ino, identity)
                self.assertEqual(model.read_bytes(), b"untouched-model")
                self.assertEqual((root / "ComfyUI/user/settings.json").read_bytes(), settings)

    def test_runtime_continuation_rejects_other_operations_and_incomplete_bridge(self):
        manifest = self.modern()
        manifest.update(
            kind="runtime-update", version="8.0.0", minimum_updater_version="8.0.0",
            files=[], runtime_bundle={
                "schema": 2, "product": "LAKIS", "version": "8.0.0",
                "manifest_sha256": "A" * 64,
            },
        )
        self.run_probe("continuation-protocol", self.document(manifest), "7.5.4.1")
        for current in ("7.5.4", "8.0.0"):
            self.run_probe("continuation-protocol", self.document(manifest), current, success=False)
        self.run_probe("continuation-protocol", self.document(self.modern()), "7.5.4.1", success=False)
        manifest["minimum_updater_version"] = "7.5.4"
        self.run_probe("continuation-protocol", self.document(manifest), "7.5.4.1", success=False)

    def test_rc_continuation_stays_on_explicit_loopback_runtime_manifest(self):
        bridge_url = "http://127.0.0.1:54199/bootstrap"
        runtime_url = "http://127.0.0.1:54199/runtime"
        result = self.run_probe("continuation-info", self.output, "true", bridge_url, runtime_url)
        info = json.loads(result.stdout)
        self.assertEqual(info["manifest_url"], runtime_url)
        self.assertEqual(Path(info["file"]), self.output / "LAKIS_Updater.exe")
        self.assertIn("--continue-runtime-update", info["arguments"])
        self.assertIn("--launch-after-update", info["arguments"])
        for bootstrap, runtime in (
            (bridge_url, ""), ("", runtime_url),
            (bridge_url, "https://example.com/runtime"),
            (bridge_url, "http://127.0.0.1:54199/a/../runtime"),
        ):
            with self.subTest(bootstrap=bootstrap, runtime=runtime):
                self.run_probe("continuation-info", self.output, "false",
                               bootstrap, runtime, success=False)

    def test_runtime_bundle_is_not_silently_accepted_as_a_file_patch(self):
        manifest = self.modern()
        manifest["runtime_bundle"] = {"name": "runtime.zip"}
        self.run_probe("protocol", self.document(manifest), "7.5.4", success=False)

    def test_empty_change_cannot_only_bump_version(self):
        manifest = self.modern()
        manifest["files"] = []
        self.run_probe("protocol", self.document(manifest), "7.5.4", success=False)
        manifest["version"] = "7.5.4.0"
        self.run_probe("protocol", self.document(manifest), "7.5.4")

    def test_runtime_operation_requires_bridge_and_cannot_use_file_patcher(self):
        manifest = self.modern()
        manifest.update(kind="runtime-update", version="8.0.0", files=[], runtime_bundle={
            "schema": 2, "product": "LAKIS", "version": "8.0.0", "manifest_sha256": "A" * 64,
        })
        self.run_probe("protocol", self.document(manifest), "7.5.4")
        self.run_probe("protocol", self.document(manifest), "7.5.3", success=False)
        root = self.fixture()
        self.run_probe("new-apply", root, "http://127.0.0.1:9/manifest",
                       self.document(manifest), success=False)
        self.assertEqual((root / "VERSION").read_text(), "7.5.4")
        self.assertFalse((root / ".lakis").exists())
        manifest["delete"] = ["LAKIS.exe"]
        self.run_probe("protocol", self.document(manifest), "7.5.4", success=False)

    def test_embedded_component_helpers_are_complete_and_tamper_checked(self):
        result = self.run_probe("helpers")
        workspace = Path(result.stdout.decode().strip())
        self.assertEqual({p.name for p in workspace.iterdir()}, set(bridge.RUNTIME_HELPERS))
        for name in ("runtime_patch.py", "runtime_update.py", "runtime_health.py"):
            self.assertEqual(bridge.digest(workspace / name), bridge.digest(bridge.ROOT / "installer" / name))
            self.run_probe("helpers", name, success=False)

    def test_new_runtime_cannot_restore_legacy_channel_binaries(self):
        self.run_probe("candidate-engine", self.output)
        candidate = Path(tempfile.mkdtemp(prefix="candidate-engine-", dir=self.work))
        for name in ("LAKIS.exe", "LAKIS_Updater.exe", "LAKIS_Patcher.exe"):
            shutil.copyfile(self.output / name, candidate / name)
        shutil.copyfile(self.baseline / "LAKIS_Updater.exe", candidate / "LAKIS_Updater.exe")
        self.run_probe("candidate-engine", candidate, success=False)

    def handoff_fixture(self):
        root = self.fixture()
        workspace = Path(self.run_probe("helpers").stdout.decode().strip())
        manifest = workspace / "manifest.json"
        manifest.write_text(json.dumps(self.modern()), encoding="utf-8")
        handoff = {
            "workspace": str(workspace), "target": str(root),
            "candidate": str(self.output), "cache": str(workspace),
            "previous_pid": os.getpid(), "previous_start_ticks": 1,
            "previous_executable": str(root / "LAKIS_Updater.exe"),
            "manifest_sha256": bridge.digest(manifest), "launch": False,
        }
        path = workspace / "handoff.json"
        path.write_text(json.dumps(handoff), encoding="utf-8")
        return root, workspace, manifest, path, handoff

    def test_handoff_tampering_cannot_reach_installed_files(self):
        for change in ("handoff-hash", "manifest", "helper", "workspace", "parent-name"):
            with self.subTest(change=change):
                root, workspace, manifest, path, handoff = self.handoff_fixture()
                before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
                if change == "manifest":
                    manifest.write_bytes(manifest.read_bytes() + b"\n")
                elif change == "helper":
                    helper = workspace / "runtime_patch.py"
                    helper.write_bytes(helper.read_bytes() + b"\n# tampered\n")
                elif change == "workspace":
                    handoff["workspace"] = str(workspace.parent)
                elif change == "parent-name":
                    handoff["previous_executable"] = str(root / "unrelated.exe")
                path.write_text(json.dumps(handoff), encoding="utf-8")
                expected = "0" * 64 if change == "handoff-hash" else bridge.digest(path)
                self.run_probe("runtime-apply", path, expected, success=False)
                self.assertEqual({p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}, before)

    def test_handoff_rejects_reused_pid_or_wrong_parent_identity(self):
        root, _, _, path, _ = self.handoff_fixture()
        result = subprocess.run([str(self.probe), "runtime-apply", str(path), bridge.digest(path)],
                                capture_output=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"Updater parent process identity changed", result.stderr)
        self.assertEqual((root / "VERSION").read_text(), "7.5.4")
        self.assertEqual((root / "ComfyUI/models/fixture.bin").read_bytes(), b"untouched-model")

    def test_interrupted_runtime_blocks_launcher_and_file_patch_entry(self):
        root = self.fixture()
        journal = root.parent / ("." + root.name + "-runtime-transition.json")
        state = {"schema": 2, "target": str(root), "phase": "applying"}
        journal.write_text(json.dumps(state), encoding="utf-8")
        self.run_probe("guard", root, success=False)
        self.run_probe("new-apply", root, "http://127.0.0.1:9/manifest",
                       self.document(self.modern()), success=False)
        self.assertEqual((root / "VERSION").read_text(), "7.5.4")
        for schema, phase in product((1, 2), ("complete", "rolled-back")):
            state.update(schema=schema, phase=phase)
            journal.write_text(json.dumps(state), encoding="utf-8")
            self.run_probe("guard", root)
        journal.write_bytes(b"invalid-json")
        self.run_probe("guard", root, success=False)

    def test_unsupported_manifest_changes_no_installed_files(self):
        root = self.fixture()
        before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        manifest = self.modern()
        manifest["schema"] = 3
        self.run_probe("new-apply", root, "http://127.0.0.1:9/manifest",
                       self.document(manifest), success=False)
        after = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        self.assertEqual(after, before)
        self.assertFalse((root / ".lakis").exists())

    def test_launcher_rejects_unknown_schema_instead_of_reporting_latest(self):
        manifest = self.modern()
        manifest["schema"] = 3
        with server({"/manifest": json.dumps(manifest).encode()}) as (base, requests):
            result = self.run_probe("launcher", base + "/manifest", success=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(requests, ["/manifest"])

    def test_launcher_and_updater_read_the_new_channel(self):
        root = self.fixture()
        with server({"/v2": json.dumps(self.modern()).encode()}) as (base, requests):
            self.run_probe("launcher", base + "/v2")
            result = self.run_probe("new-read", root, base + "/v2")
        self.assertEqual(json.loads(result.stdout)["version"], "7.5.5")
        self.assertEqual(requests, ["/v2", "/v2"])

    def test_published_753_engine_reads_the_bridge_not_the_new_channel(self):
        root = self.fixture("7.5.3")
        legacy = json.loads((self.output / "legacy-update-7.5.4.json").read_text(encoding="utf-8"))
        with server({"/legacy": json.dumps(legacy).encode(),
                     "/v2": json.dumps(self.modern()).encode()}) as (base, requests):
            result = self.run_probe("legacy-read", root, base + "/legacy",
                                    self.baseline / "LAKIS_Updater.exe")
        self.assertEqual(json.loads(result.stdout)["version"], "7.5.4")
        self.assertEqual(requests, ["/legacy"])

    def test_legacy_code_handoff_replaces_each_running_alias_and_preserves_data(self):
        for version, alias in product(("7.5.2", "7.5.3"), ("LAKIS_Updater.exe", "LAKIS_Patcher.exe")):
            with self.subTest(version=version, alias=alias):
                root = self.fixture(version)
                baseline = "LAKIS_Updater_7.5.2.exe" if version == "7.5.2" else "LAKIS_Updater.exe"
                shutil.copyfile(self.probe, root / alias)
                model = root / "ComfyUI/models/fixture.bin"
                identity = model.stat().st_ino
                settings = (root / "ComfyUI/user/settings.json").read_bytes()
                legacy = json.loads((self.output / "legacy-update-7.5.4.json").read_text(encoding="utf-8"))
                # Isolate the self-update handoff from Desktop shortcut creation.
                # The complete cumulative payload is checked independently below.
                legacy["files"] = [item for item in legacy["files"] if item["path"] in
                                   ("LAKIS.exe", "LAKIS_Updater.exe", "LAKIS_Patcher.exe")]
                legacy["delete"] = []
                routes = {"/" + item["path"]: (self.output / item["path"]).read_bytes() for item in legacy["files"]}
                with server(routes) as (base, _):
                    for item in legacy["files"]:
                        item["url"] = base + "/" + item["path"]
                    result = self.run_probe("legacy-apply", root, base + "/legacy",
                                            self.baseline / baseline, self.document(legacy),
                                            executable=root / alias)
                helper = Path(result.stdout.decode().strip().split("PENDING=", 1)[1])
                self.assertEqual(bridge.digest(helper), bridge.digest(self.output / "LAKIS_Updater.exe"))
                subprocess.run([str(helper), "--finish-self-update", str(root), "7.5.4", "0",
                                "--self-name=" + alias], check=True, timeout=30)
                self.assertEqual((root / "VERSION").read_text(), "7.5.4")
                for name in ("LAKIS.exe", "LAKIS_Updater.exe", "LAKIS_Patcher.exe"):
                    self.assertEqual(bridge.digest(root / name), bridge.digest(self.output / name))
                self.assertEqual(model.stat().st_ino, identity)
                self.assertEqual(model.read_bytes(), b"untouched-model")
                self.assertEqual((root / "ComfyUI/user/settings.json").read_bytes(), settings)

    def test_cumulative_bridge_retains_all_753_baseline_files_and_protections(self):
        baseline = json.loads((self.baseline / "update-latest.json").read_text(encoding="utf-8-sig"))
        path = self.output / "legacy-update-7.5.4.json"
        candidate = json.loads(path.read_text(encoding="utf-8"))
        changed = {"LAKIS.exe", "LAKIS_Updater.exe", "LAKIS_Patcher.exe"}
        self.assertEqual([item["path"] for item in candidate["files"]],
                         [item["path"] for item in baseline["files"]])
        self.assertEqual(candidate["delete"], baseline["delete"])
        with zipfile.ZipFile(self.output / "LAKIS_RepairPack.zip") as repair:
            for old, new in zip(baseline["files"], candidate["files"]):
                self.assertEqual(hashlib.sha256(repair.read(new["path"])).hexdigest(),
                                 new["sha256"].lower(), new["path"])
                if new["path"] not in changed:
                    self.assertEqual(new, old)
        for version, executable in (("7.5.2", "LAKIS_Updater_7.5.2.exe"), ("7.5.3", "LAKIS_Updater.exe")):
            with self.subTest(version=version):
                result = self.run_probe("legacy-catalog", self.fixture(version), "http://127.0.0.1:9/manifest",
                                        self.baseline / executable, path)
                self.assertEqual(int(result.stdout), len(candidate["files"]))

    def test_new_engine_applies_only_listed_file_with_model_locked(self):
        root = self.fixture()
        model = root / "ComfyUI/models/fixture.bin"
        identity = model.stat().st_ino
        manifest = self.modern()
        with server({"/file": b"new-ui"}) as (base, _):
            manifest["files"][0]["url"] = base + "/file"
            self.run_probe("new-apply", root, base + "/manifest", self.document(manifest))
        self.assertEqual((root / manifest["files"][0]["path"]).read_bytes(), b"new-ui")
        self.assertEqual((root / "VERSION").read_text(), "7.5.5")
        self.assertEqual(model.stat().st_ino, identity)
        self.assertEqual(model.read_bytes(), b"untouched-model")

    def test_bad_download_retains_existing_version_and_user_data(self):
        root = self.fixture()
        manifest = self.modern()
        with server({"/file": b"corrupt-ui"}) as (base, _):
            manifest["files"][0]["url"] = base + "/file"
            self.run_probe("new-apply", root, base + "/manifest", self.document(manifest), success=False)
        self.assertEqual((root / "VERSION").read_text(), "7.5.4")
        self.assertFalse((root / manifest["files"][0]["path"]).exists())
        self.assertEqual((root / "ComfyUI/models/fixture.bin").read_bytes(), b"untouched-model")

    def test_repair_pack_and_layout_change_only_bridge_components(self):
        changed = {"LAKIS.exe", "LAKIS_Patcher.exe", "LAKIS_Updater.exe", "VERSION"}
        with zipfile.ZipFile(self.baseline / "LAKIS_RepairPack.zip") as old, zipfile.ZipFile(
            self.output / "LAKIS_RepairPack.zip"
        ) as new:
            self.assertEqual(old.namelist(), new.namelist())
            for name in old.namelist():
                expected = b"7.5.4" if name == "VERSION" else (
                    (self.output / name).read_bytes() if name in changed else old.read(name))
                self.assertEqual(new.read(name), expected, name)
            layout = json.loads((self.output / "release-layout.json").read_text(encoding="utf-8"))
            for row in layout["files"]:
                self.assertEqual(row["size"], len(new.read(row["path"])), row["path"])

    def test_existing_native_self_update_recovery_contract(self):
        subprocess.run([
            "powershell", "-NoProfile", "-File", str(bridge.ROOT / "installer/Test-UpdaterSelfAliasFallback.ps1"),
            "-Patcher", str(self.output / "LAKIS_Patcher.exe"), "-Updater", str(self.output / "LAKIS_Updater.exe"),
        ], check=True, timeout=120)


class UpdaterVersionDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = Path(tempfile.mkdtemp(prefix="updater-version-"))
        cls.probe = cls.work / "BridgeProbe.exe"
        bridge.compile_native(cls.probe, [
            bridge.ROOT / "installer/LAKIS_Updater.cs",
            bridge.ROOT / "installer/LAKIS_Launcher.cs",
            Path(__file__).with_name("UpdaterBridgeProbe.cs"),
        ], main="UpdaterBridgeProbe")
        print("VERSION_DISPLAY_CANDIDATE=" + str(cls.work), flush=True)

    def test_display_tracks_installed_version_through_update_and_rollback(self):
        root = Path(tempfile.mkdtemp(prefix="installation-", dir=self.work))
        (root / "VERSION").write_text("7.5.4.1", encoding="ascii")
        result = subprocess.run([
            str(self.probe), "version-display", str(root), "8.0.0\n", "7.5.4.1",
        ], capture_output=True, text=True, encoding="utf-8", timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        prefix = "© 2026 Luke Jeong. All rights reserved. · LAKIS v"
        self.assertEqual(result.stdout.splitlines(), [
            prefix + "7.5.4.1", prefix + "8.0.0", prefix + "7.5.4.1",
        ])

    def test_missing_version_retains_existing_fallback(self):
        root = Path(tempfile.mkdtemp(prefix="installation-", dir=self.work))
        result = subprocess.run([
            str(self.probe), "version-display", str(root),
        ], capture_output=True, text=True, encoding="utf-8", timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(),
                         "© 2026 Luke Jeong. All rights reserved. · LAKIS v0.0.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
