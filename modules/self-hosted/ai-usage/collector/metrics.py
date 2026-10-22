"""Prometheus textfile rendering for the AI usage collector.

The collector writes node_exporter textfile metrics. Every sample carries the
labels the dashboard needs, and nothing that could identify a person: no
emails, no account identifiers, no paths, and no credential material.
"""

from __future__ import annotations

import dataclasses
import math
import re
from dataclasses import field
from typing import Iterable, Iterator, Mapping, Sequence

Sample = tuple[str, dict[str, str], float]

# A label value may hold any character a Prometheus label value allows, and
# a colon is one of them. The colon is kept on purpose: a T3 Code model id
# carries its checkpoint as "model:1017", and a dashboard that filters on the
# model has to use the id the provider gave.
_LABEL_VALUE = re.compile(r"[^a-zA-Z0-9_.:\-]")
_LABEL_NAME = re.compile(r"[^a-zA-Z0-9_]")

# Label values are bounded so a rogue provider string cannot create
# unbounded cardinality or blow past the textfile collector's limits.
MAX_LABEL_LENGTH = 120


class ExactLabel(str):
    """A label value that is published exactly as it is.

    The exposition format escapes a backslash, a double quote and a newline
    in a label value, and that is all it does: the reader sees the name the
    provider wrote, with its spaces and its punctuation. Every other label
    value is sanitised, so a value that reaches the text file stays safe to
    read and to filter on.
    """


def label_value(value: object) -> str:
    """Return a Prometheus-safe label value."""
    text = str(value)
    text = _LABEL_VALUE.sub("_", text)
    if len(text) > MAX_LABEL_LENGTH:
        text = text[:MAX_LABEL_LENGTH]
    return text


def label_name(name: str) -> str:
    return _LABEL_NAME.sub("_", name)


def format_series(name: str, labels: Mapping[str, str]) -> str:
    """Render a series the way the text file holds it."""
    if not labels:
        return name
    rendered = ",".join(
        f'{key}="{_escape_label(item)}"' for key, item in sorted(labels.items())
    )
    return f"{name}{{{rendered}}}"


def escape_help(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\n", "\\n")


def format_value(value: float) -> str:
    """Render a float the way Prometheus expects."""
    if isinstance(value, bool):
        return "1" if value else "0"
    if value != value or value in (float("inf"), float("-inf")):  # NaN or infinity
        return "NaN" if value != value else ("+Inf" if value > 0 else "-Inf")
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(float(value))


@dataclasses.dataclass(frozen=True)
class DroppedSeries:
    """A repeated series that the writer dropped.

    The name and the labels are the series, and the flag says whether the
    repeat carried the value that was kept.
    """

    name: str
    labels: tuple[tuple[str, str], ...]
    same_value: bool

    def describe(self) -> str:
        """Render the series the way the text file holds it."""
        return format_series(self.name, dict(self.labels))


class MetricWriter:
    """Collects samples and renders them in the Prometheus textfile format."""

    def __init__(self) -> None:
        self._samples: list[Sample] = []
        self._help: dict[str, str] = {}
        self._types: dict[str, str] = {}
        # Every published series, by its name and its label set. A metric
        # series is that pair, and a series is published once.
        self._seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
        # The value each published series kept, so a repeat can say whether
        # it carried the same value.
        self._kept: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        # How many repeats were dropped. The count is published, so a
        # duplicate is never hidden.
        self.duplicates = 0
        # The repeats that were dropped, so the run can name every series it
        # dropped and not only say how many there were.
        self.dropped: list[DroppedSeries] = []

    def declare(self, name: str, kind: str, help_text: str) -> None:
        self._help.setdefault(name, help_text)
        self._types.setdefault(name, kind)

    def add(self, name: str, labels: Mapping[str, object], value: float) -> None:
        if value is None:
            return
        number = float(value)
        if math.isnan(number):
            return
        clean = {
            label_name(key): (
                str(item) if isinstance(item, ExactLabel) else label_value(item)
            )
            for key, item in labels.items()
        }
        key = (name, tuple(sorted(clean.items())))
        if key in self._seen:
            # The same series a second time. The first reading is the one
            # that is published, and the repeat is counted: a textfile that
            # holds one series twice makes the scrape fail. The repeat is
            # recorded as well, so the run can name the series it dropped.
            self.duplicates += 1
            self.dropped.append(
                DroppedSeries(
                    name,
                    tuple(sorted(clean.items())),
                    self._kept[key] == number,
                )
            )
            return
        self._seen.add(key)
        self._kept[key] = number
        self._samples.append((name, clean, number))

    def gauge(self, name: str, value: float, **labels: object) -> None:
        self.add(name, labels, value)

    def samples(self) -> Sequence[Sample]:
        return tuple(self._samples)

    def render(self) -> str:
        lines: list[str] = []
        grouped: dict[str, list[Sample]] = {}
        for name, labels, value in self._samples:
            grouped.setdefault(name, []).append((name, labels, value))
        for name in sorted(grouped):
            help_text = self._help.get(name)
            if help_text:
                lines.append(f"# HELP {name} {escape_help(help_text)}")
            kind = self._types.get(name)
            if kind:
                lines.append(f"# TYPE {name} {kind}")
            for _, labels, value in sorted(
                grouped[name], key=lambda item: sorted(item[1].items())
            ):
                lines.append(f"{format_series(name, labels)} {format_value(value)}")
        return "\n".join(lines) + "\n"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@dataclasses.dataclass
class SourceResult:
    """The outcome of one collection source."""

    source: str
    status: str
    # A fixed reason code, never a message: a failure can carry a
    # credential, an address, a path, or a provider's own diagnostic.
    reason: str = ""
    metrics: list[Sample] = field(default_factory=list)
    observed_at: float | None = None
    duration_s: float = 0.0
    # The measured quota windows of the source, with the length of each
    # window, so the ranking can measure the pace of the usage.
    windows: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True only when the source reported a complete reading.

        A partial source is not a success: it read some of the reading and
        not the rest, and a panel must not show it green.
        """
        return self.status == "ok"

    @property
    def partial(self) -> bool:
        return self.status == "partial"


def iter_samples(results: Iterable[SourceResult]) -> Iterator[Sample]:
    for result in results:
        yield from result.metrics
