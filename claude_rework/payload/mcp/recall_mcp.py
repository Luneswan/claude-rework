#!/usr/bin/env python3
"""MCP server: give the Claude desktop app the same memory the CLI has.

Claude Code reaches recall through hooks and a skill. The desktop app cannot run
hooks, so it reaches it the way it reaches everything else - as an MCP server
over stdio. Add it to claude_desktop_config.json and Claude calls these tools by
itself when you ask about the past; you never type a command.

    {
      "mcpServers": {
        "recall": { "command": "python", "args": ["<abs path>/recall_mcp.py"] }
      }
    }

Deliberately dependency-free. MCP over stdio is newline-delimited JSON-RPC 2.0,
which is about eighty lines of standard library - and a memory tool that makes
you `pip install` a framework before it will start is a tool people abandon
during setup.

Cost note, since this is the thing recall exists to control: an MCP server's tool
schemas load into context before you type a word. These five are kept terse on
purpose. It is also why the Claude Code path uses hooks instead - a hook costs
nothing until it fires.

Never writes to stdout except protocol messages. Anything else corrupts the
stream and the app shows the server as failed; diagnostics go to stderr.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE = os.environ.get("RECALL_HOME") or os.path.dirname(HERE)
RECALL = os.path.join(CLAUDE, "skills", "recall", "scripts", "recall.py")
PROTOCOL = "2024-11-05"
TIMEOUT = float(os.environ.get("RECALL_MCP_TIMEOUT", "60"))

TOOLS = [
    {"name": "recall_search",
     "description": "Search this machine's Claude history for what was said, "
                    "concluded, decided or done. Use for any question about the "
                    "past: what did we decide, did we already fix X, why did we "
                    "choose Y. Runs locally; nothing is uploaded.",
     "inputSchema": {"type": "object", "required": ["question"], "properties": {
         "question": {"type": "string", "description": "the question, in full"},
         "budget": {"type": "integer",
                    "description": "max characters to return (default 2000)"}}}},
    {"name": "recall_brief",
     "description": "What was asked, what got done, and what is still open in the "
                    "last N days. Use to resume work or answer 'where were we'.",
     "inputSchema": {"type": "object", "properties": {
         "days": {"type": "integer", "description": "window in days (default 3)"}}}},
    {"name": "recall_decisions",
     "description": "The decisions made in the last N days, with their reasons.",
     "inputSchema": {"type": "object", "properties": {
         "days": {"type": "integer", "description": "window in days (default 30)"}}}},
    {"name": "recall_timeline",
     "description": "What happened per day across projects, for the last N days.",
     "inputSchema": {"type": "object", "properties": {
         "days": {"type": "integer", "description": "window in days (default 7)"}}}},
    {"name": "recall_write",
     "description": "Save a durable fact: a preference, a decision, a constraint, "
                    "or a correction worth remembering in later sessions.",
     "inputSchema": {"type": "object", "required": ["fact", "name"], "properties": {
         "fact": {"type": "string", "description": "the fact, self-contained"},
         "name": {"type": "string", "description": "short-kebab-case slug"},
         "type": {"type": "string",
                  "enum": ["project", "user", "feedback", "reference"],
                  "description": "project (default), user, feedback or reference"}}}},
]


def log(msg):
    """stderr only. stdout belongs to the protocol."""
    try:
        print("[recall-mcp] %s" % msg, file=sys.stderr, flush=True)
    except Exception:
        pass


def quiet_flags():
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            "startupinfo": si}


def run_recall(args):
    if not os.path.exists(RECALL):
        return "recall is not installed at %s - run install.py first." % RECALL
    try:
        p = subprocess.run([sys.executable, RECALL] + [str(a) for a in args],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT, **quiet_flags())
    except subprocess.TimeoutExpired:
        return "recall timed out after %ss." % TIMEOUT
    except Exception as exc:
        return "recall could not run: %r" % (exc,)
    out = (p.stdout or "").strip()
    return out or "No match in local history."


def _int(args, key, default):
    """Arguments arrive from a model and are untrusted: a string, a float or a
    negative number must not reach a subprocess argument list unchecked."""
    v = args.get(key, default)
    try:
        v = int(v)
    except Exception:
        return default
    return v if 1 <= v <= 3650 else default


def call_tool(name, args):
    args = args if isinstance(args, dict) else {}
    if name == "recall_search":
        q = str(args.get("question") or "").strip()
        if not q:
            return "No question given."
        try:
            budget = max(200, min(int(args.get("budget", 2000)), 8000))
        except Exception:
            budget = 2000
        return run_recall([q[:400], "--budget", budget])
    if name == "recall_brief":
        return run_recall(["--brief", "--days", _int(args, "days", 3)])
    if name == "recall_decisions":
        return run_recall(["--decisions", "--days", _int(args, "days", 30)])
    if name == "recall_timeline":
        return run_recall(["--timeline", "--days", _int(args, "days", 7)])
    if name == "recall_write":
        fact = str(args.get("fact") or "").strip()
        slug = str(args.get("name") or "").strip()
        kind = str(args.get("type") or "project").strip()
        if kind not in ("project", "user", "feedback", "reference"):
            kind = "project"
        if not fact or not slug:
            return "Both 'fact' and 'name' are required."
        return run_recall(["--write", fact[:4000], "--name", slug[:60],
                           "--type", kind])
    return "Unknown tool: %s" % name


def reply(msg_id, result=None, error=None):
    out = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


def handle(msg):
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    # A notification carries no id and MUST NOT be answered.
    if msg_id is None:
        return

    if method == "initialize":
        client = params.get("protocolVersion") or PROTOCOL
        reply(msg_id, {"protocolVersion": client,
                       "capabilities": {"tools": {}},
                       "serverInfo": {"name": "claude-rework", "version": "1.3.0"}})
    elif method == "tools/list":
        reply(msg_id, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name") or ""
        try:
            text = call_tool(name, params.get("arguments"))
        except Exception as exc:
            log("tool %s failed: %r" % (name, exc))
            reply(msg_id, {"content": [{"type": "text",
                                        "text": "recall failed: %r" % (exc,)}],
                           "isError": True})
            return
        reply(msg_id, {"content": [{"type": "text", "text": text}]})
    elif method == "ping":
        reply(msg_id, {})
    else:
        reply(msg_id, error={"code": -32601,
                             "message": "method not found: %s" % method})


def main() -> int:
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    log("started; recall at %s" % RECALL)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            log("unparseable line, ignored")
            continue
        try:
            handle(msg)
        except Exception as exc:
            log("handler error: %r" % (exc,))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
