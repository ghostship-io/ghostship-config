#!/usr/bin/env python3
"""Repair Pelorus 0.2.3's response contract without replaying native input."""
import ast
from pathlib import Path
import sys

MARKER = "# Ghostship: normalize the successful computer-use response."
NORMALIZE = '''    # Ghostship: normalize the successful computer-use response.
    if not isinstance(resp, dict):
        raise HTTPException(status_code=502, detail="Invalid computer-use response; input outcome uncertain")
    if "result" not in resp:
        if resp.get("error"):
            resp = {**resp, "result": "error"}
        elif any(key in resp for key in ("text", "data", "position")):
            resp = {**resp, "result": "ok"}
        else:
            raise HTTPException(status_code=502, detail="Unknown computer-use response; input outcome uncertain")
    return resp
'''


def rewrite(source):
    if MARKER in source:
        ast.parse(source)
        return source
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "desktop_control"]
    if len(functions) != 1:
        raise ValueError("Pelorus desktop_control contract changed")
    node = functions[0].body[-1]
    if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Name) or node.value.id != "resp":
        raise ValueError("Pelorus desktop_control response changed")
    lines = source.splitlines(keepends=True)
    lines[node.lineno - 1:node.end_lineno] = [NORMALIZE]
    result = "".join(lines)
    ast.parse(result)
    return result


def main():
    path = Path(sys.argv[1])
    source = path.read_text()
    updated = rewrite(source)
    if updated != source:
        path.write_text(updated)


if __name__ == "__main__":
    main()
