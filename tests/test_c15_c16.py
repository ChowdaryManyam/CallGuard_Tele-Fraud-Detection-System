from pathlib import Path
from callguard_fraud import analyze_segments

root = Path.home() / "stt-project/data/Transkript"
phrase = "verhindre, dass de ganze Vorgang bi dere Freigabstell landet"

def scan_file(name):
    text = (root / name).read_text(encoding="utf-8")
    return analyze_segments([
        {"start": 0.0, "end": 1.0, "text": text}
    ])

c15 = scan_file("Stufe2_C15.txt")
c16 = scan_file("Stufe2_C16.txt")

c15_match = any(
    f.get("matched_phrase", "").casefold() == phrase.casefold()
    for f in c15.get("findings", [])
)
c16_match = any(
    f.get("matched_phrase", "").casefold() == phrase.casefold()
    for f in c16.get("findings", [])
)

print(f"{'PASS' if not c15_match else 'FAIL'} | C15 does not match approval-avoidance phrase")
print(f"{'PASS' if c16_match else 'FAIL'} | C16 matches approval-avoidance phrase")

if c15_match or not c16_match:
    raise SystemExit(1)

print("PASS | C15/C16 detector contrast verified")
