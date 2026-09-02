# DBOT QS Platform

A QS / estimation / costing / budgeting platform for real-estate projects, built
to replace a 35-sheet Excel workbook whose failures are all failures of
*plumbing* rather than of judgment.

You enter five kinds of data — room configuration, unit sizes, doors and
windows, rates, project parameters. Everything else is derived: quantities,
deductions, schedules, subtotals, totals. There are no links to maintain and no
ranges to extend.

## Status

**Stage 0, Modules 1–4 and the local application are complete**, and reconcile
against the source workbook.

```
38 PASS   3 EXPLAINED   0 FAIL      -- acceptance GRANTED
125 tests passing
```

## Running it

```bash
make setup     # venv + dependencies (four of them)
make run       # the platform at http://localhost:8000
```

That is the whole thing. **One process.** It serves the browser interface and
the API, and stores everything in one SQLite file (`qs.db`). No database server,
no Docker, no npm, no build step — the interface is plain ES modules served
directly, so there is nothing to compile here or on the server it eventually
moves to.

```bash
make test      # 125 tests, ~6s
make recon     # import the AVS workbook, print Excel vs Platform
make seed      # (re)create qs.db from the workbook
```

## What the interface does

| Screen | What you do there |
|---|---|
| **Room Config** | the floor × unit-type matrix. Type a count, paste a column from Excel, arrow around it |
| **Unit Types & Rooms** | room list per type, and the quantities each room produces — gross, deduction, net |
| **Doors & Windows** | the opening type master, and the schedule counted from the rooms |
| **Rate Library** | basic + laying + wastage; the overall rate is computed and its working is one click away |
| **Parameters** | every constant the engine uses, named and editable |
| **Validation** | the issue list and health score |
| **Reconciliation** | every platform figure beside the workbook's own value |
| **Change log** | every edit, old value and new |

Three behaviours carry the whole design argument:

- **White cells are yours; grey cells are the system's.** A grey cell cannot be
  edited — clicking it opens the derivation panel instead. There is no field, no
  column and no endpoint through which a derived value can be set, which is what
  makes the `Flat Sizes!E57` paste structurally impossible rather than merely
  detectable.
- **Change one number and everything that depends on it moves.** Edit a count in
  Room Config and the flat total, the BHK split, the carpet area and the door
  count all update in the bar at the top — no linking, no dragging a formula
  down. The figures that changed flash so a change is never silent.
- **Nothing missing is drawn as a zero.** An unpriced item renders as `—` with a
  chip, never `₹0`.

`make recon` prints every figure the platform computes beside the workbook's own
cached value, classified PASS (identical to the paisa), EXPLAINED (a difference
of exactly the size a named defect predicts) or FAIL (anything else). A FAIL
blocks acceptance.

## Layout

```
packages/engine/      pure Python. The only place arithmetic lives.
  qs_engine/
    units.py          unit registry + unit-safe quantity arithmetic
    params.py         named project parameters (10.764, 3.28, wastage, ...)
    model.py          the domain model
    graph.py          DAG evaluation, cycle detection, invalidation
    provenance.py     every derived value records what produced it
    validation.py     rules as data, with severities
    rules/            rate_buildup · room_qty · unit_area · schedule
packages/importer/    openpyxl two-pass reader, sheet mappers, reconciliation
packages/app/
  qs_app/
    store.py          ProjectModel <-> SQLite. All SQL lives here and nowhere else
    service.py        the read model: everything the UI shows, from the engine
    server.py         FastAPI. Writes are thin; reads never write
    seed.py           first run: import the workbook into qs.db
web/                  the interface. ES modules, no build step
  grid.js             keyboard navigation, paste from Excel, undo
  panel.js            the derivation panel
  screens/            one file per screen
data/workbooks/       the source workbook
```

The engine imports nothing from the importer, the store or any web layer. That is
what lets every calculation rule carry a test that runs in milliseconds against
the workbook's own numbers — and why the storage and interface choices above cost
nothing to revisit. All SQL is in `store.py`; moving to Postgres later means
rewriting that one file.

## What reconciles today

| Module | Checks | Result |
|---|---|---|
| Room Config | 37 floors · 278 flats · 32 offices · BHK split 28/143/107 · height 121.40 m | all PASS |
| Unit Sizes | all 15 flat-type totals | 14 PASS, 1 EXPLAINED (C-3) |
| Openings | 4 door types · 12 window/railing types · 2,180 doors | all PASS but FRD (C-36) |
| Rate Library | every priced row of both rate lists — 203 rows | all PASS |

## Design rules

**Identity, never position.** Every reference is by a stable id. The workbook
reaches its rates by row offset (`Internal Finishes Flats!B5 = 'Rate List -
Flats'!B6`, repeated across ~150 blocks with hand-counted offsets), so inserting
one row silently re-prices the building. Two tests prove that cannot happen here:
one inserts a rate row, one reverses the entire library, and both assert every
downstream rate is byte-identical.

**Shape is data, never schema.** A unit type owns as many rooms as it has. Four
bathrooms is four rows; no balcony is no row. `test_genericity.py` builds a
second project from nothing — twelve floors, a unit type with four toilets and no
balcony, room types that do not exist in AVS — and asserts it computes end to end
with no code change.

**Derived values are not fields.** `area_sqft` is a function. There is nowhere
to paste a perimeter into an area column.

**Units are carried, not assumed.** A quantity knows what it measures, and
combining incompatible dimensions raises instead of computing.

**Nothing is removed by arithmetic.** An excluded line keeps its value, carries a
reason, and is reported separately — never multiplied by zero.

## Defects found

Sixteen were catalogued in the Phase 1 analysis. Two more were found while
building, both by checking the workbook rather than trusting the report:

**C-35 — skirting deducts door *areas* from a *running-metre* quantity.**
`Internal Finishes Flats!F6 = -(Doors!H5+H6+H7+H9)` = −7.875, where `Doors!H` is
width × height in sq.m and the skirting it reduces is in RM. Skirting should
deduct door *width*: 1.20 + 0.90 + 0.90 + 0.75 = 3.75 RM. Every door is 2.1 m
high, so the deduction is exactly 2.1× too large — 52 rows, 1,448.23 RM of
skirting never priced, **₹5,67,648**.

**C-36 — one entity, two counts.** The two smoke-check lobbies are 36 in
`Flat Sizes!H156/H157` and 37 in `Doors!K137/K138`. Both typed, neither a
formula. The finishing take-off and the door schedule price different buildings.

Also corrected in passing: the Phase 1 report gave the rate build-up test as
`Rate List - Flats!G6 = ₹1,342.90`. The master rate is **₹1,340.118**;
₹1,342.898 is `Internal Finishes Flats!E1998`, a weighted average back-calculated
across ~150 blocks. The gap between them *is* defect C-6, so the suite tests
both.

## Open QS questions

Non-blocking — these import as they stand and are flagged, so building continues.

- **Q-1** curtain wall ×32 vs ×4 (`D&W Schedule!E33`) — moves ₹2.89 Cr, 78% of the office cost sheet. Needed before Module 5's office branch reconciles.
- **Q-3** is the ₹1.98 Cr mains-wiring exclusion (`Electrical!G4 = G104*0`) deliberate?
- **Q-4** what are the 1.12 and 1.08 factors at `Room Conf!AD44/AD45`? They import unnamed and are reported as `PARAMETER_UNNAMED` until someone names them.
- **Q-6** wastage applies to flooring, skirting and frames but not plaster or paint. The build-up methods encode this; confirm it is intended.
- **Q-8** is a door frame `2H + W` (jambs and head) or `2(W + H)` as the workbook computes? The workbook's behaviour is the default.
- **C-36** which smoke-check lobby count is right, 36 or 37?

## Next

**Module 5 — finishing take-off.** The quantity and deduction rules exist and are
tested; Module 5 applies them across every room in the project and aggregates,
replacing 1,451 hand-written rows and 9,472 formulas in `Internal Finishes
Flats`. This is where the money appears.

One thing has to happen first: the rate list and the sizes sheet name rooms
differently (`M. Bed` against `M. Bedroom`, `Toilet With M. Bed` against
`M. Toilet`), which the import already reports as 16 warnings. Until those are
mapped, a finish can be priced for a room that does not exist.

Then Module 6: the estimate grid and cost summary, reproducing
`Cost Sheet Tower!I129` (₹170.56 Cr) and `Summary!D20` (₹226.68 Cr).

## Hosting it later

Copy the folder, `pip install -r requirements.txt`, run the same `make run`
behind nginx or IIS. No node, no Docker, no database server to administer. Back
it up by copying `qs.db`.
