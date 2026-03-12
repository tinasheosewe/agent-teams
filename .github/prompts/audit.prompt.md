# Full Codebase Audit

Perform a comprehensive, deep audit of the entire codebase. Scan every file methodically. Do not skim — read thoroughly.

## What to look for

### Bugs & Code-Level Errors
- Race conditions, deadlocks, or unsafe concurrent access to shared state
- Off-by-one errors, nil/null dereferences, force-unwraps, force-casts
- Unreachable code, dead code paths, or impossible conditions
- Missing error handling (unhandled throws, ignored Results, empty catch blocks)
- Resource leaks (unclosed connections, missing cleanup, retain cycles)
- Incorrect state transitions or missing state resets

### Logic & Behavioral Errors
- Features that don't actually do what they claim or intend to do — trace the logic end-to-end and verify it produces the correct result
- Conditions or branches that look right but are subtly wrong (inverted booleans, wrong comparison operators, incorrect enum cases)
- Data transformations that silently lose, corrupt, or misinterpret data
- Flows where user-facing behavior diverges from the apparent intent (e.g., a "save" that doesn't persist, a "delete" that leaves orphaned data, a filter that doesn't actually filter)
- Sequences that depend on order but don't enforce it — steps that can execute out of order or be skipped
- Edge cases the logic doesn't account for (empty collections, zero values, max values, nil/optional paths, first-run states, offline/no-data states)
- Stale or outdated logic that was correct once but no longer matches current models, APIs, or requirements

### Architecture & Design
- Violations of SOLID principles (god classes, tight coupling, leaky abstractions)
- Business logic in the wrong layer (e.g., logic in views, UI in services)
- Duplicated logic that should be extracted (DRY violations)
- Copy-pasted code across files — identify every instance and recommend where to centralize (shared utility, extension, base class, helper module, or internal package)
- Repeated patterns that have drifted apart — same intent implemented slightly differently in multiple places, leading to inconsistent behavior
- Helpers or utilities scattered in arbitrary files instead of living in a dedicated shared location
- Opportunities to consolidate similar classes/structs into a single generic or protocol-driven implementation
- Inconsistent patterns — similar things done differently across the codebase
- Missing protocol abstractions where dependency injection is needed
- Overly complex code that could be simplified without losing correctness

### Error Handling & Resilience
- Silent failures — errors caught and swallowed without logging or surfacing
- Missing validation at boundaries (API responses, user input, file reads)
- Crash-prone patterns (force unwraps, unguarded array access, implicit optionals)
- Missing retry logic or timeout handling for network/external calls

### Code Quality & Style
- Poor naming — unclear, misleading, or abbreviated names
- Functions doing too many things or at mixed abstraction levels
- Deep nesting that should use guard clauses / early returns
- Comments explaining "what" instead of "why" (or missing "why" comments)
- Magic numbers/strings that should be named constants or enums
- Unused imports, unused variables, unused parameters

### Concurrency
- Unprotected shared mutable state
- Main-thread-blocking operations (network, disk I/O on main thread)
- Missing @MainActor annotations on UI-mutating code
- Fire-and-forget Tasks that should be structured

### Testing Gaps
- Public functions/types with no test coverage
- Untested error paths and edge cases
- Tests that test implementation details instead of behavior
- Missing mocks for external dependencies

### Dependencies & Configuration
- Hardcoded secrets, API keys, or URLs that should be in config
- Outdated or unused dependencies
- Missing or incorrect access control (public vs internal vs private)
- Hand-rolled implementations where a well-maintained library would be simpler, more resilient, and less code to maintain

### Performance & Efficiency
- Wrong data structure for the job (e.g., array scans where a dictionary/set lookup would be O(1))
- Redundant work — same value computed multiple times, collections iterated repeatedly when once suffices, data re-fetched when already available
- Values computable at development/build time that are instead calculated at runtime (lookup tables, constants, static mappings)
- Unbatched operations — individual database writes, network calls, or UI updates that should be batched
- Unnecessary allocations in hot paths — large copies, avoidable object creation in loops
- Blocking the main thread with expensive synchronous work

### Type Safety & Correctness
- Raw strings or integers used where enums or strong types would make invalid states unrepresentable
- Stringly-typed APIs, dictionary-based data passing, or Any/AnyObject where concrete types exist
- Implicit conversions or loose typing that could silently produce wrong results

### Logging & Observability
- Key operations (start/end, state transitions, error paths) with no logging — would be invisible when debugging production issues
- Excessive or noisy logging that drowns out meaningful signals
- Inconsistent log levels (errors logged as info, debug noise in production)

### AI Prompts
- Prompts overfitted to specific bugs, errors, or edge cases instead of expressing generic principles
- Prompts that list hardcoded case-by-case handling where a broader instruction would suffice
- Fragile prompts that would break or need updating whenever the data, schema, or requirements change slightly
- Prompts missing clear output format specifications or constraint definitions

### Consistency & Incomplete Changes
- Partial migrations — new patterns introduced alongside old ones without completing the transition
- Orphaned code left behind from refactors (unused functions, stale references, dead imports)
- Inconsistent conventions — the same thing done two different ways in different parts of the codebase

## Output Format

Organize findings by severity:

### 🔴 Critical — Bugs, crashes, data loss, or security issues
### 🟠 High — Architectural problems, missing error handling, race conditions
### 🟡 Medium — Code quality, DRY violations, naming, style issues
### 🔵 Low — Minor improvements, suggestions, nitpicks

For each finding:
1. **File and location** (with line reference)
2. **What's wrong** — concise description of the issue
3. **Why it matters** — impact if left unfixed
4. **Fix** — concrete recommendation or code snippet

After all findings, provide a **Summary** with:
- Total count by severity
- Top 3 most impactful things to fix first
- Overall health assessment of the codebase
