"""Pipeline stage drivers for the labour-migration extraction (CLI backends).

Each module exposes ``main(argv=None) -> int`` and is dispatched through
``migration_parser.cli`` (``python -m migration_parser <stage>``).
"""
