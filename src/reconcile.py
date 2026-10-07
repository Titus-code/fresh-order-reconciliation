"""Command-line entry point for the validated reconciliation engine."""

from reconcile_engine import main, reconcile, write_outputs

__all__ = ["main", "reconcile", "write_outputs"]


if __name__ == "__main__":
    raise SystemExit(main())
