from __future__ import annotations

import argparse

from ariadion import Program, run


def build_demo(name: str) -> Program:
    if name != "bell":
        raise ValueError(f"unknown demo: {name}")
    return Program(2, name="bell").h(0).cx(0, 1)


def main() -> int:
    parser = argparse.ArgumentParser(prog="ariadion", description="Ariadion quantum tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="run a bundled demonstration")
    demo.add_argument("name", choices=["bell"])

    args = parser.parse_args()
    if args.command == "demo":
        result = run(build_demo(args.name))
        print(result.circuit)
        print()
        print(result.report)
        return 0
    return 1
