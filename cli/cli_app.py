import argparse
from pathlib import Path
import sys
import time
from typing import List, Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from cli.config import DEFAULT_CONFIG, SearchConfig
from cli.models import SearchResult
from cli.pipeline import DocumentSearchEngine

console = Console()


def format_bytes(num_bytes: int) -> str:
    """Format bytes into readable units."""
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} TB"


def resolve_target_path(path_str: str) -> Path:
    """Resolve paths including ~ expansion and user directory shortcuts like Downloads."""
    expanded = Path(path_str).expanduser()
    if expanded.exists():
        return expanded.resolve()

    resolved = expanded.resolve()
    if resolved.exists():
        return resolved

    user_home = Path.home()
    user_candidate = user_home / path_str
    if user_candidate.exists():
        return user_candidate.resolve()

    onedrive = user_home / "OneDrive"
    if onedrive.exists() and (onedrive / path_str).exists():
        return (onedrive / path_str).resolve()

    return resolved


def render_search_results(query: str, results: List[SearchResult], mode: str, elapsed_ms: float) -> None:
    """Render search results with rich formatting and metadata highlights."""
    if not results:
        console.print(Panel(f"[yellow]No matching passages found for:[/yellow] '{query}'", title="Results", border_style="yellow"))
        return

    header_text = Text()
    header_text.append(f"Query: '{query}' | Mode: ", style="bold")
    header_text.append(f"{mode.upper()}", style="bold cyan")
    header_text.append(f" | Found {len(results)} passages in {elapsed_ms:.1f}ms", style="italic green")
    console.print(header_text)
    console.print()

    for idx, r in enumerate(results, start=1):
        title_text = f"#{idx} | {r.filename} | {r.location} | Score: {r.score:.4f}"
        
        info_lines = []
        info_lines.append(f"[dim]File Path:[/dim] {r.file_path}")
        
        score_parts = []
        if r.dense_score is not None:
            dense_rank_str = f" (#{r.dense_rank})" if r.dense_rank else ""
            score_parts.append(f"Dense Similarity: [bold green]{r.dense_score:.4f}[/bold green]{dense_rank_str}")
        if r.bm25_score is not None:
            bm25_rank_str = f" (#{r.bm25_rank})" if r.bm25_rank else ""
            score_parts.append(f"BM25 Score: [bold magenta]{r.bm25_score:.2f}[/bold magenta]{bm25_rank_str}")
        if mode == "hybrid":
            score_parts.append(f"RRF Rank Fusion Score: [bold cyan]{r.score:.5f}[/bold cyan]")
            
        if score_parts:
            info_lines.append(" | ".join(score_parts))

        snippet_text = r.text.strip()
        content = "\n".join(info_lines) + "\n\n" + f"[white]{snippet_text}[/white]"

        console.print(
            Panel(
                content,
                title=f"[bold blue]{title_text}[/bold blue]",
                border_style="cyan" if idx == 1 else "bright_black",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )


def cmd_index(engine: DocumentSearchEngine, target_path: str, docs_only: bool = False, clear_first: bool = False) -> None:
    """Index a target file or folder."""
    if clear_first:
        engine.clear()
        console.print("[yellow]Cleared previous index before starting.[/yellow]")

    target = resolve_target_path(target_path)
    if not target.exists():
        console.print(f"[bold red]Error:[/bold red] Target path does not exist: {target}")
        console.print("[dim]Tip: You can provide the full path from File Explorer, e.g.:[/dim]")
        console.print(f"  [cyan]python cli.py index \"{Path.home() / 'Downloads'}\"[/cyan]")
        sys.exit(1)

    mode_str = " (Documents only: .pdf, .docx, .pptx, .txt, .md)" if docs_only else ""
    console.print(f"[bold green]Starting indexing for:[/bold green] {target}{mode_str}")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("[cyan]Scanning and indexing files...", total=None)

        def on_progress(filename: str, current: int, total: int) -> None:
            progress.update(
                task_id,
                total=total,
                completed=current,
                description=f"[cyan]Processing ({current}/{total}): [yellow]{filename}[/yellow]",
            )

        t0 = time.time()
        indexed_count = engine.index_path(target, progress_callback=on_progress, docs_only=docs_only)
        elapsed = time.time() - t0

    stats = engine.get_stats()
    console.print()
    console.print(
        Panel(
            f"[bold green]Indexing Complete![/bold green]\n\n"
            f"• Documents Processed: [bold]{indexed_count}[/bold]\n"
            f"• Total Documents in Index: [bold]{stats.total_documents}[/bold]\n"
            f"• Total Chunks: [bold]{stats.total_chunks}[/bold]\n"
            f"• Total Tokens: [bold]{stats.total_tokens:,}[/bold]\n"
            f"• Time Elapsed: [bold]{elapsed:.2f}s[/bold]\n"
            f"• SQLite DB: [dim]{stats.db_size_bytes} bytes[/dim] | "
            f"FAISS: [dim]{stats.faiss_size_bytes} bytes[/dim] | "
            f"BM25: [dim]{stats.bm25_size_bytes} bytes[/dim]",
            title="[bold cyan]Index Summary[/bold cyan]",
            border_style="green",
        )
    )


def cmd_search(engine: DocumentSearchEngine, query: str, mode: str = "hybrid", top_k: int = 5) -> None:
    """Execute search query and display results."""
    t0 = time.time()
    results = engine.search(query=query, mode=mode, top_k=top_k)
    elapsed_ms = (time.time() - t0) * 1000.0
    render_search_results(query, results, mode, elapsed_ms)


def cmd_stats(engine: DocumentSearchEngine) -> None:
    """Display index statistics."""
    stats = engine.get_stats()

    table = Table(title="Semantic Search Index Overview", box=box.ROUNDED)
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")

    table.add_row("Total Indexed Documents", str(stats.total_documents))
    table.add_row("Total Chunks", str(stats.total_chunks))
    table.add_row("Total Tokens (BM25)", f"{stats.total_tokens:,}")
    table.add_row("SQLite DB Size", format_bytes(stats.db_size_bytes))
    table.add_row("FAISS Vector Index Size", format_bytes(stats.faiss_size_bytes))
    table.add_row("BM25 Index Size", format_bytes(stats.bm25_size_bytes))
    table.add_row("Last Indexed Timestamp", stats.last_indexed_at or "Never")

    console.print(table)

    if stats.file_types:
        type_table = Table(title="Indexed Document Types", box=box.SIMPLE)
        type_table.add_column("Extension", style="yellow")
        type_table.add_column("Count", style="green")
        for ext, count in stats.file_types.items():
            type_table.add_row(ext, str(count))
        console.print(type_table)


def cmd_interactive(engine: DocumentSearchEngine) -> None:
    """Run interactive terminal search REPL."""
    console.print(
        Panel(
            "[bold cyan]Interactive Document Search Console[/bold cyan]\n"
            "Commands:\n"
            " • Enter any natural-language or keyword query to search\n"
            " • [bold]/mode hybrid|dense|bm25[/bold] - Switch retrieval mode\n"
            " • [bold]/topk <number>[/bold] - Adjust number of results (default: 5)\n"
            " • [bold]/stats[/bold] - Show index statistics\n"
            " • [bold]/help[/bold] - Display this help message\n"
            " • [bold]/exit[/bold] or [bold]quit[/bold] - Exit console",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )

    current_mode = "hybrid"
    current_top_k = 5

    while True:
        try:
            prompt_str = f"[{current_mode}|k={current_top_k}] Search"
            user_input = Prompt.ask(f"[bold green]{prompt_str}[/bold green]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Exiting search console. Goodbye![/yellow]")
            break

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit", "/exit", "/quit"}:
            console.print("[yellow]Exiting search console. Goodbye![/yellow]")
            break

        if user_input.startswith("/mode"):
            parts = user_input.split()
            if len(parts) > 1 and parts[1].lower() in {"hybrid", "dense", "bm25"}:
                current_mode = parts[1].lower()
                console.print(f"[green]Switched retrieval mode to: [bold]{current_mode.upper()}[/bold][/green]")
            else:
                console.print("[red]Invalid mode. Choose 'hybrid', 'dense', or 'bm25'.[/red]")
            continue

        if user_input.startswith("/topk"):
            parts = user_input.split()
            if len(parts) > 1 and parts[1].isdigit():
                current_top_k = int(parts[1])
                console.print(f"[green]Top-K set to: [bold]{current_top_k}[/bold][/green]")
            else:
                console.print("[red]Please provide a valid integer (e.g., /topk 5).[/red]")
            continue

        if user_input.lower() in {"/stats", "stats"}:
            cmd_stats(engine)
            continue

        if user_input.lower() in {"/help", "help"}:
            console.print("Commands: /mode <hybrid|dense|bm25>, /topk <number>, /stats, /exit")
            continue

        cmd_search(engine, query=user_input, mode=current_mode, top_k=current_top_k)
        console.print()


def cmd_evaluate(engine: DocumentSearchEngine, benchmark_file: Optional[str] = None) -> None:
    """Run retrieval evaluation benchmark comparing TF-IDF, BM25, Dense, and Hybrid."""
    console.print("[bold cyan]Running IR Benchmark Evaluation...[/bold cyan]")
    
    test_cases = []
    if benchmark_file and Path(benchmark_file).exists():
        import json
        with open(benchmark_file, "r", encoding="utf-8") as f:
            test_cases = json.load(f)
    else:
        test_cases = [
            {
                "query": "What CGPA do I need to pass?",
                "relevant_keywords": ["cgpa", "grade point average", "pass", "programme", "cumulative"],
            },
            {
                "query": "minimum requirements for graduation",
                "relevant_keywords": ["graduation", "degree", "credits", "curriculum", "regulations"],
            },
            {
                "query": "attendance policy and penalties",
                "relevant_keywords": ["attendance", "absence", "penalty", "medical", "leave"],
            },
        ]

    eval_results = engine.evaluator.evaluate_benchmark(test_cases, k_values=[1, 3, 5])
    if not eval_results:
        console.print("[yellow]Index is empty. Index documents before running evaluation.[/yellow]")
        return

    table = Table(
        title="Information Retrieval Method Comparison (Precision@K, Recall@K, MRR, NDCG@K)",
        box=box.ROUNDED,
    )
    table.add_column("Method", style="bold cyan")
    table.add_column("K", style="magenta")
    table.add_column("Precision@K", style="green")
    table.add_column("Recall@K", style="blue")
    table.add_column("MRR", style="yellow")
    table.add_column("NDCG@K", style="bold yellow")

    for method, metrics_list in eval_results.items():
        for m in metrics_list:
            table.add_row(
                m.method,
                str(m.k),
                f"{m.precision_at_k:.4f}",
                f"{m.recall_at_k:.4f}",
                f"{m.mrr:.4f}",
                f"{m.ndcg:.4f}",
            )

    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Semanty Document Search and Retrieval System CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # index command
    parser_index = subparsers.add_parser("index", help="Index a document or directory")
    parser_index.add_argument("path", help="Path to document file or directory to index")
    parser_index.add_argument(
        "--docs-only",
        action="store_true",
        help="Only index human-readable documents (.pdf, .docx, .pptx, .txt, .md), skipping code/data dumps",
    )
    parser_index.add_argument(
        "--clear-first",
        action="store_true",
        help="Clear previous index before starting new indexing",
    )

    # search command
    parser_search = subparsers.add_parser("search", help="Search indexed documents")
    parser_search.add_argument("query", help="Natural-language or keyword search query")
    parser_search.add_argument(
        "--mode",
        choices=["hybrid", "dense", "bm25"],
        default="hybrid",
        help="Retrieval mode (default: hybrid)",
    )
    parser_search.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of results to return (default: 5)",
    )

    # interactive command
    subparsers.add_parser("interactive", help="Start interactive search terminal shell")

    # stats command
    subparsers.add_parser("stats", help="Display index statistics and metadata store info")

    # evaluate command
    parser_eval = subparsers.add_parser("evaluate", help="Evaluate IR metrics (TF-IDF vs BM25 vs Dense vs Hybrid)")
    parser_eval.add_argument("--benchmark", help="Optional JSON file with custom benchmark queries", default=None)

    # clear command
    subparsers.add_parser("clear", help="Clear all indexed documents and reset database")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    engine = DocumentSearchEngine()

    if args.command == "index":
        cmd_index(engine, args.path, docs_only=args.docs_only, clear_first=args.clear_first)
    elif args.command == "search":
        cmd_search(engine, args.query, mode=args.mode, top_k=args.top_k)
    elif args.command == "interactive":
        cmd_interactive(engine)
    elif args.command == "stats":
        cmd_stats(engine)
    elif args.command == "evaluate":
        cmd_evaluate(engine, args.benchmark)
    elif args.command == "clear":
        engine.clear()
        console.print("[bold green]Successfully cleared all indexes and metadata database.[/bold green]")


if __name__ == "__main__":
    main()
