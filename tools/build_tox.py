"""Embed UTF-8 Python DAT sources with LF newlines and verify the rebuilt TOX."""

import argparse
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile


TEXT_HEADER = b"2\n*" + struct.pack(">IIIII", 1, 1, 1, 1, 2)


def text_payload(path):
    data = path.read_bytes()
    if not data.startswith(TEXT_HEADER) or len(data) < 27:
        raise ValueError(f"Unsupported Text DAT encoding: {path}")
    size = struct.unpack(">I", data[23:27])[0]
    if len(data) != 27 + size:
        raise ValueError(f"Text DAT length mismatch: {path}")
    return data[27:]


def sources(expanded, repo):
    result = {}
    for parm in expanded.rglob("*.parm"):
        match = re.search(r"^file \d+ (py/[^\r\n]+)$", parm.read_text(), re.MULTILINE)
        if match is None:
            continue
        source = (repo / match[1]).resolve()
        if not source.is_relative_to(repo):
            raise ValueError(f"Source is outside repository: {source}")
        text = parm.with_suffix(".text")
        text_payload(text)
        result[text.relative_to(expanded)] = source.read_text(encoding="utf-8").encode("utf-8")
    if not result:
        raise ValueError("No Python DAT references found")
    return result


def expand(binary, package):
    expanded = Path(str(package) + ".dir")
    toc = Path(str(package) + ".toc")
    if expanded.exists() or toc.exists():
        raise ValueError(f"Expansion output already exists for {package}")
    result = subprocess.run([str(binary), str(package)], capture_output=True, text=True)
    if not expanded.is_dir() or not toc.is_file():
        raise RuntimeError(f"toeexpand did not produce a package: {result.stderr}")
    declared = {line for line in toc.read_text().splitlines() if line and not line.startswith('#')}
    actual = {path.relative_to(expanded).as_posix() for path in expanded.rglob('*') if path.is_file()}
    if not declared or declared != actual:
        raise RuntimeError("Expanded package does not match its table of contents")
    return expanded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--td-bin", type=Path, required=True)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--output", type=Path, help="Write only after round-trip verification")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    package = (args.package or repo / "rship.tox").resolve()
    with tempfile.TemporaryDirectory(prefix="rship-tox-") as folder:
        staged = Path(folder) / "rship.tox"
        shutil.copyfile(package, staged)
        expanded = expand(args.td_bin / "toeexpand.exe", staged)
        expected = sources(expanded, repo)
        if args.output is None:
            mismatches = [str(path) for path, content in expected.items()
                          if text_payload(expanded / path) != content]
            if mismatches:
                raise ValueError("Embedded sources differ: " + ", ".join(mismatches))
            print(f"Verified {len(expected)} embedded Python DATs against source")
            return
        original = {path.relative_to(expanded): path.read_bytes()
                    for path in expanded.rglob("*") if path.is_file()}
        for path, content in expected.items():
            (expanded / path).write_bytes(TEXT_HEADER + struct.pack(">I", len(content)) + content)
        subprocess.run([str(args.td_bin / "toecollapse.exe"), str(staged)],
                       check=True, capture_output=True)
        verify_package = Path(folder) / "verify.tox"
        shutil.copyfile(staged, verify_package)
        verified = expand(args.td_bin / "toeexpand.exe", verify_package)
        actual_files = {path.relative_to(verified) for path in verified.rglob("*") if path.is_file()}
        if actual_files != set(original):
            raise ValueError("Rebuilt package changed the operator file inventory")
        for path, before in original.items():
            if path in expected:
                if text_payload(verified / path) != expected[path]:
                    raise ValueError(f"Embedded source verification failed: {path}")
            elif (verified / path).read_bytes() != before:
                raise ValueError(f"Unrelated package data changed: {path}")
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(staged, output)
        print(f"Built {output}; verified {len(expected)} Python DATs and preserved all other package data")


if __name__ == "__main__":
    main()
