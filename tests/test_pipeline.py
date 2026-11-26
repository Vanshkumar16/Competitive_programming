"""End-to-end pipeline tests with mocked APIs. Run: python tests/test_pipeline.py

Covers:
 1. preflight failure (missing CF_HANDLE) -> fails
 2. preflight key/secret validation (mismatched pair vs full pair)
 3. CF extraction: new submission with no local source -> placeholder + pending
 4. self-correct: local source appears -> placeholder upgraded, pending cleared
 5. CF API failure captured, not raised
 6. versioned filenames: resubmission adds a file, never overwrites
 7. Windows path sanitization: problem names with '?', ':', quotes don't crash
"""

import os
import sys
import tempfile
import unittest.mock as mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agents import preflight, extractor, pusher, state as state_module

PASS = 0


def check(name, cond):
    global PASS
    assert cond, f"FAILED: {name}"
    PASS += 1
    print(f"  ok: {name}")


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def cf_payload(sub_id=111, t=1000, name="Test Problem"):
    return {"status": "OK", "result": [{
        "id": sub_id, "verdict": "OK", "creationTimeSeconds": t,
        "programmingLanguage": "Python 3",
        "problem": {"contestId": 1234, "index": "A", "name": name},
    }]}


# Use isolated temp directory so tests never touch repo state or solutions
with tempfile.TemporaryDirectory() as tmp_dir:
    test_solutions = os.path.join(tmp_dir, "solutions")
    test_pending_md = os.path.join(tmp_dir, "PENDING.md")
    test_state_json = os.path.join(tmp_dir, "data", "state.json")
    test_sync_log = os.path.join(tmp_dir, "data", "sync_log.md")

    pusher.SOLUTIONS = test_solutions
    pusher.PENDING_MD = test_pending_md
    state_module.STATE_PATH = test_state_json
    state_module.LOG_PATH = test_sync_log

    print("1. Preflight drops unconfigured handle")
    os.environ.pop("CF_HANDLE", None)
    os.environ.pop("CF_API_KEY", None)
    os.environ.pop("CF_API_SECRET", None)
    r = preflight.run()
    check("cf not ok without CF_HANDLE", not r.cf_ok)

    os.environ["CF_HANDLE"] = "testuser"
    r = preflight.run()
    check("cf ok with handle (anonymous mode)", r.cf_ok)

    print("2. Preflight API key/secret validation")
    os.environ["CF_API_KEY"] = "k"   # secret missing -> mismatched pair
    r = preflight.run()
    check("mismatched key/secret pair fails preflight", not r.cf_ok)
    os.environ["CF_API_SECRET"] = "s"
    r = preflight.run()
    check("full key/secret pair passes", r.cf_ok)

    print("3. CF extraction -> placeholder path")
    state = state_module.load_state()
    with mock.patch("agents.extractor.requests.get", return_value=FakeResp(cf_payload())):
        res = extractor.run(state=state)
    check("one item extracted", len(res.items) == 1)
    check("no code found (no local dir)", res.items[0].code is None)

    pr = pusher.write_items(res.items, state)
    check("counted as new", pr.new_count == 1)
    check("submission recorded", "111" in state["codeforces"]["synced_ids"])
    check("marked pending", "111" in state["codeforces"]["pending_ids"])
    ph = os.path.join(test_solutions, "codeforces", "1234A-Test_Problem", "NEEDS_SOURCE_111.txt")
    check("placeholder file exists", os.path.exists(ph))
    check("PENDING.md lists it", "111" in open(test_pending_md, encoding="utf-8").read())

    print("4. Self-correct: local source appears")
    fake_cf_dir = os.path.join(tmp_dir, "fake_cf")
    os.makedirs(fake_cf_dir, exist_ok=True)
    with open(os.path.join(fake_cf_dir, "1234A.py"), "w", encoding="utf-8") as f:
        f.write("print('real')\n")
    os.environ["CF_LOCAL_SOLUTIONS_DIR"] = fake_cf_dir
    with mock.patch("agents.extractor.requests.get", return_value=FakeResp(cf_payload())):
        res = extractor.run(state=state)
    check("pending item re-extracted with code", len(res.items) == 1 and res.items[0].code)
    pr = pusher.write_items(res.items, state)
    check("counted as upgrade not new", pr.upgraded_count == 1 and pr.new_count == 0)
    check("pending cleared", "111" not in state["codeforces"]["pending_ids"])
    check("placeholder removed", not os.path.exists(ph))
    real = os.path.join(test_solutions, "codeforces", "1234A-Test_Problem", "solution_111.py")
    check("real solution written", open(real, encoding="utf-8").read() == "print('real')\n")
    check("PENDING.md now empty", "Nothing pending" in open(test_pending_md, encoding="utf-8").read())

    print("5. CF API failure captured, not raised")
    def boom(*a, **k):
        raise RuntimeError("CF is down")

    with mock.patch("agents.extractor.extract_codeforces", side_effect=boom):
        res = extractor.run(state=state)
    check("cf error captured, not raised", res.cf_error == "CF is down")
    check("items list is empty on failure", len(res.items) == 0)

    print("6. Versioned filenames -- resubmission never overwrites")
    with mock.patch("agents.extractor.requests.get",
                    return_value=FakeResp(cf_payload(sub_id=222, t=3000))):
        res = extractor.run(state=state)
    pr = pusher.write_items(res.items, state)
    d = os.path.join(test_solutions, "codeforces", "1234A-Test_Problem")
    files = sorted(os.listdir(d))
    check("both attempts kept", files == ["solution_111.py", "solution_222.py"])

    print("7. Windows path sanitization for special problem titles")
    with mock.patch("agents.extractor.requests.get",
                    return_value=FakeResp(cf_payload(sub_id=333, t=4000, name='Can I "Square"?: Yes!'))):
        res = extractor.run(state=state)
    check("sanitized dir_name has no illegal characters",
          '?' not in res.items[0].dir_name and ':' not in res.items[0].dir_name and '"' not in res.items[0].dir_name)
    pr = pusher.write_items(res.items, state)
    check("directory created successfully on disk",
          os.path.exists(os.path.join(test_solutions, "codeforces", res.items[0].dir_name)))

print(f"\nALL {PASS} CHECKS PASSED")
