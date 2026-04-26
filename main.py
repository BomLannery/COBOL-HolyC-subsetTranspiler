#!/usr/bin/env python3
"""
cobol2holyc — COBOL → HolyC transpiler (proof of concept)

Usage:
  python main.py input.cob              # prints HolyC to stdout
  python main.py input.cob -o out.HC    # writes to file
  python main.py --demo                 # run built-in demo programs
"""

import sys
import argparse
from parser import parse
from codegen import generate

# ─── Built-in demo programs ───────────────────────────────────────────────────

DEMOS = {
    "hello": (
        "Hello World",
        """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
       PROCEDURE DIVISION.
           DISPLAY "HELLO, WORLD".
           STOP RUN.
"""
    ),

    "counter": (
        "Counter with PERFORM TIMES",
        """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COUNTER.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-COUNT PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
           PERFORM 5 TIMES
               ADD 1 TO WS-COUNT
               DISPLAY WS-COUNT
           END-PERFORM.
           STOP RUN.
"""
    ),

    "fizzbuzz": (
        "FizzBuzz via PERFORM VARYING + EVALUATE",
        """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FIZZBUZZ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-I    PIC 9(3) VALUE 1.
       01 WS-REM3 PIC 9(3) VALUE 0.
       01 WS-REM5 PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
           PERFORM VARYING WS-I FROM 1 BY 1
                   UNTIL WS-I > 20
               COMPUTE WS-REM3 = FUNCTION MOD(WS-I, 3)
               COMPUTE WS-REM5 = FUNCTION MOD(WS-I, 5)
               EVALUATE TRUE
                   WHEN WS-REM3 = 0 AND WS-REM5 = 0
                       DISPLAY "FIZZBUZZ"
                   WHEN WS-REM3 = 0
                       DISPLAY "FIZZ"
                   WHEN WS-REM5 = 0
                       DISPLAY "BUZZ"
                   WHEN OTHER
                       DISPLAY WS-I
               END-EVALUATE
           END-PERFORM.
           STOP RUN.
"""
    ),

    "arithmetic": (
        "Basic arithmetic operations",
        """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITH.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A     PIC 9(5) VALUE 100.
       01 WS-B     PIC 9(5) VALUE 7.
       01 WS-RESULT PIC 9(10) VALUE 0.
       01 WS-REM    PIC 9(5)  VALUE 0.
       PROCEDURE DIVISION.
           ADD WS-A TO WS-RESULT.
           DISPLAY WS-RESULT.
           SUBTRACT 10 FROM WS-RESULT.
           DISPLAY WS-RESULT.
           MULTIPLY WS-A BY WS-B GIVING WS-RESULT.
           DISPLAY WS-RESULT.
           DIVIDE WS-A BY WS-B GIVING WS-RESULT REMAINDER WS-REM.
           DISPLAY WS-RESULT.
           DISPLAY WS-REM.
           STOP RUN.
"""
    ),

    "greeting": (
        "MOVE and conditional IF",
        """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GREET.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-NAME   PIC X(20) VALUE "TEMPLER".
       01 WS-SCORE  PIC 9(3)  VALUE 85.
       01 WS-GRADE  PIC X(2)  VALUE SPACES.
       PROCEDURE DIVISION.
           DISPLAY "HELLO, ".
           DISPLAY WS-NAME.
           IF WS-SCORE >= 90
               MOVE "A" TO WS-GRADE
           ELSE
               IF WS-SCORE >= 80
                   MOVE "B" TO WS-GRADE
               ELSE
                   MOVE "C" TO WS-GRADE
               END-IF
           END-IF.
           DISPLAY "GRADE: ".
           DISPLAY WS-GRADE.
           STOP RUN.
"""
    ),
}


# ─── Main ─────────────────────────────────────────────────────────────────────

def transpile(source: str) -> str:
    ast = parse(source)
    return generate(ast)


def run_demo(key: str):
    title, source = DEMOS[key]
    print(f"\n{'='*60}")
    print(f"  DEMO: {title}")
    print(f"{'='*60}")
    print("\n--- COBOL SOURCE ---")
    print(source)
    print("--- HolyC OUTPUT ---")
    result = transpile(source)
    print(result)
    print()


def main():
    ap = argparse.ArgumentParser(description="COBOL → HolyC transpiler (PoC)")
    ap.add_argument("input", nargs="?", help="COBOL source file")
    ap.add_argument("-o", "--output", help="Output file (default: stdout)")
    ap.add_argument("--demo", action="store_true", help="Run all built-in demos")
    ap.add_argument("--demo-name", choices=list(DEMOS.keys()),
                    help="Run a specific demo")
    args = ap.parse_args()

    if args.demo:
        for key in DEMOS:
            run_demo(key)
        return

    if args.demo_name:
        run_demo(args.demo_name)
        return

    if not args.input:
        ap.print_help()
        sys.exit(1)

    with open(args.input, "r") as f:
        source = f.read()

    result = transpile(source)

    if args.output:
        with open(args.output, "w") as f:
            f.write(result)
        print(f"Written to {args.output}")
    else:
        print(result)


if __name__ == "__main__":
    main()
