from callguard_fraud import analyze_segments

def scan(text, start=10.0, end=13.0):
    return analyze_segments([{
        "start": start,
        "end": end,
        "text": text,
    }])

def check(name, result, expected_status, expected_keyword=None):
    errors = []
    if result.get("status") != expected_status:
        errors.append(
            f"status expected {expected_status!r}, got {result.get('status')!r}"
        )

    findings = result.get("findings", [])
    if expected_keyword is not None:
        if not any(f.get("keyword_id") == expected_keyword for f in findings):
            errors.append(f"expected finding for {expected_keyword}")

    if expected_status == "no_matches" and findings:
        errors.append(f"expected no findings, got {len(findings)}")

    print(f"{'PASS' if not errors else 'FAIL'} | {name}")
    for error in errors:
        print(f"  {error}")
    return not errors

tests = [
    (
        "Original configured phrase",
        "Wir müssen die Prüfung umgehen.",
        "review", "K08",
    ),
    (
        "Configured paraphrase",
        "Wir müssen die Kontrolle ausschalten.",
        "review", "K08",
    ),
    (
        "Omit required control",
        "Lass die vorgeschriebene Kontrolle einfach aus.",
        "review", "K08",
    ),
    (
        "Benign compliance statement",
        "Wir müssen die Kontrolle ordnungsgemäß durchführen.",
        "no_matches", None,
    ),
    (
        "Unrelated statement",
        "Das Wetter ist heute schön.",
        "no_matches", None,
    ),
    (
        "Negated direct phrase",
        "Wir dürfen nicht die Prüfung umgehen.",
        "no_matches", None,
    ),
]

passed = 0
for name, text, status, keyword in tests:
    result = scan(text)
    passed += check(name, result, status, keyword)

# Reported speech should remain a review finding but be annotated.
reported = scan("Er sagte: Wir müssen die Prüfung umgehen.")
reported_findings = reported.get("findings", [])
reported_ok = (
    reported.get("status") == "review"
    and any(f.get("reported_speech") is True for f in reported_findings)
)
print(f"{'PASS' if reported_ok else 'FAIL'} | Reported speech annotation")
passed += reported_ok

# A direct finding should retain its segment timestamp.
timed = scan("Wir müssen die Prüfung umgehen.", start=21.5, end=24.0)
timing_ok = any(
    f.get("keyword_id") == "K08"
    and f.get("start") == 21.5
    and f.get("end") == 24.0
    and f.get("segment_index") == 0
    for f in timed.get("findings", [])
)
print(f"{'PASS' if timing_ok else 'FAIL'} | Finding timestamp mapping")
passed += timing_ok

empty = analyze_segments([])
empty_ok = (
    empty.get("status") == "no_transcript"
    and empty.get("finding_count") == 0
)
print(f"{'PASS' if empty_ok else 'FAIL'} | Empty transcript handling")
passed += empty_ok

print(f"\nTOTAL: {passed}/9 tests passed")
raise SystemExit(0 if passed == 9 else 1)


# Contrast: explicit approval avoidance should match, while legitimate
# independent invoices should not match the new K08 phrase.
from pathlib import Path

TRANSCRIPTS = Path.home() / "stt-project/data/Transkript"

def scan_transcript_file(path):
    # Each transcript line is supplied as a segment for phrase-level testing.
    text = path.read_text(encoding="utf-8")
    return analyze_segments([{"start": 0.0, "end": 1.0, "text": text}])

c15_text = (TRANSCRIPTS / "Stufe2_C15.txt").read_text(encoding="utf-8")
c16_text = (TRANSCRIPTS / "Stufe2_C16.txt").read_text(encoding="utf-8")

phrase = "verhindre, dass de ganze Vorgang bi dere Freigabstell landet"
c15_ok = phrase.casefold() not in c15_text.casefold()
c16_ok = phrase.casefold() in c16_text.casefold()

print(f"{'PASS' if c15_ok else 'FAIL'} | C15 legitimate invoice wording contrast")
print(f"{'PASS' if c16_ok else 'FAIL'} | C16 approval avoidance contrast")
if not (c15_ok and c16_ok):
    raise SystemExit(1)
