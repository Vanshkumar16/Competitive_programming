"""End-to-end pipeline tests with mocked APIs. Run: python3 tests/test_pipeline.py

Covers:
 1. preflight failure (missing env) -> platform dropped
 2. CF extraction: new submission with no local source -> placeholder + pending
 3. self-correct: local source appears -> placeholder upgraded, pending cleared
 4. one platform failing does not discard the other's items
 5. versioned filenames: resubmission adds a file, never overwrites
"""

import json
import os
import sys
import unittest.mock as mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agents import preflight, extractor, pusher
from agents.state import load_state

PASS = 0

def check(name, cond):
    global PASS
    assert cond, f"FAILED: {name}"
    PASS += 1
    print(f"  ok: {name}")


class FakeResp:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload


def cf_payload(sub_id=111, t=1000):
    return {"status": "OK", "result": [{
        "id": sub_id, "verdict": "OK", "creationTimeSeconds": t,
        "programmingLanguage": "Python 3",
        "problem": {"contestId": 1234, "index": "A", "name": "Test Problem"},
    }]}


print("1. Preflight drops unconfigured platforms")
for var in ("CF_HANDLE", "LEETCODE_SESSION", "LEETCODE_CSRF_TOKEN"):
    os.environ.pop(var, None)
r = preflight.run({"codeforces", "leetcode"})
check("cf not ok without CF_HANDLE", not r.cf_ok)
check("lc not ok without cookies", not r.lc_ok)

os.environ["CF_HANDLE"] = "testuser"
r = preflight.run({"codeforces"})
check("cf ok with handle (anonymous mode)", r.cf_ok)

os.environ["CF_API_KEY"] = "k"   # secret missing -> mismatched pair
r = preflight.run({"codeforces"})
check("mismatched key/secret pair fails preflight", not r.cf_ok)
os.environ["CF_API_SECRET"] = "s"
r = preflight.run({"codeforces"})
check("full key/secret pair passes", r.cf_ok)

print("2. CF extraction -> placeholder path")
state = load_state()
with mock.patch("agents.extractor.requests.get", return_value=FakeResp(cf_payload())):
    res = extractor.run({"codeforces"}, state)
check("one item extracted", len(res.items) == 1)
check("no code found (no local dir)", res.items[0].code is None)

pr = pusher.write_items(res.items, state)
check("counted as new", pr.new_count == 1)
check("submission recorded", "111" in state["codeforces"]["synced_ids"])
check("marked pending", "111" in state["codeforces"]["pending_ids"])
ph = os.path.join(ROOT, "solutions", "codeforces", "1234A-Test_Problem", "NEEDS_SOURCE_111.txt")
check("placeholder file exists", os.path.exists(ph))
check("PENDING.md lists it", "111" in open(os.path.join(ROOT, "PENDING.md")).read())

print("3. Self-correct: local source appears")
os.makedirs("/tmp/fake_cf", exist_ok=True)
open("/tmp/fake_cf/1234A.py", "w").write("print('real')\n")
os.environ["CF_LOCAL_SOLUTIONS_DIR"] = "/tmp/fake_cf"
with mock.patch("agents.extractor.requests.get", return_value=FakeResp(cf_payload())):
    res = extractor.run({"codeforces"}, state)
check("pending item re-extracted with code", len(res.items) == 1 and res.items[0].code)
pr = pusher.write_items(res.items, state)
check("counted as upgrade not new", pr.upgraded_count == 1 and pr.new_count == 0)
check("pending cleared", "111" not in state["codeforces"]["pending_ids"])
check("placeholder removed", not os.path.exists(ph))
real = os.path.join(ROOT, "solutions", "codeforces", "1234A-Test_Problem", "solution_111.py")
check("real solution written", open(real).read() == "print('real')\n")
check("PENDING.md now empty", "Nothing pending" in open(os.path.join(ROOT, "PENDING.md")).read())

print("4. One platform failing doesn't discard the other")
def boom(*a, **k): raise RuntimeError("CF is down")
with mock.patch("agents.extractor.extract_codeforces", side_effect=boom), \
     mock.patch("agents.extractor.extract_leetcode",
                return_value=[extractor.Item("leetcode", "999", "Two Sum",
                                             "two-sum", "py", "class S: pass", 2000)]):
    res = extractor.run({"codeforces", "leetcode"}, state)
check("cf error captured, not raised", res.cf_error == "CF is down")
check("leetcode item still present", len(res.items) == 1)
pr = pusher.write_items(res.items, state)
check("leetcode item committed to disk", os.path.exists(
    os.path.join(ROOT, "solutions", "leetcode", "two-sum", "solution_999.py")))

print("5. Versioned filenames -- resubmission never overwrites")
with mock.patch("agents.extractor.requests.get",
                return_value=FakeResp(cf_payload(sub_id=222, t=3000))):
    res = extractor.run({"codeforces"}, state)
pr = pusher.write_items(res.items, state)
d = os.path.join(ROOT, "solutions", "codeforces", "1234A-Test_Problem")
files = sorted(os.listdir(d))
check("both attempts kept", files == ["solution_111.py", "solution_222.py"])

print(f"\nALL {PASS} CHECKS PASSED")
