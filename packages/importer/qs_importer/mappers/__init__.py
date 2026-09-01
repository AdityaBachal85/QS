"""Sheet-to-entity mappers.

Each mapper knows one workbook's *layout*.  The domain model knows none of it.
That separation is what lets a differently-shaped project use the same engine:
a new layout is a new mapper, not a schema change.
"""
