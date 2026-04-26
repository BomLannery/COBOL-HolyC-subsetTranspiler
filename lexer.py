"""
COBOL Lexer — tokenizes a subset of COBOL source code.
Handles: divisions, sections, keywords, identifiers, literals, numbers.
"""

import re
from dataclasses import dataclass
from enum import Enum, auto


class TT(Enum):  # Token Type
    # Structural
    DIVISION        = auto()
    SECTION         = auto()
    PARAGRAPH       = auto()
    DOT             = auto()

    # Division keywords
    IDENTIFICATION  = auto()
    PROGRAM_ID      = auto()
    DATA            = auto()
    WORKING_STORAGE = auto()
    PROCEDURE       = auto()
    ENVIRONMENT     = auto()

    # Data keywords
    PIC             = auto()
    PICTURE         = auto()
    VALUE           = auto()

    # Statement keywords
    DISPLAY         = auto()
    MOVE            = auto()
    TO              = auto()
    ADD             = auto()
    SUBTRACT        = auto()
    MULTIPLY        = auto()
    DIVIDE          = auto()
    COMPUTE         = auto()
    IF              = auto()
    ELSE            = auto()
    END_IF          = auto()
    PERFORM         = auto()
    UNTIL           = auto()
    VARYING         = auto()
    FROM            = auto()
    BY              = auto()
    END_PERFORM     = auto()
    STOP            = auto()
    RUN             = auto()
    EVALUATE        = auto()
    WHEN            = auto()
    OTHER           = auto()
    END_EVALUATE    = auto()
    GIVING          = auto()
    REMAINDER       = auto()
    TIMES           = auto()
    THRU            = auto()
    THROUGH         = auto()

    # Operators / relations
    EQUAL           = auto()
    NOT_EQUAL       = auto()
    LESS            = auto()
    GREATER         = auto()
    LESS_EQUAL      = auto()
    GREATER_EQUAL   = auto()
    AND             = auto()
    OR              = auto()
    NOT             = auto()
    EQUAL_SIGN      = auto()

    # Literals & identifiers
    NUMBER_LIT      = auto()
    STRING_LIT      = auto()
    IDENTIFIER      = auto()
    LEVEL_NUMBER    = auto()  # 01, 05, 77, etc.

    # Misc
    NEWLINE         = auto()
    EOF             = auto()
    UNKNOWN         = auto()


@dataclass
class Token:
    type: TT
    value: str
    line: int

    def __repr__(self):
        return f"Token({self.type.name}, {self.value!r}, ln{self.line})"


# Keywords map (uppercase)
KEYWORDS = {
    "IDENTIFICATION": TT.IDENTIFICATION,
    "PROGRAM-ID":     TT.PROGRAM_ID,
    "DATA":           TT.DATA,
    "WORKING-STORAGE":TT.WORKING_STORAGE,
    "PROCEDURE":      TT.PROCEDURE,
    "ENVIRONMENT":    TT.ENVIRONMENT,
    "DIVISION":       TT.DIVISION,
    "SECTION":        TT.SECTION,
    "PIC":            TT.PIC,
    "PICTURE":        TT.PICTURE,
    "VALUE":          TT.VALUE,
    "DISPLAY":        TT.DISPLAY,
    "MOVE":           TT.MOVE,
    "TO":             TT.TO,
    "ADD":            TT.ADD,
    "SUBTRACT":       TT.SUBTRACT,
    "MULTIPLY":       TT.MULTIPLY,
    "DIVIDE":         TT.DIVIDE,
    "COMPUTE":        TT.COMPUTE,
    "IF":             TT.IF,
    "ELSE":           TT.ELSE,
    "END-IF":         TT.END_IF,
    "PERFORM":        TT.PERFORM,
    "UNTIL":          TT.UNTIL,
    "VARYING":        TT.VARYING,
    "FROM":           TT.FROM,
    "BY":             TT.BY,
    "END-PERFORM":    TT.END_PERFORM,
    "STOP":           TT.STOP,
    "RUN":            TT.RUN,
    "EVALUATE":       TT.EVALUATE,
    "WHEN":           TT.WHEN,
    "OTHER":          TT.OTHER,
    "END-EVALUATE":   TT.END_EVALUATE,
    "GIVING":         TT.GIVING,
    "REMAINDER":      TT.REMAINDER,
    "TIMES":          TT.TIMES,
    "THRU":           TT.THRU,
    "THROUGH":        TT.THROUGH,
    "EQUAL":          TT.EQUAL,
    "NOT":            TT.NOT,
    "LESS":           TT.LESS,
    "GREATER":        TT.GREATER,
    "AND":            TT.AND,
    "OR":             TT.OR,
    "IS":             TT.UNKNOWN,   # relational filler — absorbed
    "ARE":            TT.UNKNOWN,
    "THAN":           TT.UNKNOWN,
    "TO":             TT.TO,
}

RELATION_MAP = {
    "=":  TT.EQUAL_SIGN,
    ">":  TT.GREATER,
    "<":  TT.LESS,
    ">=": TT.GREATER_EQUAL,
    "<=": TT.LESS_EQUAL,
}


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    line_num = 1

    # Strip COBOL fixed-format line numbers / sequence area (cols 1-6) and
    # indicator area (col 7).  We handle both fixed and free format naively:
    # if a line starts with 6+ digits or spaces followed by a non-space, strip them.
    lines = source.splitlines()
    clean_lines = []
    for ln in lines:
        # Remove inline comments (*> …)
        ln = re.sub(r'\*>.*$', '', ln)
        # Fixed format: col 7 is indicator; cols 1-6 are sequence. Strip if present.
        if len(ln) >= 7 and ln[:6].strip().isdigit():
            indicator = ln[6]
            if indicator == '*':   # comment line
                clean_lines.append('')
                continue
            ln = ln[7:]
        elif len(ln) >= 7 and ln[6] == '*':
            clean_lines.append('')
            continue
        clean_lines.append(ln)

    cleaned = '\n'.join(clean_lines)

    # Tokenizer regex
    token_pattern = re.compile(
        r'(?P<STRING>"[^"]*"|\'[^\']*\')'   # string literals
        r"|(?P<NUMBER>-?\d+(\.\d+)?)"        # numbers
        r"|(?P<RELOP>>=|<=|=|>|<)"           # relational operators
        r"|(?P<DOT>\.(?!\d))"                # dot (not decimal)
        r"|(?P<WORD>[A-Za-z][\w-]*)"         # identifiers / keywords
        r"|(?P<NEWLINE>\n)"
        r"|(?P<SKIP>[ \t\r]+)"
        r"|(?P<UNKNOWN>.)"
    )

    for m in token_pattern.finditer(cleaned):
        kind = m.lastgroup
        val  = m.group()

        if kind == 'SKIP':
            continue
        elif kind == 'NEWLINE':
            line_num += 1
            continue
        elif kind == 'STRING':
            tokens.append(Token(TT.STRING_LIT, val, line_num))  # keep quotes
        elif kind == 'NUMBER':
            # Level numbers are two-digit integers 01–49 or 66/77/88
            int_val = None
            try:
                int_val = int(val)
            except ValueError:
                pass
            if int_val is not None and 1 <= int_val <= 88 and '.' not in val:
                tokens.append(Token(TT.LEVEL_NUMBER, val, line_num))
            else:
                tokens.append(Token(TT.NUMBER_LIT, val, line_num))
        elif kind == 'RELOP':
            tokens.append(Token(RELATION_MAP.get(val, TT.UNKNOWN), val, line_num))
        elif kind == 'DOT':
            tokens.append(Token(TT.DOT, '.', line_num))
        elif kind == 'WORD':
            upper = val.upper()
            tt = KEYWORDS.get(upper, TT.IDENTIFIER)
            tokens.append(Token(tt, val, line_num))
        elif kind == 'UNKNOWN':
            tokens.append(Token(TT.UNKNOWN, val, line_num))

    tokens.append(Token(TT.EOF, '', line_num))
    return tokens
