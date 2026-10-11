"""CallGuard adapter for the sprintd keyword/context detector.

Input: Whisper segments, each with start, end, and text fields.
Output: findings suitable for review. This rule engine does not determine that
fraud or a compliance breach definitely occurred.
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from hackathon import build_keyword_terms, find_hits

BASE_DIR = Path(__file__).resolve().parent
KEYWORD_FILE = BASE_DIR / "Stichwortliste.json"

_NEGATION_RE = re.compile(
    r"\b(?:nicht|nie|niemals|keinesfalls)\b"
    r"(?:\W+\w+){0,3}\W*$",
    re.IGNORECASE,
)


def is_preceded_by_negation(text: str, matched_phrase: str) -> bool:
    """Conservative heuristic for negation immediately before a direct match."""
    if not text or not matched_phrase:
        return False

    match = re.search(re.escape(matched_phrase), text, re.IGNORECASE)
    if match is None:
        return False

    prefix = text[:match.start()]
    return _NEGATION_RE.search(prefix) is not None




_REPORTED_SPEECH_RE = re.compile(
    r"\b(?:er|sie|man|der kollege|die kollegin)\s+"
    r"(?:sagte|meinte|erklärte|behauptete|fragte|berichtete)\b"
    r"|"
    r"\b(?:laut ihm|laut ihr|laut aussage|er sagte|sie sagte)\b",
    re.IGNORECASE,
)



_PROTECTIVE_CREDENTIAL_WARNING_RE = re.compile(
    r"\b(?:"
    r"nicht\s+(?:weitergeben|teilen|verraten|offenlegen|durchgeben|vorlesen)"
    r"|(?:geben|teilen|verraten|offenlegen)\s+sie\s+"
    r"(?:ihre|deine|die)\s+"
    r"(?:pin|passwort|tan|bestätigungscode)\s+"
    r"nicht\b"
    r")",
    re.IGNORECASE,
)


def is_protective_credential_warning(text: str) -> bool:
    """Recognize common warnings against disclosing credentials."""
    return bool(text and _PROTECTIVE_CREDENTIAL_WARNING_RE.search(text))


def detect_quoted_or_educational_context(text: str) -> bool:
    """Flag possible quotation or educational discussion for human review."""
    if not text:
        return False

    quoted = bool(
        re.search(
            r'"[^"\n]{1,300}"|„[^“\n]{1,300}“|«[^»\n]{1,300}»',
            text,
        )
    )
    educational = bool(
        re.search(
            r"\b(?:im training|in der schulung|als beispiel|"
            r"wir diskutieren den ausdruck|wir besprechen den ausdruck|"
            r"zur demonstration)\b",
            text,
            re.IGNORECASE,
        )
    )
    return quoted or educational



def detect_reported_speech(text: str) -> bool:
    """Flag likely reported speech for human review; do not infer intent."""
    return bool(_REPORTED_SPEECH_RE.search(text))


def analyze_segments(
    segments: Iterable[dict[str, Any]],
    *,
    language: str = "all",
    accent_insensitive: bool = True,
    context_window: int = 2,
) -> dict[str, Any]:
    """Scan real Whisper segments and attach each finding to its audio time.

    Expected segment fields: start (seconds), end (seconds), text.
    Returns status='review' when any rule matches, otherwise 'no_matches'.
    'no_matches' means no configured phrase matched; it is not proof of no fraud.
    """
    normalized: list[dict[str, Any]] = []
    for item in segments:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        try:
            start = float(item.get("start", 0.0) or 0.0)
        except (TypeError, ValueError):
            start = 0.0
        try:
            end = float(item.get("end", start) or start)
        except (TypeError, ValueError):
            end = start
        normalized.append({"start": max(0.0, start), "end": max(start, end), "text": text})

    if not normalized:
        return {"status": "no_transcript", "finding_count": 0, "findings": [],
                "message": "No non-empty transcript segments were supplied."}

    languages = {"de", "gsw"} if language == "all" else {language}
    terms = build_keyword_terms(KEYWORD_FILE, languages)

    # Each segment is represented as a structured turn so detector line numbers
    # map predictably back to Whisper segment indices (text line = 2 * index + 2).
    transcript = "\n".join(
        line
        for i, segment in enumerate(normalized, start=1)
        for line in (f"T{i:03d} Text", segment["text"])
    ) + "\n"

    with tempfile.TemporaryDirectory(prefix="callguard-fraud-") as temp_dir:
        transcript_path = Path(temp_dir) / "live_transcript.txt"
        transcript_path.write_text(transcript, encoding="utf-8")
        hits = find_hits(
            [transcript_path], terms,
            accent_insensitive=accent_insensitive,
            include_context=True,
            context_window=max(0, int(context_window)),
        )

    findings: list[dict[str, Any]] = []
    for hit in hits:
        # Apply only to direct phrase matches; context findings need separate review.
        if hit.evidence_type != "context" and (
            is_preceded_by_negation(hit.text, hit.matched_text)
            or (
                hit.matched_text.lower() in {
                    "pin", "passwort", "tan", "bestätigungscode"
                }
                and is_protective_credential_warning(hit.text)
            )
        ):
            continue

        # Direct hit line numbers are 2,4,6...; context hits point to the first
        # supporting line. Clamp defensively in case the transcript format changes.
        index = max(0, min(len(normalized) - 1, (int(hit.line_number) - 2) // 2))
        segment = normalized[index]
        raw = asdict(hit)
        findings.append({
            "status": "review",
            "evidence_type": raw["evidence_type"],
            "confidence": raw["confidence"],
            "category": raw["family_label"],
            "keyword_id": raw["keyword_id"],
            "keyword_label": raw["keyword_label"],
            "matched_phrase": raw["matched_text"],
            "reason": (
                raw["reason"] + " | Reported speech may be present; "
                "the quoted/reported action does not establish the current speaker's intent."
                if detect_reported_speech(raw["text"])
                else raw["reason"]
            ),
            "reported_speech": detect_reported_speech(raw["text"]),
            "quoted_or_educational_context": detect_quoted_or_educational_context(raw["text"]),
            "text": raw["text"],
            "speaker": segment.get("speaker", "") or "",
            "segment_index": index,
            "start": segment["start"],
            "end": segment["end"],
            "turn_id": raw["turn_id"],
        })

    return {
        "status": "review" if findings else "no_matches",
        "finding_count": len(findings),
        "findings": findings,
        "message": ("Keyword/context matches require human review." if findings else
                    "No configured keyword/context matches. This does not prove the call is compliant."),
    }
