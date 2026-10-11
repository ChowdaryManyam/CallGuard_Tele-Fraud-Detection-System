from callguard_fraud import analyze_segments

phrase = "verhindre, dass de ganze Vorgang bi dere Freigabstell landet"
benign = "Mir führed d'Kontrolle ordnigsgemäss dure."

def scan(text):
    return analyze_segments([
        {"start": 0.0, "end": 1.0, "text": text}
    ])

control = scan(benign)
target = scan(phrase)

control_match = any(
    f.get("matched_phrase", "").casefold() == phrase.casefold()
    for f in control.get("findings", [])
)
target_match = any(
    f.get("matched_phrase", "").casefold() == phrase.casefold()
    for f in target.get("findings", [])
)

print(
    f"{'PASS' if not control_match else 'FAIL'} | "
    "Benign control does not match approval-avoidance phrase"
)
print(
    f"{'PASS' if target_match else 'FAIL'} | "
    "Configured approval-avoidance phrase is detected"
)

if control_match or not target_match:
    raise SystemExit(1)

print("PASS | Approval-avoidance phrase regression verified")
