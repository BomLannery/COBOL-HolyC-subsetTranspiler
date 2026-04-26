# COBOL-HolyC-subsetTranspiler

A subset transpiler — covering core COBOL arithmetic, control flow, working-storage variables, and DISPLAY

COBOL→ HolyC

DISPLAY "TEXT"→ Print("%s\n", "TEXT");
MOVE x TO y→ y = x; / StrCpy(y, x);
ADD x TO y→ y = y + x;
SUBTRACT/MULTIPLY/DIVIDE→ Full arithmetic
COMPUTE x = expr→ x = expr;
IF/ELSE/END-IFif/else {}
PERFORM n TIMES→ for loop
PERFORM VARYING … UNTIL→ for with condition
EVALUATE TRUE / WHEN→ if/else if/else chain
STOP RUN→ exit(0);
PIC 9(n) / X(n)→ I64 / U8[n]
