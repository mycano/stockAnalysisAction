"""Deterministic investor-report structures from the product contract."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any


@dataclass(frozen=True)
class ReportSection:
    section_id: str
    heading: str


@dataclass(frozen=True)
class ReportContract:
    scene: str
    depth: str
    sections: tuple[ReportSection, ...]

    @property
    def contract_id(self) -> str:
        return f"{self.scene}.{self.depth}"

    def validate(self, markdown: str) -> list[str]:
        """Return deterministic structure violations without exposing internals."""

        positions: list[int] = []
        violations: list[str] = []
        for section in self.sections:
            marker = f"## {section.heading}"
            position = markdown.find(marker)
            if position < 0:
                violations.append(f"缺少章节：{section.heading}")
            positions.append(position)
        present = [position for position in positions if position >= 0]
        if present != sorted(present):
            violations.append("章节顺序不符合报告契约")
        bodies: list[tuple[str, str]] = []
        for index, section in enumerate(self.sections):
            marker = f"## {section.heading}"
            start = markdown.find(marker)
            if start < 0:
                continue
            body_start = start + len(marker)
            later = [
                markdown.find(f"## {candidate.heading}", body_start)
                for candidate in self.sections[index + 1 :]
            ]
            end = min((position for position in later if position >= 0), default=len(markdown))
            body = markdown[body_start:end].strip()
            bodies.append((section.heading, body))
            prose = re.sub(r"[*_`#|\-\s]", "", body)
            if not prose:
                violations.append(f"章节内容过少：{section.heading}")
        normalized: dict[str, list[str]] = {}
        for heading, body in bodies:
            key = re.sub(r"\s+", "", body)
            if len(key) >= 40:
                normalized.setdefault(key, []).append(heading)
        duplicates = [headings for headings in normalized.values() if len(headings) > 1]
        for headings in duplicates:
            violations.append(f"章节内容重复：{'、'.join(headings)}")
        return violations


def _catalog() -> dict[str, Any]:
    resource = resources.files("stock_analysis").joinpath("report_contracts", "catalog.yaml")
    with resource.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_report_contract(scene: str, depth: str) -> ReportContract:
    contract_id = f"{scene}.{depth}"
    try:
        raw = _catalog()["contracts"][contract_id]
    except KeyError as exc:
        raise ValueError(f"unsupported report contract: {contract_id}") from exc
    return ReportContract(
        scene=str(raw["scene"]),
        depth=str(raw["depth"]),
        sections=tuple(
            ReportSection(str(section_id), str(heading))
            for section_id, heading in raw["sections"]
        ),
    )


def list_report_contracts() -> tuple[str, ...]:
    return tuple(_catalog()["contracts"])
