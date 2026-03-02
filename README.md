# Moonshot: Deterministic Knowledge Structure

This moonshot aims to design a new AI-native data structure for storing and reasoning over long-context factual knowledge.

Core problem:
- Current storage patterns are brittle for facts expressed in different language forms.
- Exact-match keys lose semantic equivalence.
- Fuzzy retrieval is useful but often nondeterministic.
- Chronology, provenance, edits, and sync conflicts are hard to represent cleanly.

Core thesis:
- Better knowledge structure first, then simpler and more trustworthy reasoning.
- If storage is semantically grounded and operationally rigorous, retrieval and planning become more deterministic.

## Operating Mode

This moonshot is now in implementation mode:

- implement small deterministic behavior slices
- write tests for each slice
- run tests every iteration and report exact pass/fail outcomes
- keep scope locked to a practical V1 core
- update research docs to reflect implemented behavior, not speculation

## Scope

Build a V1 AI-native fact structure that supports:
- semantic equivalence across paraphrases
- explicit fact-to-fact relations
- chronology and revision history
- provenance and confidence tracking
- deterministic querying and update semantics
- multi-agent sync and conflict resolution

## Layout

```
moonshot-deterministic-knowledge-structure/
  README.md
  run-planning.ps1
  watch-planning.ps1
  prompts/
    planning-worker.txt
    planning-condition.txt
    runtime-directive.txt
  src/ (or code/)
  tests/
  research/
    INDEX.md
    STATE.md
    SYSTEM_THESIS.md
    MENTAL_LAB_LOG.md
    FAILURE_MODES.md
    EVALUATION_RUBRIC.md
    DECISION_LOG.md
    EXECUTION_GATE.md
```

## Continuum Usage

From this folder:

```powershell
./run-planning.ps1 -EchoProgress -EchoErrors
```

Default run behavior includes automated post-iteration verification:
- command: `tools\post_iter_verify.cmd`
- timeout: `180` seconds
- adaptive control file: `prompts\runtime-directive.txt` (worker updates this when stagnation is detected)

The runner injects `prompts\runtime-directive.txt` into every worker prompt on each iteration (`-DirectiveFile`), so strategy updates in that file take effect immediately next cycle.

Override verification command if needed:

```powershell
./run-planning.ps1 -PostIterCommand "python -m pytest -q tests\unit" -PostIterTimeout 300
```

Disable judge checks only if needed:

```powershell
./run-planning.ps1 -NoJudge
```

Watch live state:

```powershell
./watch-planning.ps1
```
