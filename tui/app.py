"""Primary FindIT Textual workspace."""

from __future__ import annotations

import asyncio
from typing import Any

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from .api import APIClient, APIError
from .process import BackendProcess


class ConfirmScreen(ModalScreen[bool]):
    CSS = """
    ConfirmScreen { align: center middle; }
    #confirm-box { width: 64; height: auto; padding: 2; background: $surface; border: thick $error; }
    #confirm-actions { height: 3; align: right middle; }
    """

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Confirm destructive action", id="confirm-title"),
            Static(self.message, id="confirm-message"),
            Label("Press y to confirm · n or Escape to cancel", id="confirm-actions"),
            id="confirm-box",
        )

    def on_key(self, event: events.Key) -> None:
        if event.key.lower() == "y":
            self.dismiss(True)
        elif event.key.lower() in {"n", "escape"}:
            self.dismiss(False)


class HelpScreen(ModalScreen[None]):
    CSS = """
    HelpScreen { align: center middle; }
    #help-box { width: 64; height: auto; padding: 2; background: $surface; border: round $accent; }
    #help-title { text-style: bold; color: $accent; padding-bottom: 1; }
    #help-close { color: $text-muted; padding-top: 1; }
    """

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("FindIT keyboard help", id="help-title"),
            Static("/ search\nEnter inspect\nj/k move · n more\no open · f reveal\na add · d remove\ns sync · S sync all\nq quit", id="help-body"),
            Label("Press Escape or Enter to close", id="help-close"),
            id="help-box",
        )

    def on_key(self, event: events.Key) -> None:
        if event.key in {"escape", "enter", "?"}:
            self.dismiss(None)


class ResultItem(ListItem):
    def __init__(self, result: dict[str, Any], index: int) -> None:
        self.result = result
        super().__init__(Label(f"{index:>2}. {result.get('filename', 'Unknown')}  ·  {result.get('location_label', '')}\n    {result.get('passage_preview', '')}"))


class DirectoryItem(ListItem):
    def __init__(self, directory: dict[str, Any]) -> None:
        self.directory = directory
        super().__init__(Label(f"{directory.get('display_name', 'Directory')}\n    {directory.get('file_count', 0)} files · {directory.get('sync_status', 'UNKNOWN')}"))


class StatusMessage(Message):
    def __init__(self, text: str, error: bool = False) -> None:
        super().__init__()
        self.text = text
        self.error = error


class FindITApp(App[None]):
    TITLE = "FindIT"
    SUB_TITLE = "Find what you remember"
    CSS = """
    Screen { background: $surface; }
    #body { height: 1fr; }
    #sources { width: 27; min-width: 22; border: round $primary-darken-2; padding: 1; }
    #workspace { width: 1fr; }
    #results { height: 1fr; border: round $primary-darken-2; }
    #inspector { width: 38; min-width: 28; border: round $primary-darken-2; padding: 1; }
    #search { margin: 0 1; }
    #status { height: 2; padding: 0 1; color: $text-muted; }
    .panel-title { text-style: bold; color: $accent; padding-bottom: 1; }
    .error { color: $error; }
    .compact #inspector { display: none; }
    .narrow #sources { display: none; }
    """
    BINDINGS = [
        Binding("/", "focus_search", "Search", show=True),
        Binding("enter", "inspect", "Inspect", show=True),
        Binding("j", "next_result", "Next", show=False),
        Binding("k", "previous_result", "Previous", show=False),
        Binding("n", "load_more", "More", show=True),
        Binding("o", "open_document", "Open", show=True),
        Binding("f", "open_folder", "Reveal", show=True),
        Binding("a", "add_directory", "Add folder", show=True),
        Binding("d", "remove_directory", "Remove folder", show=True),
        Binding("s", "sync_directory", "Sync", show=True),
        Binding("S", "sync_all", "Sync all", show=False),
        Binding("?", "help", "Help", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self, client: APIClient | None = None, backend: BackendProcess | None = None) -> None:
        super().__init__()
        self.client = client or APIClient()
        self.backend = backend or BackendProcess(self.client)
        self.results: list[dict[str, Any]] = []
        self.directories: list[dict[str, Any]] = []
        self.selected_result: dict[str, Any] | None = None
        self.selected_directory: dict[str, Any] | None = None
        self.next_offset: int | None = None
        self.active_query = ""
        self.search_generation = 0
        self.active_job_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="sources"):
                yield Label("Sources & jobs", classes="panel-title")
                yield ListView(id="directories")
                yield Static("a add · d remove\ns sync · S sync all", id="source-help")
            with Vertical(id="workspace"):
                yield Input(placeholder="Describe what you remember…", id="search")
                yield Static("Ready", id="status")
                yield ListView(id="results")
            with VerticalScroll(id="inspector"):
                yield Label("Passage inspector", classes="panel-title")
                yield Static("Select a result and press Enter.", id="detail")
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#search", Input).focus()
        self.run_worker(self.initialize(), name="backend-init", exclusive=True)

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 100, "compact")
        self.set_class(event.size.width < 70, "narrow")

    async def initialize(self) -> None:
        try:
            health = await self.backend.ensure_ready()
            self.post_message(StatusMessage(f"Ready · {health.get('total_passages_indexed', 0)} passages indexed"))
            await self.refresh_directories()
        except APIError as exc:
            self.post_message(StatusMessage(str(exc), error=True))

    async def refresh_directories(self) -> None:
        self.directories = await self.client.directories()
        view = self.query_one("#directories", ListView)
        view.clear()
        for directory in self.directories:
            view.append(DirectoryItem(directory))

    def on_unmount(self) -> None:
        self.backend.stop()

    def on_status_message(self, message: StatusMessage) -> None:
        status = self.query_one("#status", Static)
        status.update(message.text)
        status.set_class(message.error, "error")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            await self.execute_search(event.value)

    async def execute_search(self, query: str, append: bool = False) -> None:
        query = query.strip()
        if not query:
            return
        if not append:
            self.search_generation += 1
            self.active_query = query
            self.next_offset = 0
            self.results = []
            self.query_one("#results", ListView).clear()
        generation = self.search_generation
        offset = self.next_offset or 0
        self.post_message(StatusMessage("Searching…"))
        try:
            payload = await self.client.search(query, offset=offset)
        except APIError as exc:
            self.post_message(StatusMessage(str(exc), error=True))
            return
        if generation != self.search_generation:
            return
        new_results = payload.get("results", [])
        self.results.extend(new_results)
        self.next_offset = payload.get("next_offset")
        view = self.query_one("#results", ListView)
        start = len(self.results) - len(new_results) + 1
        for index, result in enumerate(new_results, start=start):
            view.append(ResultItem(result, index))
        self.post_message(StatusMessage(f"{payload.get('total_available', 0)} matching passages · hybrid ranking"))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, ResultItem):
            self.selected_result = event.item.result
            self.run_worker(self.load_detail(self.selected_result["chunk_id"]), name="passage-detail", exclusive=True)
        elif isinstance(event.item, DirectoryItem):
            self.selected_directory = event.item.directory

    async def load_detail(self, chunk_id: str) -> None:
        try:
            detail = await self.client.passage(chunk_id)
            text = detail.get("text", "")
            location = detail.get("location_label", "")
            header = f"{detail.get('filename', 'Unknown')}\n{location}\n{detail.get('display_path', '')}\n\n"
            self.query_one("#detail", Static).update(header + text)
        except APIError as exc:
            self.post_message(StatusMessage(str(exc), error=True))

    async def action_load_more(self) -> None:
        if self.next_offset is not None:
            await self.execute_search(self.active_query, append=True)

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_inspect(self) -> None:
        if self.selected_result:
            self.run_worker(self.load_detail(self.selected_result["chunk_id"]), name="passage-detail", exclusive=True)

    def action_next_result(self) -> None:
        view = self.query_one("#results", ListView)
        if view.index is not None and view.index < len(view) - 1:
            view.index += 1
        view.focus()

    def action_previous_result(self) -> None:
        view = self.query_one("#results", ListView)
        if view.index is not None and view.index > 0:
            view.index -= 1
        view.focus()

    def action_open_document(self) -> None:
        if self.selected_result:
            self.run_worker(self.perform_file_action("open_document"), name="open-document", exclusive=True)

    def action_open_folder(self) -> None:
        if self.selected_result:
            self.run_worker(self.perform_file_action("open_folder"), name="open-folder", exclusive=True)

    async def perform_file_action(self, action: str) -> None:
        try:
            if action == "open_folder":
                await self.client.open_folder(self.selected_result["document_id"])
                self.post_message(StatusMessage(f"Revealed {self.selected_result.get('filename', 'document')}"))
            else:
                await self.client.open_document(self.selected_result["document_id"])
                self.post_message(StatusMessage(f"Opened {self.selected_result.get('filename', 'document')}"))
        except APIError as exc:
            self.post_message(StatusMessage(str(exc), error=True))

    def action_add_directory(self) -> None:
        self.run_worker(self.add_directory(), name="add-directory", exclusive=True)

    async def add_directory(self) -> None:
        try:
            path = await self.client.pick_directory()
            if path:
                result = await self.client.register_directory(path)
                self.active_job_id = result.get("initial_job_id")
                await self.refresh_directories()
                self.post_message(StatusMessage(f"Index queued for {path}"))
                self.run_worker(self.monitor_job(self.active_job_id), name="job-monitor", exclusive=True)
        except APIError as exc:
            self.post_message(StatusMessage(str(exc), error=True))

    def action_remove_directory(self) -> None:
        if not self.selected_directory:
            self.post_message(StatusMessage("Select a directory first", error=True))
            return
        directory = self.selected_directory
        self.push_screen(ConfirmScreen(f"Remove {directory.get('display_name')} from FindIT?\nOriginal files will remain untouched."), lambda confirmed: self.run_worker(self.remove_directory(directory) if confirmed else self.noop(), name="remove-directory", exclusive=True))

    async def noop(self) -> None:
        return

    async def remove_directory(self, directory: dict[str, Any]) -> None:
        try:
            await self.client.remove_directory(directory["directory_id"])
            self.selected_directory = None
            await self.refresh_directories()
            self.post_message(StatusMessage(f"Removed {directory.get('display_name')} from the index"))
        except APIError as exc:
            self.post_message(StatusMessage(str(exc), error=True))

    def action_sync_directory(self) -> None:
        if self.selected_directory:
            self.run_worker(self.start_sync(self.selected_directory["directory_id"]), name="sync-directory", exclusive=True)
        else:
            self.post_message(StatusMessage("Select a directory first", error=True))

    def action_sync_all(self) -> None:
        self.run_worker(self.start_sync_all(), name="sync-all", exclusive=True)

    async def start_sync(self, directory_id: str) -> None:
        try:
            result = await self.client.sync_directory(directory_id)
            await self.monitor_job(result["job_id"])
        except APIError as exc:
            self.post_message(StatusMessage(str(exc), error=True))

    async def start_sync_all(self) -> None:
        try:
            result = await self.client.sync_all()
            self.post_message(StatusMessage(f"Queued {len(result.get('jobs', []))} directory sync jobs"))
            for job in result.get("jobs", []):
                await self.monitor_job(job["job_id"])
        except APIError as exc:
            self.post_message(StatusMessage(str(exc), error=True))

    async def monitor_job(self, job_id: str | None) -> None:
        if not job_id:
            return
        while True:
            try:
                job = await self.client.job(job_id)
            except APIError as exc:
                self.post_message(StatusMessage(str(exc), error=True))
                return
            self.post_message(StatusMessage(f"{job.get('stage', 'PROCESSING')} · {job.get('files_processed', 0)}/{job.get('files_discovered', 0)} files · {job.get('passages_created', 0)} passages"))
            if job.get("status") in {"COMPLETED", "FAILED"}:
                if job.get("status") == "FAILED":
                    self.post_message(StatusMessage(job.get("error_summary") or "Indexing failed", error=True))
                await self.refresh_directories()
                return
            await asyncio.sleep(0.5)

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

