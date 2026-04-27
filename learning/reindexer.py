"""
Reindexer — detects schema changes and re-embeds only the affected tables.

Designed to be run on a schedule (e.g. every hour via APScheduler) or
triggered manually after a schema change. Only changed tables are
re-embedded, keeping the process fast even with large catalogs.
"""

from __future__ import annotations

from embeddings.schema_embedder import index_table
from learning.change_detector import TableChange, detect_changes, save_snapshot


def reindex_changed(verbose: bool = True) -> dict:
    """
    Detect changes and re-embed affected tables.

    Returns a summary dict:
      checked    — total tables checked
      reindexed  — tables successfully re-embedded
      skipped    — tables that failed or were deleted
      changes    — list of TableChange objects
    """
    changes = detect_changes()

    if not changes:
        if verbose:
            print("No schema changes detected. Nothing to reindex.")
        return {"checked": 0, "reindexed": 0, "skipped": 0, "changes": []}

    if verbose:
        print(f"Detected {len(changes)} change(s):")
        for c in changes:
            print(f"  {c.schema}.{c.table} — {c.reason}")

    reindexed = 0
    skipped = 0

    for change in changes:
        if change.reason == "deleted":
            if verbose:
                print(f"  Skipping deleted table {change.schema}.{change.table}")
            skipped += 1
            continue

        if verbose:
            print(f"  Re-indexing {change.schema}.{change.table}…", end=" ")

        success = index_table(change.schema, change.table)
        if success:
            reindexed += 1
            if verbose:
                print("done")
        else:
            skipped += 1
            if verbose:
                print("failed")

    # Update the snapshot so next run has the new baseline
    save_snapshot()

    if verbose:
        print(f"\nReindex complete: {reindexed} updated, {skipped} skipped.")

    return {
        "checked": len(changes),
        "reindexed": reindexed,
        "skipped": skipped,
        "changes": [{"schema": c.schema, "table": c.table, "reason": c.reason} for c in changes],
    }


def full_reindex(verbose: bool = True) -> int:
    """Force a full re-index of all tables and refresh the snapshot."""
    from embeddings.schema_embedder import index_all
    n = index_all(force_reset=True)
    save_snapshot()
    return n


if __name__ == "__main__":
    reindex_changed()
