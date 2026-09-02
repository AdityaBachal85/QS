# Working in this repository

## What this is

A QS / estimation / costing platform replacing a 35-sheet Excel workbook.
The workbook is the specification *and* the test oracle: it is in
`data/workbooks/`, and `make recon` compares every figure the platform computes
against its cached values.

## Non-negotiables

These are not style preferences. Each exists because of a specific defect in the
source workbook, and there is a test asserting it.

1. **All arithmetic lives in `packages/engine`.** Not in the importer, not in
   the API, not in the UI, not in SQL. The engine imports nothing from any other
   package.

2. **Reference by id, never by position.** No calculation may depend on the
   order of a list or the index of a row. Two tests
   (`test_module4_rates.py::test_c6_*`) insert and reorder the rate library and
   assert nothing moves.

3. **Derived values are functions, not fields.** If a value can be computed, it
   must not be storable. `area_sqft` is the canonical example.

4. **Quantities carry units.** Use `qs_engine.units.Quantity`, never a bare
   float, anywhere a deduction or comparison happens. Combining dimensions must
   raise.

5. **Never assume shape.** No code may assume a number of rooms, floors, unit
   types, opening types or rate rows. `test_genericity.py` builds a differently
   shaped project and must keep passing with no code change.

6. **Nothing is removed by arithmetic.** No `* 0`, no dropping a record to
   exclude it. Excluded things keep their value and carry a reason.

7. **Magic numbers are parameters.** Anything like 10.764, 3.28, 1.1, 0.15 goes
   in `params.py` with a description. A parameter without a description is
   reported as `PARAMETER_UNNAMED`.

8. **The UI computes nothing.** Every figure on screen comes from an API call
   that came from the engine. If a number is being worked out in JavaScript,
   it is in the wrong place.

9. **All SQL lives in `packages/app/qs_app/store.py`.** Nothing else in the
   codebase knows a database exists.

## Running it

`make run` — one process, `qs.db`, http://localhost:8000. No Docker, no npm.

## Before changing a calculation

Run `make recon`. If a line moves from PASS, you have changed a number the
workbook agrees with — either revert, or add an expected-delta entry in
`reconcile.py` explaining exactly why and by how much. An unexplained difference
fails acceptance.

## Import philosophy

Nothing is auto-corrected. Defects import as they stand, get flagged, and change
only when someone approves the change. When the platform's number differs from
the workbook's, that difference must be *predicted* — see the expected-delta
ledger in `reconcile.py`.

## Commit style

Reference the defect number (C-3, C-35, ...) when a change addresses one.
