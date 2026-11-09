"""Run axe-core scans and render their results as a GitHub-friendly Markdown report."""

import html
import json
import typing as t
from pathlib import Path

from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page

AXE_REPORT_PATH = Path("/shared_cache/pytest/axe-report.md")
WCAG_TAGS = ("wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa")


class AxeCheck(t.TypedDict):
    """One explanation returned for a DOM node."""

    message: str


class AxeNode(t.TypedDict):
    """Relevant axe data for one rendered DOM location."""

    impact: str | None
    target: list[t.Any]
    html: str
    failureSummary: str | None
    any: list[AxeCheck]
    all: list[AxeCheck]
    none: list[AxeCheck]


class AxeRuleSummary(t.TypedDict):
    """Compact axe result for a rule that passed."""

    id: str
    help: str
    helpUrl: str
    tags: list[str]


class AxeRuleResult(AxeRuleSummary):
    """Detailed axe result for a violation or manual-review item."""

    impact: str | None
    description: str
    nodes: list[AxeNode]


class AxeResults(t.TypedDict):
    """Serializable subset of one axe-core result object."""

    testEngine: dict[str, str]
    passes: list[AxeRuleSummary]
    violations: list[AxeRuleResult]
    incomplete: list[AxeRuleResult]


class AxeScenario(t.TypedDict):
    """A named browser state and its accessibility results."""

    name: str
    url: str
    results: AxeResults


class AxeTechnicalError(t.TypedDict):
    """A technical failure that prevented an accessibility scan."""

    name: str
    url: str
    message: str


class AccessibilityReport:
    """Collect non-blocking axe findings across browser scenarios."""

    def __init__(self) -> None:
        """Initialize an empty axe report."""
        self.axe = Axe()
        self.scenarios: list[AxeScenario] = []
        self.technical_errors: list[AxeTechnicalError] = []

    def scan(self, page: Page, name: str) -> None:
        """Scan the currently rendered browser state and retain the results."""
        try:
            results = t.cast(
                AxeResults,
                self.axe.run(
                    page,
                    options={
                        "runOnly": {"type": "tag", "values": list(WCAG_TAGS)},
                        "resultTypes": ["passes", "violations", "incomplete"],
                    },
                ).response,
            )
            self.scenarios.append({"name": name, "url": page.url, "results": results})
        except Exception as exc:
            self.technical_errors.append({"name": name, "url": page.url, "message": str(exc)})
            raise

    def write(self, path: Path = AXE_REPORT_PATH) -> None:
        """Write the collected results to the shared CI report directory."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.as_markdown(), encoding="utf-8")

    @property
    def has_violations(self) -> bool:
        """Return whether any scanned scenario has an axe-core violation."""
        return any(scenario["results"]["violations"] for scenario in self.scenarios)

    def as_markdown(self) -> str:
        """Render all scenarios as a detailed, non-blocking Markdown report."""
        engine_versions = {
            scenario["results"].get("testEngine", {}).get("version", "onbekend") for scenario in self.scenarios
        }
        version = ", ".join(sorted(engine_versions)) if engine_versions else "unknown"
        violation_rules = sum(len(scenario["results"]["violations"]) for scenario in self.scenarios)
        incomplete_rules = sum(len(scenario["results"]["incomplete"]) for scenario in self.scenarios)
        passed_rules = sum(len(scenario["results"]["passes"]) for scenario in self.scenarios)

        attention_scenarios = [
            scenario
            for scenario in self.scenarios
            if scenario["results"]["violations"] or scenario["results"]["incomplete"]
        ]
        lines = [
            f"## Accessibility — axe-core {version}",
            "",
            "| Scenarios | Passed | Issues | Manual review |",
            "|---:|---:|---:|---:|",
            (f"| {len(self.scenarios)} | {passed_rules} | {violation_rules} | {incomplete_rules} |"),
            "",
        ]

        if not self.scenarios:
            lines.extend(["No accessibility scenarios were executed.", ""])
        elif not attention_scenarios:
            lines.extend(["✅ No accessibility issues found.", ""])

        for scenario in attention_scenarios:
            lines.extend(self._scenario_markdown(scenario))

        if self.technical_errors:
            lines.extend(["### Technical scan errors", ""])
            for error in self.technical_errors:
                lines.extend(
                    [
                        f"- **{self._text(error['name'])}** — `{self._text(error['url'])}`",
                        f"  - {self._text(error['message'])}",
                    ]
                )
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def _scenario_markdown(self, scenario: AxeScenario) -> list[str]:
        """Render one page state, including every affected DOM location."""
        results = scenario["results"]
        lines = [
            f"### {self._text(scenario['name'])}",
            "",
            f"Page: `{self._text(scenario['url'])}`",
            "",
        ]
        for rule in results["violations"]:
            lines.extend(self._rule_markdown(rule, "❌ Violation"))

        for rule in results["incomplete"]:
            lines.extend(self._rule_markdown(rule, "⚠️ Manual review"))

        return lines

    def _rule_markdown(self, rule: AxeRuleResult, label: str) -> list[str]:
        """Render one failed or incomplete axe rule and its DOM targets."""
        impact = rule.get("impact") or "unknown"
        lines = [
            f"#### {label}: `{self._text(rule['id'])}` ({self._text(impact)})",
            "",
            self._text(rule["help"]),
        ]

        for index, node in enumerate(rule["nodes"], start=1):
            selector = json.dumps(node.get("target", []), ensure_ascii=False)
            reasons = self._node_reasons(node)
            lines.extend(
                [
                    f"- **Location {index}:** `{self._text(selector)}`",
                    f"  - {self._text(' '.join(reasons))}",
                    "",
                ]
            )

        lines.extend([f"[Uitleg en hersteladvies van Deque]({rule['helpUrl']})", ""])
        return lines

    @staticmethod
    def _node_reasons(node: AxeNode) -> list[str]:
        """Return de-duplicated axe explanations for one DOM node."""
        reasons: list[str] = []
        checks = [*node.get("any", []), *node.get("all", []), *node.get("none", [])]
        for reason in [node.get("failureSummary"), *(check.get("message") for check in checks)]:
            normalized = str(reason or "").strip()
            if normalized and normalized not in reasons:
                reasons.append(normalized)
        return reasons or ["axe-core did not return an explanation for this location."]

    @staticmethod
    def _text(value: object) -> str:
        """Escape dynamic text before embedding it in GitHub Markdown."""
        return html.escape(str(value), quote=False)
