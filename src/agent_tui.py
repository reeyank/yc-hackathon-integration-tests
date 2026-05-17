"""Rich terminal UI for the AI-native integration tester.

Visual language is inherited from DESIGN.md (the T8 coverage map):
bioluminescent terminal — near-black field, phosphor-mint accents, alarm
coral reserved strictly for failure, dim slate for everything secondary.
No purple, no gradients, no RAG palette, minimal chrome. Layout takes its
breathing-room and wordmark cues from clean agent CLIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# DESIGN.md palette — the single source of truth for color on every surface.
BG = "#0A0E14"
DORMANT = "#2A3340"
MINT = "#5EF6A4"  # exercised / done
ACTIVE = "#A8FFD0"  # the one warmest thing on screen
CORAL = "#FF6B5E"  # failure ONLY — never decoration
DIM = "#5A6B7A"  # secondary text
EDGE = "#1C2530"  # rules / borders

_WORDMARK = "ai ios integration tester"


@dataclass
class TaskState:
    name: str
    status: str = "pending"
    detail: str = ""


class AgentTUI:
    def __init__(self) -> None:
        try:
            from rich import box
            from rich.align import Align
            from rich.console import Console, Group
            from rich.live import Live
            from rich.markdown import Markdown
            from rich.padding import Padding
            from rich.panel import Panel
            from rich.prompt import Prompt
            from rich.rule import Rule
            from rich.table import Table
            from rich.text import Text
            from rich.theme import Theme
        except ModuleNotFoundError:
            self.box = None
            self.Align = None
            self.console = None
            self.Group = None
            self.Live = None
            self.Markdown = None
            self.Padding = None
            self.Panel = None
            self.Prompt = None
            self.Rule = None
            self.Table = None
            self.Text = None
        else:
            self.box = box
            self.Align = Align
            self.Group = Group
            self.Live = Live
            self.Markdown = Markdown
            self.Padding = Padding
            self.Panel = Panel
            self.Prompt = Prompt
            self.Rule = Rule
            self.Table = Table
            self.Text = Text
            self.console = Console(
                theme=Theme(
                    {
                        "brand": f"bold {MINT}",
                        "active": f"bold {ACTIVE}",
                        "ok": MINT,
                        "run": ACTIVE,
                        "fail": f"bold {CORAL}",
                        "muted": DIM,
                        "rule.line": EDGE,
                        "panel.border": EDGE,
                    }
                )
            )
        self.tasks: list[TaskState] = []
        self.network_rows: list[dict[str, Any]] = []
        self.title = "GBRAIN AI Integration Tester"
        self.subtitle = ""
        self.events: list[tuple[str, str]] = []
        self.gbrain_rows: list[dict[str, str]] = []
        self.phase = "warming up"
        self.agent_thought = "Waiting for the first plan."
        self.risks: list[str] = []
        self.tool_calls: list[str] = []
        self.metrics: dict[str, str] = {
            "gbrain": "cold",
            "openai": "idle",
            "network": "idle",
            "sim": "idle",
        }
        self.live: Any | None = None

    def header(self, title: str, subtitle: str) -> None:
        self.title = title
        self.subtitle = subtitle
        if not self.console:
            print(f"{title}\n{subtitle}")
            return
        self.start()

    def start(self) -> None:
        if not self.console or self.live:
            return
        self.live = self.Live(
            self._render(),
            console=self.console,
            refresh_per_second=8,
            transient=False,
        )
        self.live.start()

    def stop(self) -> None:
        if self.live:
            self.live.stop()
            self.live = None

    def add_task(self, name: str) -> int:
        self.tasks.append(TaskState(name=name))
        self.render_tasks()
        return len(self.tasks) - 1

    def update_task(self, index: int, status: str, detail: str = "") -> None:
        self.tasks[index].status = status
        self.tasks[index].detail = detail
        self.metrics[_metric_key(self.tasks[index].name)] = status
        if status == "running":
            self.phase = self.tasks[index].name
        self.render_tasks()

    def render_tasks(self) -> None:
        if not self.console:
            for task in self.tasks:
                detail = f" - {task.detail}" if task.detail else ""
                print(f"[{task.status}] {task.name}{detail}")
            return
        self._refresh()

    def log(self, title: str, detail: str) -> None:
        self.events.append((title, detail))
        self.events = self.events[-10:]
        if not self.console:
            print(f"{title}: {detail}")
            return
        self._refresh()

    def _glyph(self, status: str) -> str:
        style = _status_style(status)
        mark = {
            "done": "●",
            "running": "◍",
            "blocked": "✕",
        }.get(status, "○")
        return f"[{style}]{mark}[/]"

    def _task_table(self):
        table = self.Table(
            title="[muted]run spine[/]",
            title_justify="left",
            expand=True,
            show_lines=False,
            box=self.box.SIMPLE,
            padding=(0, 1),
            border_style="muted",
        )
        table.add_column("", width=2)
        table.add_column("intent", style="active", header_style="muted")
        table.add_column("signal", width=10, header_style="muted")
        table.add_column("evidence", style="muted", header_style="muted")
        for task in self.tasks:
            style = _status_style(task.status)
            table.add_row(
                self._glyph(task.status),
                task.name,
                f"[{style}]{task.status}[/]",
                task.detail,
            )
        return table

    def decision(self, summary: str, risks: list[str], calls: list[str]) -> None:
        self.agent_thought = summary
        self.risks = risks[-4:]
        self.tool_calls = calls[-5:]
        self.metrics["openai"] = "thinking"
        self.panel(summary, "openai")

    def network(self, rows: list[dict[str, Any]]) -> None:
        self.network_rows = rows
        if not rows:
            self.metrics["network"] = "quiet"
            return
        if not self.console:
            for row in rows[:8]:
                print(row)
            return
        self._refresh()

    def gbrain(self, rows: list[dict[str, str]]) -> None:
        self.gbrain_rows = rows[:8]
        self.metrics["gbrain"] = "linked" if rows else self.metrics.get("gbrain", "idle")
        if not self.console:
            for row in rows[:8]:
                print(row)
            return
        self._refresh()

    def _network_table(self):
        table = self.Table(
            title="[muted]network pulse[/]",
            title_justify="left",
            expand=True,
            box=self.box.SIMPLE,
            padding=(0, 1),
            border_style="muted",
        )
        table.add_column("method", width=7, header_style="muted")
        table.add_column("status", width=7, header_style="muted")
        table.add_column("host", header_style="muted")
        table.add_column("path", header_style="muted", style="muted")
        if not self.network_rows:
            table.add_row("", "[muted]· · ·[/]", "[muted]no traffic observed[/]", "")
            return table
        for row in self.network_rows[:8]:
            status = str(row.get("status", ""))
            if status.startswith("2"):
                style = "ok"
            elif status.startswith(("4", "5")):
                style = "fail"
            else:
                style = "run"
            table.add_row(
                str(row.get("method", "")),
                f"[{style}]{status}[/]",
                str(row.get("host", "")),
                str(row.get("path", ""))[:80],
            )
        return table

    def _gbrain_table(self):
        table = self.Table(
            title="[muted]gbrain memory[/]",
            title_justify="left",
            expand=True,
            box=self.box.SIMPLE,
            padding=(0, 1),
            border_style="muted",
        )
        table.add_column("flow", width=18, style="ok", header_style="muted")
        table.add_column("symbol", width=24, header_style="muted")
        table.add_column("evidence", style="muted", header_style="muted")
        if not self.gbrain_rows:
            table.add_row("[muted]pending[/]", "", "[muted]waiting for source provenance[/]")
            return table
        for row in self.gbrain_rows:
            table.add_row(
                row.get("flow", ""),
                row.get("symbol", ""),
                row.get("evidence", "")[:90],
            )
        return table

    def ask(self, prompt: str, password: bool = False) -> str:
        if not self.console:
            suffix = " (hidden)" if password else ""
            return input(f"{prompt}{suffix}: ")
        was_live = self.live is not None
        if was_live:
            self.stop()
        try:
            return self.Prompt.ask(f"[brand]{prompt}[/]", password=password)
        finally:
            if was_live:
                self.start()

    def panel(self, body: str, title: str) -> None:
        self.events.append((title, body))
        self.events = self.events[-10:]
        if not self.console:
            print(f"{title}: {body}")
            return
        self._refresh()

    def _event_table(self):
        table = self.Table(
            title="[muted]live evidence[/]",
            title_justify="left",
            expand=True,
            show_header=False,
            box=self.box.SIMPLE,
            padding=(0, 1),
            border_style="muted",
        )
        table.add_column("source", width=14, style="ok")
        table.add_column("detail", ratio=1, style="muted")
        if not self.events:
            table.add_row("status", "[muted]waiting for first observation[/]")
            return table
        for title, detail in self.events[-7:]:
            table.add_row(title, detail[:600])
        return table

    def _mind_panel(self):
        risks = "\n".join(f"[fail]›[/] {risk}" for risk in self.risks) or "[muted]none surfaced[/]"
        calls = "\n".join(f"[ok]›[/] {call}" for call in self.tool_calls) or "[muted]waiting[/]"
        body = (
            f"[active]current read[/]\n{self.agent_thought[:900]}\n\n"
            f"[fail]risks[/]\n{risks}\n\n"
            f"[ok]next tools[/]\n{calls}"
        )
        return self.Panel(
            body,
            title="[muted]agent mind[/]",
            title_align="left",
            border_style="panel.border",
            box=self.box.ROUNDED,
            padding=(1, 2),
        )

    def _signal_bar(self):
        cells = []
        for label, value in self.metrics.items():
            style = _status_style(value)
            cells.append(f"[muted]{label}[/] [{style}]●[/] [{style}]{value}[/]")
        return self.Padding(
            self.Text.from_markup("    ".join(cells)),
            (0, 0, 1, 1),
        )

    def _header(self):
        wordmark = self.Text(_WORDMARK, style="brand")
        meta = self.Text.from_markup(
            f"[muted]{self.subtitle}[/]\n"
            f"[muted]phase[/]  [active]{self.phase}[/]"
        )
        return self.Padding(
            self.Group(wordmark, self.Text(""), meta),
            (1, 0, 0, 1),
        )

    def _render(self):
        return self.Group(
            self._header(),
            self.Rule(style="rule.line"),
            self._signal_bar(),
            self.Group(self._task_table(), self._mind_panel()),
            self._gbrain_table(),
            self._network_table(),
            self._event_table(),
        )

    def _refresh(self) -> None:
        if self.live:
            self.live.update(self._render())
        elif self.console:
            self.console.print(self._render())

    def final_report(self, markdown: str) -> None:
        self.stop()
        if not self.console:
            print(markdown)
            return
        self.console.print(
            self.Padding(
                self.Panel(
                    self.Markdown(markdown),
                    title="[brand]run report[/]",
                    title_align="left",
                    border_style="ok",
                    box=self.box.ROUNDED,
                    padding=(1, 2),
                ),
                (1, 0),
            )
        )


def _metric_key(task_name: str) -> str:
    lowered = task_name.lower()
    if "gbrain" in lowered:
        return "gbrain"
    if "network" in lowered or "proxy" in lowered:
        return "network"
    if "openai" in lowered:
        return "openai"
    if "simulator" in lowered or "trace" in lowered:
        return "sim"
    return "sim"


def _status_style(status: str) -> str:
    if status in {"done", "passed", "ok", "linked"}:
        return "ok"
    if status in {"running", "thinking"}:
        return "run"
    if status in {"blocked", "failed"}:
        return "fail"
    return "muted"
