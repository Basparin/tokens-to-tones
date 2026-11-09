"""dur.py <piece.txt> -- how long a piece plays (sums beats at the running tempo)."""
import re, sys
tempo = 100.0; total = 0.0
for line in open(sys.argv[1], encoding="utf-8"):
    for tok in re.findall(r"\[[^\]]*\](?::[\d.]+)?|\S+", line.strip()):
        if tok.startswith("#"): break
        if tok.startswith("tempo="): tempo = float(tok[6:]); continue
        if "=" in tok and not tok.startswith("["): continue
        m = re.search(r":([\d.]+)$", tok); beats = float(m.group(1)) if m else 1.0
        total += 60.0 / tempo * beats
print("%.0f s (%.1f min)" % (total, total / 60))
