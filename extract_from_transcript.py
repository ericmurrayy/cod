#!/usr/bin/env python3
"""Sync DesignSync get_file results from the session transcript into design-src/.

The main session fetches sources with the DesignSync tool; each tool result
(inline in the transcript JSONL, or persisted under tool-results/) is a JSON
object {method, path, content, truncated}. This script scans both places and
writes every fetched file to design-src/<path>, so file contents never need to
be re-typed into Write calls.

Usage: python3 extract_from_transcript.py [transcript.jsonl ...]
Defaults to every *.jsonl under /root/.claude/projects/-home-user-cod/ plus all
persisted tool-result files.
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(ROOT, "design-src")
PROJ_DIR = "/root/.claude/projects/-home-user-cod"


def try_payload(text, written):
    """text may be a get_file result JSON string; write the file if so."""
    if not isinstance(text, str) or '"get_file"' not in text:
        return
    try:
        d = json.loads(text)
    except (ValueError, TypeError):
        return
    if not isinstance(d, dict) or d.get("method") != "get_file":
        return
    path, content = d.get("path"), d.get("content")
    if not path or content is None or ".." in path or path.startswith("/"):
        return
    if d.get("truncated"):
        print(f"SKIP {path}: truncated result", file=sys.stderr)
        return
    dest = os.path.join(DEST, path)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    prev = None
    if os.path.exists(dest):
        with open(dest) as f:
            prev = f.read()
    if prev != content:
        with open(dest, "w") as f:
            f.write(content)
        written.append((path, len(content)))


def scan_transcript(path, written):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if '"get_file"' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            # Tool results live in message.content[].content (string or
            # [{type:text,text:...}] blocks); scan every string we can find.
            stack = [rec]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    stack.extend(node.values())
                elif isinstance(node, list):
                    stack.extend(node)
                elif isinstance(node, str) and node.lstrip().startswith("{"):
                    try_payload(node, written)


def main():
    written = []
    transcripts = sys.argv[1:] or glob.glob(os.path.join(PROJ_DIR, "*.jsonl"))
    for t in transcripts:
        scan_transcript(t, written)
    for pr in glob.glob(os.path.join(PROJ_DIR, "*", "tool-results", "*.txt")):
        with open(pr) as f:
            try_payload(f.read(), written)
    for path, size in written:
        print(f"wrote {path} ({size} bytes)")
    print(f"{len(written)} file(s) updated")


if __name__ == "__main__":
    main()
