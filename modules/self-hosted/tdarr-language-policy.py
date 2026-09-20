#!/usr/bin/env python3
"""Build Tdarr's original-language policy from the local arr databases."""

import json
import os
import sqlite3
import tempfile
from pathlib import Path


LANGUAGES = {
    1: ("English", ("eng", "en")),
    2: ("French", ("fra", "fre", "fr")),
    3: ("Spanish", ("spa", "es")),
    4: ("German", ("deu", "ger", "de")),
    5: ("Italian", ("ita", "it")),
    6: ("Danish", ("dan", "da")),
    7: ("Dutch", ("nld", "dut", "nl")),
    8: ("Japanese", ("jpn", "ja")),
    9: ("Icelandic", ("isl", "ice", "is")),
    10: ("Chinese", ("zho", "chi", "cmn", "yue", "zh")),
    11: ("Russian", ("rus", "ru")),
    12: ("Polish", ("pol", "pl")),
    13: ("Vietnamese", ("vie", "vi")),
    14: ("Swedish", ("swe", "sv")),
    15: ("Norwegian", ("nor", "no")),
    16: ("Finnish", ("fin", "fi")),
    17: ("Turkish", ("tur", "tr")),
    18: ("Portuguese", ("por", "pt")),
    19: ("Flemish", ("nld", "dut", "vls", "nl")),
    20: ("Greek", ("ell", "gre", "el")),
    21: ("Korean", ("kor", "ko")),
    22: ("Hungarian", ("hun", "hu")),
    23: ("Hebrew", ("heb", "he")),
    24: ("Lithuanian", ("lit", "lt")),
    25: ("Czech", ("ces", "cze", "cs")),
    26: ("Hindi", ("hin", "hi")),
    27: ("Romanian", ("ron", "rum", "ro")),
    28: ("Thai", ("tha", "th")),
    29: ("Bulgarian", ("bul", "bg")),
    30: ("Portuguese (Brazil)", ("por", "pt", "pob")),
    31: ("Arabic", ("ara", "ar")),
    32: ("Ukrainian", ("ukr", "uk")),
    33: ("Persian", ("fas", "per", "fa")),
    34: ("Bengali", ("ben", "bn")),
    35: ("Slovak", ("slk", "slo", "sk")),
    36: ("Latvian", ("lav", "lv")),
    37: ("Spanish (Latino)", ("spa", "es")),
    38: ("Catalan", ("cat", "ca")),
    39: ("Croatian", ("hrv", "hr")),
    40: ("Serbian", ("srp", "sr")),
    41: ("Bosnian", ("bos", "bs")),
    42: ("Estonian", ("est", "et")),
    43: ("Tamil", ("tam", "ta")),
    44: ("Indonesian", ("ind", "id")),
    45: ("Telugu", ("tel", "te")),
    46: ("Macedonian", ("mkd", "mac", "mk")),
    47: ("Slovenian", ("slv", "sl")),
    48: ("Malayalam", ("mal", "ml")),
    49: ("Kannada", ("kan", "kn")),
    50: ("Albanian", ("sqi", "alb", "sq")),
    51: ("Afrikaans", ("afr", "af")),
    52: ("Marathi", ("mar", "mr")),
    53: ("Tagalog", ("tgl", "fil", "tl")),
    54: ("Urdu", ("urd", "ur")),
    55: ("Romansh", ("roh", "rm")),
    56: ("Mongolian", ("mon", "mn")),
    57: ("Georgian", ("kat", "geo", "ka")),
}


def query(database: str, statement: str):
    uri = f"file:{database}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=30) as connection:
        yield from connection.execute(statement)


def policy_entry(language_id: int):
    language = LANGUAGES.get(language_id)
    if language is None:
        return {"languageId": language_id, "name": "Unknown", "tags": []}
    name, tags = language
    return {"languageId": language_id, "name": name, "tags": list(tags)}


def translate(path: str, arr_root: str, tdarr_root: str):
    path = path.rstrip("/")
    if path == arr_root:
        return tdarr_root
    prefix = f"{arr_root}/"
    if not path.startswith(prefix):
        return None
    return f"{tdarr_root}/{path[len(prefix):]}"


def main():
    roots = {}
    movie_query = """
        SELECT m.Path, mm.OriginalLanguage
        FROM Movies AS m
        JOIN MovieMetadata AS mm ON mm.Id = m.MovieMetadataId
    """
    for path, language_id in query("/srv/apps/radarr/radarr.db", movie_query):
        translated = translate(path, "/movies", "/source/Movies")
        if translated:
            roots[translated] = policy_entry(language_id)

    for path, language_id in query(
        "/srv/apps/sonarr/sonarr.db", "SELECT Path, OriginalLanguage FROM Series"
    ):
        translated = translate(path, "/tv", "/source/TV")
        if translated:
            roots[translated] = policy_entry(language_id)

    payload = json.dumps(
        {"version": 1, "roots": roots}, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    destination = Path("/srv/apps/tdarr/policy/original-languages.json")
    if destination.exists() and destination.read_text(encoding="utf-8") == payload:
        return

    destination.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=destination.parent, prefix=".original-languages.", text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    main()
