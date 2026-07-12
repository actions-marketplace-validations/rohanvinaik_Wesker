"""A capacity-aware memory guard for the mutation engine.

Mutation profiling materializes a function's whole mutant set and accumulates its
kill/survivor records in RAM. For one function that is small, but nothing bounds it
in principle — a pathologically large function, or a long-lived host that never
releases between calls, could grow without a ceiling. This guard gives that ceiling
a GUARANTEE rather than trusting scope and process-exit:

  * the budget is auto-set from the machine's own capacity — a modest, non-intrusive
    fraction of total RAM, so a run never dominates the system;
  * it is a value the user can select (``WESKER_MEM_BUDGET_MB``, or an explicit
    argument), overriding the default;
  * when a run crosses the budget it stops accumulating and reclaims — the caller
    dumps transient state instead of climbing past the ceiling.

Stdlib only (``os`` + ``resource``); no psutil dependency.
"""

from __future__ import annotations

import gc
import os
import resource
import sys

_MB = 1024 * 1024
_GB = 1024 * _MB

# Non-intrusive default: an eighth of system RAM, clamped so it is neither trivially
# small on a tiny box nor greedy on a large one. The user overrides this per their
# machine; the fraction is only the sensible starting point.
_DEFAULT_FRACTION = 8
_DEFAULT_FLOOR = 256 * _MB
_DEFAULT_CEILING = 2 * _GB


def system_memory_bytes() -> int:
    """Total physical RAM, or a conservative 4 GB fallback when it cannot be read
    (so the budget is never accidentally unbounded)."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        return 4 * _GB


def default_budget_bytes(system_bytes: int | None = None) -> int:
    """The sensible, non-intrusive default budget: ``system_RAM / 8``, clamped to
    [256 MB, 2 GB]. Pure in ``system_bytes`` so it is testable without reading the
    host."""
    total = system_bytes if system_bytes is not None else system_memory_bytes()
    return max(_DEFAULT_FLOOR, min(total // _DEFAULT_FRACTION, _DEFAULT_CEILING))


def resolve_budget(explicit_mb: int | None = None) -> int:
    """The active budget in bytes, most-specific source winning: an explicit
    argument, else ``WESKER_MEM_BUDGET_MB`` from the environment, else the
    capacity-derived default. A non-positive selection means "unbounded"
    (``sys.maxsize``) — the user opting out, on purpose."""
    if explicit_mb is not None:
        return explicit_mb * _MB if explicit_mb > 0 else sys.maxsize
    env = os.environ.get("WESKER_MEM_BUDGET_MB")
    if env is not None:
        try:
            value = int(env)
            return value * _MB if value > 0 else sys.maxsize
        except ValueError:
            pass
    return default_budget_bytes()


def process_rss_bytes() -> int:
    """This process's peak resident set size. ``ru_maxrss`` is bytes on macOS and
    kilobytes on Linux — normalized to bytes. Peak (not instantaneous) is the
    conservative signal: once the peak crosses the budget the run has already
    demanded that much, so stopping there is the guarantee."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def over_budget(budget_bytes: int | None = None) -> bool:
    """True when this process has crossed the memory budget and must stop growing."""
    budget = budget_bytes if budget_bytes is not None else resolve_budget()
    return process_rss_bytes() > budget


def reclaim() -> None:
    """Force a collection to release whatever transient analysis the caller just
    dropped — the "dump" half of the guard, made explicit rather than left to the
    collector's own schedule."""
    gc.collect()


def telemetry(budget_bytes: int | None = None) -> str:
    """A one-line, commonsense memory report for a CLI footer: what this run used,
    against the budget and the machine, with an offload hint when it runs hot. Cheap
    (one getrusage) and never fails — visibility, not enforcement."""
    budget = budget_bytes if budget_bytes is not None else resolve_budget()
    rss = process_rss_bytes()
    total = system_memory_bytes()
    unbounded = budget >= sys.maxsize
    if unbounded:
        return f"mem: {rss // _MB} MB used · budget OFF · system {total // _GB} GB"
    pct = round(100 * rss / budget) if budget else 0
    hot = pct >= 80
    hint = "  ⚠ near budget — offload: `purge` to clear caches, or raise WESKER_MEM_BUDGET_MB" if hot else ""
    return f"mem: {rss // _MB} MB / {budget // _MB} MB budget ({pct}%) · system {total // _GB} GB{hint}"


def purge_caches(project_root: str) -> tuple[tuple[str, ...], int]:
    """Delete regeneratable analysis cruft under ``project_root`` — the function
    result cache and the mutation/mcdc reports that a prior run left in ``.wesker/``.

    Returns ``(removed_paths, reclaimed_bytes)``. Generated TEST files are the
    product, not cruft, and are never touched. Everything removed here is rebuilt on
    the next run from the current code, so purging can only cost recomputation, never
    correctness — which is the point: a clean restart that guarantees no stale state
    lingers."""
    wesker_dir = os.path.join(project_root, ".wesker")
    targets = ("function_cache.json", "mutation_report.json", "mcdc_report.json")
    removed: list[str] = []
    reclaimed = 0
    for name in targets:
        path = os.path.join(wesker_dir, name)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        try:
            os.remove(path)
        except OSError:
            continue
        removed.append(path)
        reclaimed += size
    return tuple(removed), reclaimed
