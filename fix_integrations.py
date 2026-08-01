#!/usr/bin/env python3
"""Fix broken integration adapter files - v2."""
import py_compile
import glob
import os
import re

BASE = "/Users/javiercamaraportepetit/Desktop/B2B-AI-MVP/enterprise"
os.chdir(BASE)

broken = []
for f in glob.glob("b2b_ai/integrations/**/*.py", recursive=True):
    try:
        py_compile.compile(f, doraise=True)
    except py_compile.PyCompileError:
        broken.append(f)

print(f"Found {len(broken)} broken files")

fixed = 0
for filepath in broken:
    full = os.path.join(BASE, filepath)
    with open(full, "r") as fh:
        content = fh.read()

    lines = content.split("\n")

    # Fix 1: Remove misplaced "import os" lines (there may be multiple)
    lines = [l for l in lines if l != "import os"]

    # Fix 2: Split combined lines (setdefault + super)
    new_lines = []
    for line in lines:
        has_setdefault = 'setdefault("api_key"' in line or 'setdefault("company_id"' in line or "api_key=os.environ" in line
        has_super = "super().__init__" in line
        if has_setdefault and has_super:
            idx = line.find("super().__init__")
            if idx > 0:
                new_lines.append(line[:idx].rstrip())
                new_lines.append("        " + line[idx:])
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Fix 3: Add "import os" after the docstring block but before other imports
    # Find the end of the module docstring (after """ ... """)
    insert_pos = 0
    in_docstring = False
    for i, line in enumerate(new_lines):
        stripped = line.strip()
        if stripped.startswith('# -*- coding'):
            continue
        if '"""' in stripped:
            count = stripped.count('"""')
            if count == 2:  # Single-line docstring
                insert_pos = i + 1
                break
            elif count == 1:
                in_docstring = not in_docstring
                if not in_docstring:
                    insert_pos = i + 1
                    break
        elif not in_docstring and not stripped.startswith('#') and not stripped.startswith('"""'):
            insert_pos = i
            break

    # Skip past existing imports (from __future__ etc.)
    for i in range(insert_pos, len(new_lines)):
        stripped = new_lines[i].strip()
        if stripped.startswith("from ") or stripped.startswith("import "):
            insert_pos = i + 1
        elif stripped == "" or stripped.startswith("#"):
            continue
        else:
            break

    # Make sure we're not inserting inside a multi-line import
    # Count open parens from the last import line backwards
    paren_depth = 0
    for i in range(insert_pos - 1, -1, -1):
        paren_depth += new_lines[i].count(")") - new_lines[i].count("(")
        if paren_depth > 0:
            # We're inside a multi-line import, find the end
            for j in range(i, len(new_lines)):
                paren_depth += new_lines[j].count(")") - new_lines[j].count("(")
                if paren_depth <= 0:
                    insert_pos = j + 1
                    break
            break

    new_lines.insert(insert_pos, "import os")

    fixed_content = "\n".join(new_lines)

    with open(full, "w") as fh:
        fh.write(fixed_content)

    try:
        py_compile.compile(full, doraise=True)
        fixed += 1
        print(f"  OK  {filepath}")
    except py_compile.PyCompileError as e:
        print(f"  ERR {filepath}: {str(e)[:120]}")

print(f"\nFixed {fixed}/{len(broken)} files")
