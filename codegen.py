"""
HolyC Code Generator
Walks the AST and emits HolyC source code targeting TempleOS.

PIC clause → HolyC type mapping:
  9(n)        → I64  (integer)
  9(n)V9(m)   → F64  (fixed-point approximated as float)
  X(n) / A(n) → U8[n+1] (char array)
  S9(n)       → I64  (signed)
"""

from __future__ import annotations
import re
from parser import (
    ProgramNode, DataItem, ParagraphNode,
    DisplayStmt, MoveStmt, ComputeStmt,
    AddStmt, SubtractStmt, MultiplyStmt, DivideStmt,
    IfStmt, PerformTimesStmt, PerformUntilStmt, PerformVaryingStmt,
    PerformParagraphStmt, EvaluateStmt, StopRunStmt, RawStmt,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _cobol_name_to_c(name: str) -> str:
    """Convert COBOL-STYLE-NAME to cobol_style_name."""
    return name.replace("-", "_").lower()


def _pic_to_holyc_type(pic: str) -> tuple[str, int | None]:
    """
    Returns (holyc_type, array_size_or_None).
    array_size is set only for string types.
    """
    pic = pic.strip().upper()
    # Strip leading S (signed)
    if pic.startswith("S"):
        pic = pic[1:]

    # Alphanumeric / char
    m = re.match(r'^X\((\d+)\)$', pic)
    if m: return ("U8", int(m.group(1)) + 1)
    if pic.startswith("X"): return ("U8", 32)

    m = re.match(r'^A\((\d+)\)$', pic)
    if m: return ("U8", int(m.group(1)) + 1)

    # Fixed-point (has V)
    if "V" in pic: return ("F64", None)

    # Integer
    m = re.match(r'^9\((\d+)\)$', pic)
    if m: return ("I64", None)
    if re.match(r'^9+$', pic): return ("I64", None)

    return ("I64", None)   # safe default


def _pic_default(pic: str) -> str:
    htype, arr = _pic_to_holyc_type(pic)
    if arr is not None: return '""'
    if htype == "F64":   return "0.0"
    return "0"


def _translate_condition(cond: str) -> str:
    """Translate a COBOL condition string to a HolyC expression."""
    cond = cond.strip()

    replacements = [
        (r'\bIS\s+NOT\s+EQUAL\s+TO\b', "!="),
        (r'\bIS\s+EQUAL\s+TO\b',        "=="),
        (r'\bIS\s+NOT\s+GREATER\s+THAN\b', "<="),
        (r'\bIS\s+NOT\s+LESS\s+THAN\b',    ">="),
        (r'\bIS\s+GREATER\s+THAN\b',     ">"),
        (r'\bIS\s+LESS\s+THAN\b',        "<"),
        (r'\bNOT\s+EQUAL\b',    "!="),
        (r'\bEQUAL\b',          "=="),
        (r'\bGREATER\b',        ">"),
        (r'\bLESS\b',           "<"),
        (r'\bAND\b',            "&&"),
        (r'\bOR\b',             "||"),
        (r'\bNOT\b',            "!"),
    ]
    for pat, repl in replacements:
        cond = re.sub(pat, repl, cond, flags=re.IGNORECASE)

    # Replace bare = with == (only when surrounded by identifiers/numbers)
    cond = re.sub(r'(?<![=!<>])=(?!=)', '==', cond)

    # Convert COBOL identifiers in the expression
    tokens = re.split(r'(\s+|==|!=|<=|>=|[<>!&|()]+)', cond)
    result = []
    for tok in tokens:
        stripped = tok.strip()
        if re.match(r'^[A-Za-z][A-Za-z0-9\-_]*$', stripped):
            result.append(_cobol_name_to_c(stripped))
        else:
            result.append(tok)
    return "".join(result)


def _translate_expr(expr: str) -> str:
    """Translate a COBOL arithmetic expression to HolyC."""
    # Simple: just convert identifiers and operators
    tokens = re.split(r'(\s+|[+\-*/()]+)', expr)
    result = []
    for tok in tokens:
        stripped = tok.strip()
        if re.match(r'^[A-Za-z][A-Za-z0-9\-_]*$', stripped):
            result.append(_cobol_name_to_c(stripped))
        else:
            result.append(tok)
    return "".join(result)


def _is_string_literal(v) -> bool:
    s = str(v)
    return s.startswith('"') or s.startswith("'")

def _val(v) -> str:
    """Format a value (string literal or identifier) for HolyC."""
    if v is None:
        return "0"
    s = str(v)
    # Already a string literal — keep as proper C string
    if s.startswith('"'):
        return s   # already has double quotes from lexer strip
    if s.startswith("'"):
        inner = s[1:-1] if len(s) >= 2 else s
        return f'"{inner}"'
    # Numeric?
    try:
        float(s)
        return s
    except ValueError:
        pass
    # COBOL figurative constants
    upper = s.upper()
    if upper in ("ZEROS", "ZEROES", "ZERO"):   return "0"
    if upper in ("SPACES", "SPACE"):            return '""'
    if upper in ("HIGH-VALUES", "HIGH-VALUE"):  return "0xFF"
    if upper in ("LOW-VALUES",  "LOW-VALUE"):   return "0"
    # Identifier
    return _cobol_name_to_c(s)


# ─── Generator ────────────────────────────────────────────────────────────────

class CodeGen:
    def __init__(self, program: ProgramNode):
        self.program = program
        self.indent_level = 0
        self.lines: list[str] = []
        # type info for variables (name → (holyc_type, array_size))
        self.var_types: dict[str, tuple[str, int | None]] = {}

    def _emit(self, text: str = ""):
        prefix = "  " * self.indent_level
        self.lines.append(prefix + text)

    def _indent(self):   self.indent_level += 1
    def _dedent(self):   self.indent_level = max(0, self.indent_level - 1)

    def generate(self) -> str:
        prog = self.program
        self._emit(f"// Generated by cobol2holyc")
        self._emit(f"// Program: {prog.name}")
        self._emit()
        self._emit('#include "HolyC.HC"')
        self._emit()

        # Global variable declarations
        if prog.data_items:
            self._emit("// === WORKING-STORAGE ===")
            self._gen_data_items(prog.data_items)
            self._emit()

        # Forward declarations for paragraphs
        if len(prog.paragraphs) > 1:
            self._emit("// === Forward declarations ===")
            for para in prog.paragraphs:
                self._emit(f"U0 {_cobol_name_to_c(para.name)}();")
            self._emit()

        # Paragraph bodies
        for para in prog.paragraphs:
            self._gen_paragraph(para)
            self._emit()

        # Entry point
        self._emit("// === Entry point ===")
        if prog.paragraphs:
            first = _cobol_name_to_c(prog.paragraphs[0].name)
            self._emit(f"{first}();")
        else:
            self._emit("// (no procedure division found)")

        return "\n".join(self.lines)

    # ── Data items ─────────────────────────────────────────────────────────────

    def _gen_data_items(self, items: list[DataItem], global_scope=True):
        for item in items:
            if not item:
                continue
            htype, arr = _pic_to_holyc_type(item.pic) if item.pic else ("I64", None)
            cname = _cobol_name_to_c(item.name)
            self.var_types[item.name.upper()] = (htype, arr)

            if item.pic == "" and item.children:
                # Group item — just a comment
                self._emit(f"// Group: {cname}")
                self._gen_data_items(item.children, global_scope)
                continue

            raw_default = item.value
            default = _val(raw_default) if raw_default is not None else _pic_default(item.pic)

            if arr is not None:
                size = arr
                # For string arrays, initialise inline if we have a value
                if raw_default is not None:
                    self._emit(f'U8 {cname}[{size}] = {default};')
                else:
                    self._emit(f'U8 {cname}[{size}] = "";')
            else:
                self._emit(f"{htype} {cname} = {default};")

    # ── Paragraph ──────────────────────────────────────────────────────────────

    def _gen_paragraph(self, para: ParagraphNode):
        cname = _cobol_name_to_c(para.name)
        self._emit(f"U0 {cname}()")
        self._emit("{")
        self._indent()
        for stmt in para.stmts:
            self._gen_stmt(stmt)
        self._dedent()
        self._emit("}")

    # ── Statements ─────────────────────────────────────────────────────────────

    def _gen_stmt(self, stmt):
        if stmt is None:
            return
        t = type(stmt)
        if t == DisplayStmt:       self._gen_display(stmt)
        elif t == MoveStmt:        self._gen_move(stmt)
        elif t == ComputeStmt:     self._gen_compute(stmt)
        elif t == AddStmt:         self._gen_add(stmt)
        elif t == SubtractStmt:    self._gen_subtract(stmt)
        elif t == MultiplyStmt:    self._gen_multiply(stmt)
        elif t == DivideStmt:      self._gen_divide(stmt)
        elif t == IfStmt:          self._gen_if(stmt)
        elif t == PerformTimesStmt:    self._gen_perform_times(stmt)
        elif t == PerformUntilStmt:    self._gen_perform_until(stmt)
        elif t == PerformVaryingStmt:  self._gen_perform_varying(stmt)
        elif t == PerformParagraphStmt:self._gen_perform_paragraph(stmt)
        elif t == EvaluateStmt:    self._gen_evaluate(stmt)
        elif t == StopRunStmt:     self._emit("exit(0);")
        elif t == RawStmt:         self._emit(f"// (unhandled): {stmt.text}")

    def _gen_display(self, stmt: DisplayStmt):
        for item in stmt.items:
            v = _val(item)
            htype, arr = self.var_types.get(str(item).upper(), (None, None))
            if _is_string_literal(item):
                self._emit(f'Print("%s\\n", {v});')
            elif htype == "F64":
                self._emit(f'Print("%f\\n", {v});')
            elif arr is not None:
                self._emit(f'Print("%s\\n", {v});')
            else:
                self._emit(f'Print("%d\\n", {v});')

    def _gen_move(self, stmt: MoveStmt):
        src = _val(stmt.source)
        dst = _cobol_name_to_c(stmt.target)
        htype, arr = self.var_types.get(stmt.target.upper(), (None, None))
        if arr is not None:
            self._emit(f'StrCpy({dst}, {src});')
        else:
            self._emit(f"{dst} = {src};")

    def _gen_compute(self, stmt: ComputeStmt):
        target = _cobol_name_to_c(stmt.target)
        expr   = _translate_expr(stmt.expr)
        self._emit(f"{target} = {expr};")

    def _gen_add(self, stmt: AddStmt):
        target = _cobol_name_to_c(stmt.target)
        ops = " + ".join(_val(o) for o in stmt.operands)
        self._emit(f"{target} = {target} + {ops};")

    def _gen_subtract(self, stmt: SubtractStmt):
        target = _cobol_name_to_c(stmt.target)
        ops = " + ".join(_val(o) for o in stmt.operands)
        self._emit(f"{target} = {target} - ({ops});")

    def _gen_multiply(self, stmt: MultiplyStmt):
        target = _cobol_name_to_c(stmt.target)
        left   = _val(stmt.left)
        right  = _val(stmt.right)
        self._emit(f"{target} = {left} * {right};")

    def _gen_divide(self, stmt: DivideStmt):
        target   = _cobol_name_to_c(stmt.target)
        dividend = _val(stmt.dividend)
        divisor  = _val(stmt.divisor)
        self._emit(f"{target} = {dividend} / {divisor};")
        if stmt.remainder:
            rem = _cobol_name_to_c(stmt.remainder)
            self._emit(f"{rem} = {dividend} %% {divisor};")

    def _gen_if(self, stmt: IfStmt):
        cond = _translate_condition(stmt.condition)
        self._emit(f"if ({cond})")
        self._emit("{")
        self._indent()
        for s in stmt.then_stmts: self._gen_stmt(s)
        self._dedent()
        self._emit("}")
        if stmt.else_stmts:
            self._emit("else")
            self._emit("{")
            self._indent()
            for s in stmt.else_stmts: self._gen_stmt(s)
            self._dedent()
            self._emit("}")

    def _gen_perform_times(self, stmt: PerformTimesStmt):
        count = _val(stmt.count)
        self._emit(f"I64 _i;")
        self._emit(f"for (_i = 0; _i < {count}; _i++)")
        self._emit("{")
        self._indent()
        for s in stmt.stmts: self._gen_stmt(s)
        self._dedent()
        self._emit("}")

    def _gen_perform_until(self, stmt: PerformUntilStmt):
        cond = _translate_condition(stmt.condition)
        self._emit(f"while (!({cond}))")
        self._emit("{")
        self._indent()
        for s in stmt.stmts: self._gen_stmt(s)
        self._dedent()
        self._emit("}")

    def _gen_perform_varying(self, stmt: PerformVaryingStmt):
        var     = _cobol_name_to_c(stmt.var)
        from_v  = _val(stmt.from_val)
        by_v    = _val(stmt.by_val)
        cond    = _translate_condition(stmt.condition)
        self._emit(f"for ({var} = {from_v}; !({cond}); {var} += {by_v})")
        self._emit("{")
        self._indent()
        for s in stmt.stmts: self._gen_stmt(s)
        self._dedent()
        self._emit("}")

    def _gen_perform_paragraph(self, stmt: PerformParagraphStmt):
        cname = _cobol_name_to_c(stmt.paragraph)
        self._emit(f"{cname}();")
        if stmt.thru:
            self._emit(f"// (THRU {stmt.thru} not fully supported)")

    def _gen_evaluate(self, stmt: EvaluateStmt):
        first = True
        for (val, stmts) in stmt.whens:
            if val == "OTHER":
                self._emit("else")
            else:
                kw = "if" if first else "else if"
                cval = _translate_condition(val)
                if stmt.subject != "TRUE":
                    subj = _cobol_name_to_c(stmt.subject)
                    self._emit(f"{kw} ({subj} == {cval})")
                else:
                    # EVALUATE TRUE: condition is a full boolean expression
                    self._emit(f"{kw} ({cval})")
                first = False
            self._emit("{")
            self._indent()
            for s in stmts: self._gen_stmt(s)
            self._dedent()
            self._emit("}")


def generate(program: ProgramNode) -> str:
    return CodeGen(program).generate()
