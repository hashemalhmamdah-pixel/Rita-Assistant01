"""Dependency-free static audit for Rita's modules and requirements.

This is a conservative local substitute for pyflakes/Flake8 in offline build
containers. It checks syntax, likely undefined globals, unused imports,
unsafe dynamic execution, and declared third-party import dependencies.
"""
from __future__ import annotations

import ast
import builtins
import re
import symtable
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE_FILES = ("main.py", "voice.py", "system_control.py", "ai_brain.py", "local_commands.py")
REQUIREMENTS = ROOT / "requirements.txt"
MODULE_TO_DISTRIBUTION = {
    "dotenv": "python-dotenv",
    "google": "google-genai",
    "groq": "groq",
    "customtkinter": "customtkinter",
    "speech_recognition": "SpeechRecognition",
    "edge_tts": "edge-tts",
    "pygame": "pygame-ce",
    "sounddevice": "sounddevice",
    "pycaw": "pycaw",
    "comtypes": "comtypes",
    "win32api": "pywin32",
    "win32com": "pywin32",
    "screen_brightness_control": "screen-brightness-control",
    "pystray": "pystray",
    "PIL": "Pillow",
}
LOCAL_MODULES = set(SOURCE_FILES[index][:-3] for index in range(len(SOURCE_FILES)))
STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"winreg"}


def normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def read_requirements() -> set[str]:
    declared: set[str] = set()
    for raw_line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)", line)
        if match:
            declared.add(normalized_name(match.group(1)))
    return declared


def audit_file(
    path: Path, declared: set[str], problems: list[str], warnings: list[str]
) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    compile(tree, str(path), "exec")
    module_table = symtable.symtable(source, str(path), "exec")
    module_names = set(module_table.get_identifiers())

    for line_number, line in enumerate(source.splitlines(), start=1):
        if len(line) > 100:
            warnings.append(
                f"{path.name}:{line_number}: line is {len(line)} characters (limit 100)"
            )
        if line.rstrip() != line:
            warnings.append(f"{path.name}:{line_number}: trailing whitespace")
        if "\t" in line:
            warnings.append(f"{path.name}:{line_number}: tab character found")

    loaded_names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    imported_names: dict[str, int] = {}
    imported_modules: dict[str, int] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".", 1)[0]
                imported_name = alias.asname or root_name
                imported_names[imported_name] = node.lineno
                imported_modules[root_name] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_name = node.module.split(".", 1)[0]
                imported_modules[root_name] = node.lineno
                for alias in node.names:
                    if alias.name != "*":
                        imported_names[alias.asname or alias.name] = node.lineno
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"eval", "exec"}:
                problems.append(f"{path.name}:{node.lineno}: {node.func.id}() is not permitted")

    for name, line in imported_names.items():
        if name not in loaded_names and name != "annotations":
            problems.append(f"{path.name}:{line}: unused import {name}")

    def check_scope(table: symtable.SymbolTable) -> None:
        for symbol in table.get_symbols():
            if symbol.is_global() and symbol.is_referenced():
                name = symbol.get_name()
                if name not in module_names and name not in {"__file__", "__name__", "__package__"} and not hasattr(builtins, name):
                    problems.append(
                        f"{path.name}:{table.get_name()}: possible undefined global {name}"
                    )
        for child in table.get_children():
            check_scope(child)

    check_scope(module_table)

    def check_unused_locals(table: symtable.SymbolTable) -> None:
        if table.get_type() == "function":
            for symbol in table.get_symbols():
                name = symbol.get_name()
                if (
                    symbol.is_local()
                    and symbol.is_assigned()
                    and not symbol.is_referenced()
                    and not symbol.is_parameter()
                    and name != "_"
                    and not name.startswith("__")
                ):
                    warnings.append(
                        f"{path.name}:{table.get_name()}: possibly unused local {name}"
                    )
        for child in table.get_children():
            check_unused_locals(child)

    check_unused_locals(module_table)

    for module_name, line in imported_modules.items():
        if module_name in STDLIB or module_name in LOCAL_MODULES:
            continue
        distribution = MODULE_TO_DISTRIBUTION.get(module_name)
        if distribution is None:
            problems.append(
                f"{path.name}:{line}: external import {module_name} has no dependency mapping"
            )
        elif normalized_name(distribution) not in declared:
            problems.append(
                f"{path.name}:{line}: {module_name} requires {distribution}, missing from requirements.txt"
            )


def main() -> int:
    problems: list[str] = []
    warnings: list[str] = []
    declared = read_requirements()
    for filename in SOURCE_FILES:
        audit_file(ROOT / filename, declared, problems, warnings)
    print(f"Static audit: {len(SOURCE_FILES)} requested modules inspected.")
    if warnings:
        print("\nStyle / maintenance warnings (non-blocking):")
        print("\n".join(warnings))
    if problems:
        print("\nBlocking findings:")
        print("\n".join(problems))
        return 1
    print("PASS: syntax, global-name, import-use, unsafe-execution and requirements checks found no blocking issues.")
    print("Note: style warnings are reported but do not block tests; hardware/Windows-only lazy imports are checked against requirements.txt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
