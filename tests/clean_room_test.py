#!/usr/bin/env python3
"""Install the repo into a machine that has never seen recall, and use it.

Proves the claims the README makes for someone who is not me:
  - installs into a bare ~/.claude with nothing but transcripts
  - works with no graphify installed, and with a graph dir but no binary
  - retrieves a known answer from a corpus it built itself
  - the hook records work, is idempotent, and uninstalls cleanly
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import tempfile

# This file lives in <repo>/tests/, so the repo root is one level up.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
FAILS = []


def ok(name, cond, detail=""):
    print("  %-46s %s%s" % (name, "PASS" if cond else "FAIL",
                            "" if cond else "  <- " + str(detail)[:150]))
    if not cond:
        FAILS.append(name)


def ev(role, text):
    return json.dumps({"type": role, "message": {"content": text}})


def make_machine(root):
    """A bare ~/.claude: transcripts and nothing else."""
    proj = os.path.join(root, "projects", "demo-app")
    os.makedirs(proj)
    turns = []
    # Messages are deliberately long enough (>260 chars) for the known-item
    # generator to build cases from them, the way a real session would be.
    topics = [("how should we handle retries on the upload endpoint when the "
               "provider starts returning 429 under load",
               "Decided on exponential backoff capped at 30 seconds, because the "
               "provider rate-limits per minute and a fixed delay synchronised "
               "every client onto the same second. Jitter is drawn uniformly from "
               "zero to the current interval, and the retry budget is five "
               "attempts before the upload is parked on the dead letter queue for "
               "an operator to inspect."),
              ("the dashboard is slow when a team has many projects and the "
               "sidebar takes seconds to paint",
               "The N+1 was in the membership serializer; prefetching the related "
               "rows took the page from 4.1 seconds to 380 milliseconds. The "
               "serializer walked every project to resolve its owner, so a team "
               "with two hundred projects issued two hundred queries. Confirmed by "
               "counting statements in the request log before and after."),
              ("why did the nightly reconciliation job stop emailing failure "
               "reports to the operations channel",
               "The SMTP credentials rotated and the job swallowed the auth error, "
               "so it reported success while sending nothing. The cause was a bare "
               "except around the send call that logged at debug level. Fixed by "
               "letting the exception propagate and adding a synthetic canary "
               "message that must arrive before the run is marked healthy."),
              ("should we move the queue off redis onto something with stronger "
               "durability guarantees",
               "Kept redis. The durability gap only matters for the billing "
               "consumer, which now writes an idempotency record before acking, so "
               "a lost message replays without double charging. Migrating the other "
               "eleven consumers would cost weeks and buy nothing measurable, and "
               "the trade-off was not worth the operational churn.")]
    for i in range(60):
        q, a = topics[i % len(topics)]
        turns.append(ev("user", "%s (round %d)" % (q, i)))
        turns.append(ev("assistant", a + " Round %d notes." % i))
    turns.append(ev("user", "what timeout did we settle on for the payment webhook"))
    turns.append(ev("assistant",
                    "We set the payment webhook timeout to 12 seconds after "
                    "measuring the provider's p99 at 9.4 seconds. The marker for "
                    "this decision is quetzalcoatl so it can be found later."))
    with open(os.path.join(proj, "session-01.jsonl"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write("\n".join(turns) + "\n")
    return proj


def run(args, root, timeout=900):
    env = dict(os.environ)
    env.update({"RECALL_HOME": root, "PYTHONIOENCODING": "utf-8",
                "HF_HUB_DISABLE_PROGRESS_BARS": "1"})
    # a PATH with no graphify on it, so "optional" is tested rather than assumed
    env["PATH"] = os.path.dirname(PY)
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=env, cwd=root)


def main():
    tmp = tempfile.mkdtemp(prefix="cleanroom-")
    root = os.path.join(tmp, ".claude")
    os.makedirs(root)
    try:
        proj = make_machine(root)
        print("clean-room install (a machine that has never seen recall)")
        print("  root: %s" % root)
        print()

        which = shutil.which("graphify", path=os.path.dirname(PY))
        ok("graphify absent from test PATH", which is None, which)

        p = run([PY, os.path.join(REPO, "install.py")], root)
        ok("installer exits 0", p.returncode == 0, (p.stderr or "")[-200:])
        ok("skill copied", os.path.exists(os.path.join(root, "skills", "recall",
                                                       "scripts", "recall.py")))
        ok("hook copied", os.path.exists(os.path.join(root, "hooks",
                                                      "capture_events.py")))
        ok("corpus built", os.path.exists(os.path.join(root, "recall_corpus.jsonl")))

        def hook_cmds(settings):
            out = {}
            for event, groups in settings.get("hooks", {}).items():
                for g in groups:
                    for h in g.get("hooks", []):
                        out.setdefault(event, []).append(h.get("command", ""))
            return out

        s = json.load(open(os.path.join(root, "settings.json"), encoding="utf-8"))
        cmds = hook_cmds(s)
        want = {"SessionStart": "recall_session_start.py",
                "UserPromptSubmit": "recall_auto.py",
                "PostToolUse": "capture_events.py",
                "PreCompact": "recall_precompact.py"}
        missing = [e for e, script in want.items()
                   if not any(script in c for c in cmds.get(e, []))]
        ok("all four hooks registered", not missing, "missing: %s" % missing)
        allc = [c for v in cmds.values() for c in v]
        ok("no hook path has backslashes",
           all("\\" not in c for c in allc), [c for c in allc if "\\" in c][:1])

        p2 = run([PY, os.path.join(REPO, "install.py"), "--no-build"], root)
        s2 = json.load(open(os.path.join(root, "settings.json"), encoding="utf-8"))
        c2 = hook_cmds(s2)
        dupes = [e for e, script in want.items()
                 if sum(1 for c in c2.get(e, []) if script in c) != 1]
        ok("re-install does not duplicate", not dupes, "duplicated: %s" % dupes)
        ok("re-install says so", "already registered" in (p2.stdout or ""))

        # the desktop-app path: an MCP server that actually speaks the protocol
        mcp = os.path.join(root, "recall_mcp", "recall_mcp.py")
        ok("mcp server installed", os.path.exists(mcp))
        msgs = "\n".join([
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
            '{"protocolVersion":"2024-11-05","capabilities":{}}}',
            '{"jsonrpc":"2.0","method":"notifications/initialized"}',
            '{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
            '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":'
            '"recall_search","arguments":{"question":"payment webhook timeout",'
            '"budget":800}}}',
        ]) + "\n"
        menv = dict(os.environ)
        menv.update({"RECALL_HOME": root, "PYTHONIOENCODING": "utf-8"})
        mp = subprocess.run([PY, mcp], input=msgs, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=180,
                            env=menv)
        replies = [json.loads(l) for l in (mp.stdout or "").splitlines() if l.strip()]
        ids = [r.get("id") for r in replies]
        ok("mcp answers initialize and tools/list", ids[:2] == [1, 2], ids)
        ok("mcp does not answer notifications", None not in ids, ids)
        tools = next((r["result"]["tools"] for r in replies if r.get("id") == 2), [])
        ok("mcp exposes its tools", len(tools) == 5,
           [t.get("name") for t in tools])
        call = next((r for r in replies if r.get("id") == 3), {})
        ok("mcp tools/call returns content",
           bool(call.get("result", {}).get("content")), call)

        R = os.path.join(root, "skills", "recall", "scripts", "recall.py")

        q = run([PY, R, "what timeout did we agree for the payment webhook",
                 "--budget", "1500"], root)
        ok("retrieves the known answer", "quetzalcoatl" in (q.stdout or "").lower(),
           (q.stdout or "")[:200])
        ok("query does not crash", "Traceback" not in (q.stderr or ""),
           (q.stderr or "")[-200:])
        ok("no graphify -> no crash", q.returncode == 0, (q.stderr or "")[-160:])

        os.makedirs(os.path.join(proj, "graphify-out"), exist_ok=True)
        json.dump({"nodes": []}, open(os.path.join(proj, "graphify-out",
                                                   "graph.json"), "w"))
        q2 = run([PY, R, "payment webhook timeout", "--budget", "1200",
                  "--project", proj], root)
        ok("graph dir but no binary -> no crash",
           q2.returncode == 0 and "Traceback" not in (q2.stderr or ""),
           (q2.stderr or "")[-200:])

        subs = [["--stores"], ["--budget-report"], ["--brief", "--days", "30"],
                ["--handoff"], ["--decisions", "--days", "30"],
                ["--digest", "--weeks", "2"], ["--timeline", "--days", "30"],
                ["--gc"], ["--optimize", "--days", "30"], ["--estimate", "hi"]]
        broken = []
        for args in subs:
            r = run([PY, R] + args, root)
            if r.returncode != 0 or "Traceback" in (r.stderr or ""):
                broken.append(args[0] + ":" + (r.stderr or "")[-90:])
        ok("all subcommands clean on a bare machine", not broken, broken)

        r = run([PY, R, "--optimize", "--days", "30", "--apply"], root)
        moved = "demoted " in (r.stdout or "") or "promoted " in (r.stdout or "")
        ok("optimizer withholds without evidence", not moved, (r.stdout or "")[:160])

        hook = os.path.join(root, "hooks", "capture_events.py")
        payload = json.dumps({"tool_name": "Bash", "cwd": proj,
                              "tool_input": {"command": "pytest -q"}})
        subprocess.run([PY, hook], input=payload, text=True, capture_output=True,
                       timeout=60)
        evp = os.path.join(root, "events.jsonl")
        rec = ([json.loads(l) for l in open(evp, encoding="utf-8")]
               if os.path.exists(evp) else [])
        ok("hook writes an event", any(x.get("d") == "pytest -q" for x in rec),
           rec[:2])

        t = run([PY, os.path.join(root, "skills", "recall", "tests", "run_tests.py"),
                 "--known", "25"], root)
        passed = "PASS" in (t.stdout or "")
        ok("bundled test suite passes here", passed, "see full output below")
        if not passed:
            print("  ---- run_tests.py output ----")
            for line in (t.stdout or "").splitlines():
                print("  | " + line)
            for line in (t.stderr or "").splitlines()[-15:]:
                print("  ! " + line)
            print("  -----------------------------")

        u = run([PY, os.path.join(REPO, "install.py"), "--uninstall"], root)
        s3 = json.load(open(os.path.join(root, "settings.json"), encoding="utf-8"))
        left = [h["command"] for g in s3.get("hooks", {}).get("PostToolUse", [])
                for h in g["hooks"] if "capture_events.py" in h["command"]]
        ok("uninstall removes the hook", not left, left)
        ok("uninstall keeps settings.json valid", u.returncode == 0)
        ok("uninstall keeps user data", os.path.exists(evp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print("  FAIL: " + "; ".join(FAILS))
        return 1
    print("  ALL CLEAN - a fresh machine installs and works with no graphify")
    return 0


if __name__ == "__main__":
    sys.exit(main())
