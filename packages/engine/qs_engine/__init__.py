"""The DBOT QS calculation engine.

Pure Python.  No web framework, no database, no I/O.  It takes a project model
in and returns computed values plus provenance out, which is what lets every
rule carry a test that runs against the source workbook's own numbers in
milliseconds.
"""
