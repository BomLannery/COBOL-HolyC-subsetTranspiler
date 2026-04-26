"""
COBOL Parser — builds an AST from the token stream.

Covers:
  IDENTIFICATION DIVISION  → ProgramNode
  WORKING-STORAGE SECTION  → DataItem nodes
  PROCEDURE DIVISION       → statements:
      DISPLAY, MOVE, COMPUTE, ADD, SUBTRACT, MULTIPLY, DIVIDE,
      IF/ELSE/END-IF, PERFORM … END-PERFORM, PERFORM … TIMES,
      PERFORM … UNTIL, EVALUATE/WHEN/END-EVALUATE, STOP RUN
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from lexer import Token, TT, tokenize


# ─── AST Node types ──────────────────────────────────────────────────────────

@dataclass
class ProgramNode:
    name: str
    data_items: list[DataItem]
    paragraphs: list[ParagraphNode]

@dataclass
class DataItem:
    level: int
    name: str
    pic: str          # raw PIC string, e.g. "9(5)", "X(20)", "9(7)V99"
    value: Any        # initial value or None
    children: list[DataItem] = field(default_factory=list)

@dataclass
class ParagraphNode:
    name: str
    stmts: list

# Statements
@dataclass
class DisplayStmt:
    items: list   # list of str/identifiers

@dataclass
class MoveStmt:
    source: Any
    target: str

@dataclass
class ComputeStmt:
    target: str
    expr: str     # raw expression string

@dataclass
class AddStmt:
    operands: list
    target: str

@dataclass
class SubtractStmt:
    operands: list
    target: str

@dataclass
class MultiplyStmt:
    left: Any
    right: Any
    target: str

@dataclass
class DivideStmt:
    dividend: Any
    divisor: Any
    target: str
    remainder: str | None

@dataclass
class IfStmt:
    condition: str
    then_stmts: list
    else_stmts: list

@dataclass
class PerformTimesStmt:
    count: Any
    stmts: list

@dataclass
class PerformUntilStmt:
    condition: str
    stmts: list

@dataclass
class PerformVaryingStmt:
    var: str
    from_val: Any
    by_val: Any
    condition: str
    stmts: list

@dataclass
class PerformParagraphStmt:
    paragraph: str
    thru: str | None = None

@dataclass
class EvaluateStmt:
    subject: str
    whens: list     # list of (value_or_OTHER, [stmts])

@dataclass
class StopRunStmt:
    pass

@dataclass
class RawStmt:
    text: str       # fallback for unrecognised statements


# ─── Parser ──────────────────────────────────────────────────────────────────

class ParseError(Exception):
    pass


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    # ── Primitives ────────────────────────────────────────────────────────────

    def peek(self, offset=0) -> Token:
        i = self.pos + offset
        if i >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[i]

    def advance(self) -> Token:
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def at(self, *types) -> bool:
        return self.peek().type in types

    def eat(self, *types) -> Token:
        if self.peek().type in types:
            return self.advance()
        raise ParseError(
            f"Expected {[t.name for t in types]}, got {self.peek()} at line {self.peek().line}"
        )

    def skip_dots(self):
        while self.at(TT.DOT):
            self.advance()

    def skip_unknown(self):
        while self.at(TT.UNKNOWN):
            self.advance()

    def at_stmt_keyword(self) -> bool:
        return self.peek().type in (
            TT.DISPLAY, TT.MOVE, TT.COMPUTE, TT.ADD, TT.SUBTRACT,
            TT.MULTIPLY, TT.DIVIDE, TT.IF, TT.PERFORM, TT.EVALUATE,
            TT.STOP, TT.EOF,
            TT.IDENTIFICATION, TT.DATA, TT.PROCEDURE, TT.ENVIRONMENT,
            TT.END_IF, TT.END_PERFORM, TT.END_EVALUATE, TT.ELSE,
            TT.WHEN,
        )

    def at_division(self) -> bool:
        return self.peek(1).type == TT.DIVISION

    # ── Top-level ─────────────────────────────────────────────────────────────

    def parse(self) -> ProgramNode:
        name = "UNKNOWN"
        data_items: list[DataItem] = []
        paragraphs: list[ParagraphNode] = []

        while not self.at(TT.EOF):
            if self.at(TT.IDENTIFICATION):
                name = self._parse_id_division()
            elif self.at(TT.ENVIRONMENT):
                self._skip_division()
            elif self.at(TT.DATA):
                data_items = self._parse_data_division()
            elif self.at(TT.PROCEDURE):
                paragraphs = self._parse_procedure_division()
            else:
                self.advance()

        return ProgramNode(name=name, data_items=data_items, paragraphs=paragraphs)

    # ── IDENTIFICATION DIVISION ───────────────────────────────────────────────

    def _parse_id_division(self) -> str:
        self.eat(TT.IDENTIFICATION)
        self.eat(TT.DIVISION)
        self.skip_dots()
        name = "UNKNOWN"
        while not self.at(TT.EOF) and not self.at_division():
            if self.at(TT.PROGRAM_ID):
                self.advance()
                self.skip_dots()
                if self.at(TT.IDENTIFIER):
                    name = self.advance().value
                self.skip_dots()
            else:
                self.advance()
        return name

    def _skip_division(self):
        self.advance()  # division keyword
        while not self.at(TT.EOF) and not self.at_division():
            self.advance()

    # ── DATA DIVISION ─────────────────────────────────────────────────────────

    def _parse_data_division(self) -> list[DataItem]:
        self.eat(TT.DATA)
        self.eat(TT.DIVISION)
        self.skip_dots()
        items = []
        while not self.at(TT.EOF) and not self.at_division():
            if self.at(TT.WORKING_STORAGE):
                self.advance()
                self.eat(TT.SECTION)
                self.skip_dots()
                items.extend(self._parse_data_items())
            else:
                # other sections (FILE, LOCAL-STORAGE) — skip
                self.advance()
        return items

    def _parse_data_items(self) -> list[DataItem]:
        items = []
        while self.at(TT.LEVEL_NUMBER):
            item = self._parse_one_data_item()
            if item:
                items.append(item)
        return items

    def _parse_one_data_item(self) -> DataItem | None:
        level_tok = self.eat(TT.LEVEL_NUMBER)
        level = int(level_tok.value)

        if not self.at(TT.IDENTIFIER):
            # FILLER or malformed — skip to next dot
            while not self.at(TT.DOT) and not self.at(TT.EOF):
                self.advance()
            self.skip_dots()
            return None

        name = self.advance().value
        pic = ""
        value = None

        while not self.at(TT.DOT) and not self.at(TT.LEVEL_NUMBER) and not self.at(TT.EOF):
            if self.at(TT.PIC, TT.PICTURE):
                self.advance()
                # skip optional IS
                if self.at(TT.IDENTIFIER) and self.peek().value.upper() == "IS":
                    self.advance()
                # collect pic clause tokens until VALUE or DOT or level
                pic_parts = []
                while not self.at(TT.DOT) and not self.at(TT.VALUE) \
                        and not self.at(TT.LEVEL_NUMBER) and not self.at(TT.EOF):
                    # stop if we hit a statement keyword that isn't part of PIC
                    if self.peek().type not in (
                        TT.IDENTIFIER, TT.NUMBER_LIT, TT.LEVEL_NUMBER,
                        TT.UNKNOWN,
                    ):
                        break
                    pic_parts.append(self.advance().value)
                pic = "".join(pic_parts)
            elif self.at(TT.VALUE):
                self.advance()
                if self.at(TT.STRING_LIT):
                    value = self.advance().value
                elif self.at(TT.NUMBER_LIT, TT.LEVEL_NUMBER):
                    value = self.advance().value
                elif self.at(TT.IDENTIFIER):
                    value = self.advance().value  # e.g. ZEROS, SPACES
            else:
                self.advance()

        self.skip_dots()
        return DataItem(level=level, name=name.upper(), pic=pic.upper(), value=value)

    # ── PROCEDURE DIVISION ────────────────────────────────────────────────────

    def _parse_procedure_division(self) -> list[ParagraphNode]:
        self.eat(TT.PROCEDURE)
        self.eat(TT.DIVISION)
        self.skip_dots()
        paragraphs = []

        # Check if there are explicit paragraph names or just raw statements
        if self._looks_like_paragraph():
            while not self.at(TT.EOF) and not self.at_division():
                para = self._parse_paragraph()
                if para:
                    paragraphs.append(para)
        else:
            # Wrap everything in implicit MAIN paragraph
            stmts = self._parse_statements(stop_at=set())
            paragraphs.append(ParagraphNode(name="MAIN", stmts=stmts))

        return paragraphs

    def _looks_like_paragraph(self) -> bool:
        """Heuristic: next token is IDENTIFIER followed by DOT."""
        return (self.at(TT.IDENTIFIER) and self.peek(1).type == TT.DOT)

    def _parse_paragraph(self) -> ParagraphNode | None:
        if not self.at(TT.IDENTIFIER):
            self.advance()
            return None
        name = self.advance().value.upper()
        self.skip_dots()
        stmts = self._parse_statements(stop_at={TT.IDENTIFIER})
        return ParagraphNode(name=name, stmts=stmts)

    # ── Statement parsing ─────────────────────────────────────────────────────

    STOP_TYPES = {
        TT.END_IF, TT.END_PERFORM, TT.END_EVALUATE,
        TT.ELSE, TT.WHEN, TT.EOF,
        TT.IDENTIFICATION, TT.DATA, TT.PROCEDURE, TT.ENVIRONMENT,
    }

    def _parse_statements(self, stop_at: set) -> list:
        stmts = []
        combined_stop = self.STOP_TYPES | stop_at
        while not self.at(TT.EOF):
            tt = self.peek().type
            if tt in combined_stop:
                break
            # paragraph boundary check
            if tt == TT.IDENTIFIER and self.peek(1).type == TT.DOT:
                break
            stmt = self._parse_one_stmt()
            if stmt:
                stmts.append(stmt)
        return stmts

    def _parse_one_stmt(self):
        tt = self.peek().type

        if tt == TT.DISPLAY:   return self._parse_display()
        if tt == TT.MOVE:      return self._parse_move()
        if tt == TT.COMPUTE:   return self._parse_compute()
        if tt == TT.ADD:       return self._parse_add()
        if tt == TT.SUBTRACT:  return self._parse_subtract()
        if tt == TT.MULTIPLY:  return self._parse_multiply()
        if tt == TT.DIVIDE:    return self._parse_divide()
        if tt == TT.IF:        return self._parse_if()
        if tt == TT.PERFORM:   return self._parse_perform()
        if tt == TT.EVALUATE:  return self._parse_evaluate()
        if tt == TT.STOP:
            self.advance()
            if self.at(TT.RUN): self.advance()
            self.skip_dots()
            return StopRunStmt()

        # Skip unrecognised tokens / dots
        raw = self.advance().value
        self.skip_dots()
        return None

    def _collect_value(self):
        """Return string/number/identifier token value."""
        if self.at(TT.STRING_LIT, TT.NUMBER_LIT, TT.IDENTIFIER, TT.LEVEL_NUMBER):
            return self.advance().value
        return None

    def _parse_display(self):
        self.eat(TT.DISPLAY)
        items = []
        while not self.at_stmt_keyword() and not self.at(TT.DOT) and not self.at(TT.EOF):
            v = self._collect_value()
            if v is not None:
                items.append(v)
            else:
                self.advance()
        self.skip_dots()
        return DisplayStmt(items=items)

    def _parse_move(self):
        self.eat(TT.MOVE)
        source = self._collect_value()
        if self.at(TT.TO): self.advance()
        target = self._collect_value() or "?"
        self.skip_dots()
        return MoveStmt(source=source, target=target.upper())

    def _parse_compute(self):
        self.eat(TT.COMPUTE)
        target = (self._collect_value() or "?").upper()
        if self.at(TT.EQUAL_SIGN): self.advance()
        parts = []
        while not self.at_stmt_keyword() and not self.at(TT.DOT) and not self.at(TT.EOF):
            parts.append(self.advance().value)
        self.skip_dots()
        return ComputeStmt(target=target, expr=" ".join(parts))

    def _parse_add(self):
        self.eat(TT.ADD)
        operands = []
        while not self.at(TT.TO) and not self.at_stmt_keyword() \
                and not self.at(TT.DOT) and not self.at(TT.EOF):
            v = self._collect_value()
            if v: operands.append(v)
            else: self.advance()
        target = "?"
        if self.at(TT.TO):
            self.advance()
            target = (self._collect_value() or "?").upper()
        self.skip_dots()
        return AddStmt(operands=operands, target=target)

    def _parse_subtract(self):
        self.eat(TT.SUBTRACT)
        operands = []
        while not self.at(TT.FROM) and not self.at_stmt_keyword() \
                and not self.at(TT.DOT) and not self.at(TT.EOF):
            v = self._collect_value()
            if v: operands.append(v)
            else: self.advance()
        target = "?"
        if self.at(TT.FROM):
            self.advance()
            target = (self._collect_value() or "?").upper()
        self.skip_dots()
        return SubtractStmt(operands=operands, target=target)

    def _parse_multiply(self):
        self.eat(TT.MULTIPLY)
        left  = self._collect_value() or "?"
        # consume BY (could be TT.BY or absorbed as IDENTIFIER)
        if self.at(TT.BY) or (self.at(TT.IDENTIFIER) and self.peek().value.upper() == "BY"):
            self.advance()
        right  = self._collect_value() or "?"
        target = right
        if self.at(TT.GIVING):
            self.advance()
            target = (self._collect_value() or "?").upper()
        self.skip_dots()
        return MultiplyStmt(left=left, right=right, target=target.upper())

    def _parse_divide(self):
        self.eat(TT.DIVIDE)
        dividend = self._collect_value() or "?"
        # consume INTO or BY (may appear as IDENTIFIER or UNKNOWN keyword)
        if self.at(TT.BY) or self.at(TT.FROM) or \
                (self.at(TT.IDENTIFIER) and self.peek().value.upper() in ("BY", "INTO")):
            self.advance()
        divisor = self._collect_value() or "?"
        target = dividend   # default target for DIVIDE A INTO B (modifies B)
        remainder = None
        if self.at(TT.GIVING):
            self.advance()
            target = (self._collect_value() or "?").upper()
        if self.at(TT.REMAINDER):
            self.advance()
            remainder = (self._collect_value() or "?").upper()
        self.skip_dots()
        return DivideStmt(dividend=dividend, divisor=divisor,
                          target=target.upper(), remainder=remainder)

    def _parse_if(self):
        self.eat(TT.IF)
        cond_parts = []
        while not self.at_stmt_keyword() and not self.at(TT.DOT) and not self.at(TT.EOF):
            cond_parts.append(self.peek().value)
            self.advance()
        self.skip_dots()
        then_stmts = self._parse_statements(stop_at={TT.ELSE, TT.END_IF})
        else_stmts = []
        if self.at(TT.ELSE):
            self.advance()
            self.skip_dots()
            else_stmts = self._parse_statements(stop_at={TT.END_IF})
        if self.at(TT.END_IF):
            self.advance()
        self.skip_dots()
        return IfStmt(condition=" ".join(cond_parts),
                      then_stmts=then_stmts,
                      else_stmts=else_stmts)

    def _parse_perform(self):
        self.eat(TT.PERFORM)

        # PERFORM paragraph [THRU paragraph]
        if self.at(TT.IDENTIFIER) and not self.peek(1).type in (
                TT.TIMES, TT.UNTIL, TT.VARYING, TT.DOT):
            para = self.advance().value.upper()
            thru = None
            if self.at(TT.THRU, TT.THROUGH):
                self.advance()
                thru = (self._collect_value() or "?").upper()
            self.skip_dots()
            return PerformParagraphStmt(paragraph=para, thru=thru)

        # PERFORM n TIMES … END-PERFORM
        if self.peek(1).type == TT.TIMES or \
                (self.at(TT.NUMBER_LIT) and self.peek(1).type == TT.TIMES):
            count = self._collect_value()
            self.eat(TT.TIMES)
            self.skip_dots()
            stmts = self._parse_statements(stop_at={TT.END_PERFORM})
            if self.at(TT.END_PERFORM): self.advance()
            self.skip_dots()
            return PerformTimesStmt(count=count, stmts=stmts)

        # PERFORM VARYING
        if self.at(TT.VARYING):
            self.advance()
            var = (self._collect_value() or "IDX").upper()
            from_val = "1"
            by_val   = "1"
            cond_parts = []
            if self.at(TT.FROM): self.advance(); from_val = self._collect_value() or "1"
            if self.at(TT.BY):   self.advance(); by_val   = self._collect_value() or "1"
            if self.at(TT.UNTIL):
                self.advance()
                while not self.at_stmt_keyword() and not self.at(TT.DOT) \
                        and not self.at(TT.EOF):
                    cond_parts.append(self.peek().value); self.advance()
            self.skip_dots()
            stmts = self._parse_statements(stop_at={TT.END_PERFORM})
            if self.at(TT.END_PERFORM): self.advance()
            self.skip_dots()
            return PerformVaryingStmt(
                var=var, from_val=from_val, by_val=by_val,
                condition=" ".join(cond_parts), stmts=stmts)

        # PERFORM UNTIL
        if self.at(TT.UNTIL):
            self.advance()
            cond_parts = []
            while not self.at_stmt_keyword() and not self.at(TT.DOT) \
                    and not self.at(TT.EOF):
                cond_parts.append(self.peek().value); self.advance()
            self.skip_dots()
            stmts = self._parse_statements(stop_at={TT.END_PERFORM})
            if self.at(TT.END_PERFORM): self.advance()
            self.skip_dots()
            return PerformUntilStmt(condition=" ".join(cond_parts), stmts=stmts)

        # fallback
        self.skip_dots()
        return None

    def _parse_evaluate(self):
        self.eat(TT.EVALUATE)
        subject = (self._collect_value() or "TRUE").upper()
        self.skip_dots()
        whens = []
        while self.at(TT.WHEN):
            self.advance()
            if self.at(TT.OTHER):
                self.advance()
                self.skip_dots()
                stmts = self._parse_statements(stop_at={TT.WHEN, TT.END_EVALUATE})
                whens.append(("OTHER", stmts))
            else:
                val_parts = []
                while not self.at_stmt_keyword() and not self.at(TT.DOT) \
                        and not self.at(TT.EOF):
                    val_parts.append(self.peek().value); self.advance()
                self.skip_dots()
                stmts = self._parse_statements(stop_at={TT.WHEN, TT.END_EVALUATE})
                whens.append((" ".join(val_parts), stmts))
        if self.at(TT.END_EVALUATE): self.advance()
        self.skip_dots()
        return EvaluateStmt(subject=subject, whens=whens)


def parse(source: str) -> ProgramNode:
    tokens = tokenize(source)
    return Parser(tokens).parse()
