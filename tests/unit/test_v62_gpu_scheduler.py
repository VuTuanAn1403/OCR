"""Real process/lock/checkpoint tests; no mock CUDA claims."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil
from tests.unit.process_test_helpers import assert_reaped
import pytest

from src.ocr.runtime.atomic_io import atomic_write_json
from src.ocr.runtime.gpu_scheduler import GPULease, sha256, valid_stage, committed_stage, validate_policy
from src.ocr.runtime.process_tree import supervised_run


def test_child_and_grandchild_cannot_survive_timeout(tmp_path):
    pidfile = tmp_path / "pid.json"
    code = """
import json,subprocess,sys,time,os
p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(40)'])
open(sys.argv[1],'w').write(json.dumps([os.getpid(),p.pid]))
time.sleep(40)
"""
    with pytest.raises(TimeoutError):
        supervised_run([sys.executable, "-c", code, str(pidfile)], cwd=tmp_path,
                       env=os.environ.copy(), log_path=tmp_path / "worker.log", timeout=1.5)
    pids = json.loads(pidfile.read_text())
    for pid in pids:
        assert_reaped(pid)


def test_success_also_reaps_orphaned_grandchild(tmp_path):
    pidfile = tmp_path / "pid.json"
    code = """
import subprocess,sys,json,time
p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(40)'])
open(sys.argv[1],'w').write(json.dumps(p.pid))
time.sleep(.4)
"""
    result = supervised_run([sys.executable, "-c", code, str(pidfile)], cwd=tmp_path,
                            env=os.environ.copy(), log_path=tmp_path / "worker.log", timeout=10)
    assert result["tree_exited"]
    assert_reaped(json.loads(pidfile.read_text()))


def test_gpu_lease_is_exclusive_between_processes_and_released(tmp_path):
    lease = tmp_path / "gpu.lock"
    code = """
import sys
from src.ocr.runtime.gpu_scheduler import GPULease
with GPULease(sys.argv[1],timeout=.2): pass
"""
    with GPULease(lease):
        result = subprocess.run([sys.executable,"-c",code,str(lease)], capture_output=True, text=True)
        assert result.returncode != 0
        assert "GPU_LEASE_BUSY" in result.stderr
    with GPULease(lease, timeout=.2):
        pass


def test_checkpoint_hashes_key_and_predecessor(tmp_path):
    text, structure = tmp_path / "text", tmp_path / "structure"
    text.mkdir(); structure.mkdir()
    a, b = text / "a.json", structure / "b.json"
    a.write_text("a"); b.write_text("b")
    atomic_write_json(text / "done.json", {"generation":"g", "phase":"text", "key":"ka", "files":{"a.json":sha256(a)}})
    atomic_write_json(structure / "done.json", {"generation":"g", "phase":"structure", "key":"kb", "files":{"b.json":sha256(b)},
                                                "input_receipt_sha256":sha256(text / "done.json")})
    assert valid_stage(text,"text","ka") and valid_stage(structure,"structure","kb",text / "done.json")
    assert not committed_stage(text,"text","ka")
    atomic_write_json(text / "exited.json", {"receipt_sha256":sha256(text / "done.json"),"tree_exited":True})
    assert committed_stage(text,"text","ka")
    assert not valid_stage(text,"text","another-key")
    a.write_text("mutated")
    assert not valid_stage(text,"text","ka")
    atomic_write_json(text / "done.json", {"generation":"g", "phase":"text", "key":"ka", "files":{"a.json":sha256(a)}})
    assert not valid_stage(structure,"structure","kb",text / "done.json")


@pytest.mark.parametrize("device,flag",[("cpu",False),("cuda",True),("auto",False)])
def test_policy_does_not_silently_fallback_to_cpu(device,flag):
    with pytest.raises(ValueError):validate_policy(device,flag)


def test_policy_explicit_modes():
    validate_policy("cuda",False)
    validate_policy("cpu",True)


def test_supervisor_import_does_not_import_torch():
    result = subprocess.run([sys.executable,"-c", "import sys; import src.ocr.cli.gpu_runner; assert 'torch' not in sys.modules"],
                            capture_output=True,text=True)
    assert result.returncode == 0, result.stderr


def test_dependency_drift_fails_before_inference(tmp_path,monkeypatch):
    from src.ocr.runtime.dependency_lock import verify_installed_lock
    path=tmp_path/"lock.txt"
    path.write_text("torch==2.12.1+cu126\n")
    monkeypatch.setattr("src.ocr.runtime.dependency_lock.metadata.version",lambda _:"2.12.1+cpu")
    with pytest.raises(RuntimeError,match="DEPENDENCY_LOCK_MISMATCH"):
        verify_installed_lock(path)


def test_real_forward_detects_wrong_torch_device():
    import torch
    from src.ocr.runtime.torch_placement import TorchPlacementAudit
    audit=TorchPlacementAudit("cuda")
    model=torch.nn.Linear(2,2).cpu()
    audit.attach(model,"recognizer")
    model(torch.ones((1,2)))
    with pytest.raises(RuntimeError,match="wrong Torch placement"):
        audit.report(require_inference=True)


def test_uncalled_backend_is_explicit():
    import torch
    from src.ocr.runtime.torch_placement import TorchPlacementAudit
    audit=TorchPlacementAudit("cpu")
    audit.attach(torch.nn.Linear(2,2),"formula")
    result=audit.report()
    assert result["status"] == "NOT_EXERCISED" and result["not_exercised"] == ["formula"]
