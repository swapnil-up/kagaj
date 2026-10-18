"""KUKL water-distribution schedule extraction pipeline.

KUKL (Kathmandu Upatyaka Khanepani Limited) publishes monthly water-distribution
schedules per branch office on https://kukl.org.np/downloads/water-distribution-schedule.

Two source formats are in active use:

* **xlsx/doc** — modern format. One workbook per branch, one sheet per reservoir /
  DMA / pumping group. Human-readable Nepali tables with no fixed schema.
* **pdf** — legacy and some current branches. Either a vector table (whose
  Devanagari text layer is a legacy font and extracts garbled) or a scan; both
  are recovered with PaddleOCR.

Because the layouts differ branch-to-branch and month-to-month, the pipeline does
NOT hard-code a per-branch parser. It flattens every source into reading-order
text and hands that to Gemini with a fixed JSON schema (see :mod:`water_parser.schema`),
producing one normalised ``zone`` list per branch.

Public entry point is the CLI::

    python -m water_parser.cli scrape
    python -m water_parser.cli process --month 2083_Ashoj
    python -m water_parser.cli build
"""

__all__ = ["paths", "schema", "text", "gemini"]
