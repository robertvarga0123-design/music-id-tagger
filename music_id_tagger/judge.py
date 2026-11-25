"""Two outside models vote on a doubtful match.

Grok and Gemini see the same file, tags and candidate. A doubtful hit is written
only when every model that answers accepts the same recording. One rejection
vetoes the write. They do not invent BPM, key or genre.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from music_id_tagger.match import clean, same_recording

Log = Callable[[str, str], None] | None

_GROK_MODELS = ("grok-4.20-non-reasoning", "grok-4.20-non-reasoning-latest")
_GEMINI_MODELS = ("gemini-2.5-flash", "gemini-2.0-flash")
_chosen = {"grok": "", "gemini": ""}


@dataclass
class Vote:
    name: str
    accept: bool | None
    artist: str = ""
    title: str = ""
    reason: str = ""


@dataclass
class Verdict:
    used: bool = False
    accept: bool = True
    confirmed: int = 0
    reasons: list[str] = field(default_factory=list)


def parse_decision(text: str) -> tuple[bool, str, str, str] | None:
    raw = text or ""
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        body = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict) or "accept" not in body:
        return None
    accept = body.get("accept")
    if isinstance(accept, str):
        accept = accept.strip().lower() in {"true", "igen", "yes", "1"}
    if not isinstance(accept, bool):
        return None
    return accept, clean(body.get("artist")), clean(body.get("title")), clean(body.get("reason"))[:240]


def combine(found_artist: str, found_title: str, votes: list[Vote]) -> Verdict:
    """Reject unless every answer that arrived accepts this same recording."""
    if not votes:
        return Verdict(used=False, accept=True, confirmed=0)
    answered = [vote for vote in votes if vote.accept is not None]
    if not answered:
        return Verdict(used=True, accept=True, confirmed=0, reasons=["Az AI nem válaszolt, a régi szabály dönt."])
    reasons: list[str] = []
    for vote in answered:
        if vote.accept and vote.artist and vote.title:
            if not same_recording(vote.artist, vote.title, found_artist, found_title):
                vote.accept = False
                vote.reason = vote.reason or "más számot mondott, mint a találat"
        if vote.reason:
            reasons.append(f"{vote.name}: {vote.reason}")
    named = [vote for vote in answered if vote.accept and vote.artist and vote.title]
    if len(named) >= 2 and not same_recording(named[0].artist, named[0].title, named[1].artist, named[1].title):
        reasons.append("A két AI nem ugyanazt a számot választotta.")
        return Verdict(used=True, accept=False, confirmed=0, reasons=reasons)
    if any(vote.accept is False for vote in answered):
        return Verdict(used=True, accept=False, confirmed=0, reasons=reasons)
    return Verdict(used=True, accept=True, confirmed=len(answered), reasons=reasons)


def _prompt(filename: str, existing: dict, found: dict, file_duration) -> str:
    def bits(meta: dict) -> str:
        parts = [
            clean(meta.get("artist")),
            clean(meta.get("title")),
            f"bpm {meta.get('bpm')}" if meta.get("bpm") not in (None, "") else "",
            f"key {meta.get('key')}" if meta.get("key") else "",
            f"genre {meta.get('genre')}" if meta.get("genre") else "",
            f"duration {meta.get('duration')}" if meta.get("duration") else "",
            f"source {meta.get('source')}" if meta.get("source") else "",
        ]
        return " | ".join(part for part in parts if part)

    return (
        "Decide if this music-file candidate is the same recording. "
        "Reject a different artist, a radio edit versus an extended mix, or a guess. "
        "Do not invent BPM, key or genre. Reply with JSON only: "
        '{"accept": true or false, "artist": "", "title": "", "reason": "short"}'
        f"\nFile name: {filename}"
        f"\nFile duration seconds: {file_duration if file_duration else 'unknown'}"
        f"\nTags already in the file: {bits(existing) or 'none'}"
        f"\nCandidate to write: {bits(found) or 'none'}"
    )


def review(filename: str, existing: dict, found: dict, file_duration, grok_key: str, gemini_key: str, log: Log = None) -> Verdict:
    votes: list[Vote] = []
    prompt = _prompt(filename, existing or {}, found or {}, file_duration)
    artist = clean((found or {}).get("artist"))
    title = clean((found or {}).get("title"))
    if grok_key:
        votes.append(_grok(grok_key.strip(), prompt, log))
    if gemini_key:
        votes.append(_gemini(gemini_key.strip(), prompt, log))
    verdict = combine(artist, title, votes)
    if log and verdict.used:
        if not verdict.accept:
            log("muted", "AI elutasította: " + " ".join(verdict.reasons))
        elif verdict.confirmed >= 2:
            log("ok", "Mindkét AI elfogadta ezt a találatot.")
        elif verdict.confirmed == 1:
            log("muted", "Csak az egyik AI válaszolt, a sor sárga marad.")
    return verdict


def _grok(key: str, prompt: str, log: Log) -> Vote:
    text = _chat_json(
        "grok",
        _GROK_MODELS,
        "https://api.x.ai/v1/chat/completions",
        key,
        prompt,
        log,
        grok=True,
    )
    return _vote("Grok", text)


def _gemini(key: str, prompt: str, log: Log) -> Vote:
    text = _chat_json(
        "gemini",
        _GEMINI_MODELS,
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        key,
        prompt,
        log,
        grok=False,
    )
    return _vote("Gemini", text)


def _vote(name: str, text: str | None) -> Vote:
    if not text:
        return Vote(name=name, accept=None, reason="nem válaszolt")
    parsed = parse_decision(text)
    if not parsed:
        return Vote(name=name, accept=None, reason="nem érthető válasz")
    accept, artist, title, reason = parsed
    return Vote(name=name, accept=accept, artist=artist, title=title, reason=reason)


def _chat_json(bucket: str, models: tuple[str, ...], url: str, key: str, prompt: str, log: Log, *, grok: bool) -> str | None:
    import requests

    order = [item for item in (_chosen[bucket], *models) if item]
    seen: list[str] = []
    for model in order:
        if model in seen:
            continue
        seen.append(model)
        try:
            if grok:
                response = requests.post(
                    url,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": model,
                        "temperature": 0,
                        "messages": [
                            {"role": "system", "content": "Reply with one JSON object and nothing else."},
                            {"role": "user", "content": prompt},
                        ],
                    },
                    timeout=30,
                )
            else:
                response = requests.post(
                    url.format(model=model),
                    params={"key": key},
                    headers={"Content-Type": "application/json"},
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=30,
                )
        except Exception:
            if log:
                log("muted", f"{bucket}: nincs hálózat.")
            return None
        if response.status_code in {404, 400} and "model" in (response.text or "").lower():
            continue
        if response.status_code == 401 or response.status_code == 403:
            if log:
                log("err", f"{bucket}: a kulcsot elutasították.")
            return None
        if response.status_code != 200:
            continue
        text = _message_text(response.json() if response.content else {}, grok=grok)
        if text:
            _chosen[bucket] = model
            return text
    if log:
        log("muted", f"{bucket}: nincs használható válasz.")
    return None


def _message_text(body: dict, *, grok: bool) -> str:
    if not isinstance(body, dict):
        return ""
    if grok:
        choices = body.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return ""
        message = choices[0].get("message") if isinstance(choices[0].get("message"), dict) else {}
        return clean(message.get("content"))
    candidates = body.get("candidates") or []
    if not candidates or not isinstance(candidates[0], dict):
        return ""
    content = candidates[0].get("content") if isinstance(candidates[0].get("content"), dict) else {}
    parts = content.get("parts") or []
    if not parts or not isinstance(parts[0], dict):
        return ""
    return clean(parts[0].get("text"))
