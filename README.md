# Click evidence-reuse benchmark

An independent, deterministic benchmark for
[Click](https://github.com/grapefruit0205/click) cross-revision verification
evidence reuse.

It contains three separately runnable suites:

- a 500-cell evidence-reuse matrix; and
- a 100-case black-box dependency-omission suite; and
- a 100-case black-box unnecessary-rerun suite.

The suite asks one question: after a repository or environment changes, is it
safe to trust an earlier verification result? It does not call an LLM. It runs
Click's production decision function directly and separately records:

- the semantic oracle (`reuse_safe: true/false`);
- Click's reuse or rerun decision; and
- the result of actually rerunning the fixture test.

## Independence boundary

The benchmark lives outside the product repository. `target.lock.json` pins the
exact Click commit being evaluated, and the runner refuses a checkout at a
different revision. This keeps benchmark history, fixtures, scenario labels,
and reports separate from product implementation changes.

Within this repository:

- `scenarios.py` defines semantic expectations from fixture behavior and does
  not inspect Click manifests;
- `manifests.py` defines five dependency-map states and does not import the
  oracle;
- `runtime_observations.py` defines controlled baseline inputs independently
  from scenario labels; and
- `runner.py` combines those inputs and invokes
  `hooks.click_verification.dependency_receipt_matches` from the pinned target.

This separation reduces circularity; it does not make synthetic fixtures equal
to production telemetry. A later shadow phase can feed real observations into
the same decision and reporting boundary.

## The independent 100-case omission suite

This suite is specifically designed to test the concern that a benchmark may
simply mirror Click's decision rules. Its case generator, fixture builder, and
output parser do not import Click hooks or inspect the decision implementation.

For each case it:

1. runs a real Python, Node.js, C, or Java fixture;
2. parses dependency paths emitted by that running fixture;
3. selects one proven dependency with a reproducible random seed;
4. writes a manifest that deliberately omits that path;
5. records the complete baseline observation in Click's receipt;
6. changes only the omitted dependency;
7. calls Click's production cross-revision decision function; and
8. separately reruns the fixture to confirm that the change really breaks it.

The default seed is `20260902`. Languages are stratified rather than left to
chance: Python, Node.js, C, and Java each receive 25 cases. Within each language,
case order, paths, and nested omission targets are seeded. The five behavior
types each receive 20 cases: direct file reads, nested pointers, directory
membership, previously missing files, and child-process reads.

Run only these 100 cases:

```text
# Linux or macOS
python3 run_benchmark.py --suite dependency-omission-100 -- --fail-on-unsafe --fail-on-oracle-mismatch

# Windows
py -3 run_benchmark.py --suite dependency-omission-100 -- --fail-on-unsafe --fail-on-oracle-mismatch
```

Use `--seed NUMBER` after the separator to generate another reproducible set,
or `--language python` to run one 25-case language slice. The report keeps the
oracle, Click decision, and actual rerun result in separate JSON fields.

The initial pinned result is 100/100 correct invalidations, zero unsafe reuse,
and 100/100 actual rerun failures. This means Click caught every controlled
omission tested here; it does not prove that a production observer can see every
dependency in every real repository.

## The independent 100-case unnecessary-rerun suite

This safe-change suite measures the opposite failure mode: Click rerunning a
check even though old evidence is still valid. Its generator also does not
import Click rules.

Each case first obtains a complete dependency list from a real fixture process.
It then changes a tracked documentation, unused example, unread asset, tooling
note, or unrelated source file that is absent from that observation. Click's
decision and a real passing rerun are recorded separately. The suite includes
exact manifests and broad repository, runtime, mixed, and language envelopes.

Python, Node.js, C, and Java each receive 25 cases with the fixed default seed
`20260903`. Run only these 100 safe-change cases with:

```text
# Linux or macOS
python3 run_benchmark.py --suite unnecessary-rerun-100 -- --fail-on-unnecessary-rerun --fail-on-oracle-mismatch

# Windows
py -3 run_benchmark.py --suite unnecessary-rerun-100 -- --fail-on-unnecessary-rerun --fail-on-oracle-mismatch
```

The initial pinned result is 100/100 correct safe reuses, zero unnecessary
reruns, and 100/100 actual rerun passes. This measures cache efficiency only for
the controlled safe changes in this suite; it does not replace the separate
dependency-omission safety result.

## The 500-case matrix

The suite crosses 100 semantic mutations with five manifest states:

| Fixture | Runtime | Mutations | Matrix cases |
| --- | --- | ---: | ---: |
| Python service | Python `unittest` | 20 | 100 |
| Python package | Python `unittest` | 20 | 100 |
| Node CommonJS | Node test runner | 10 | 50 |
| Node ESM | Node test runner | 10 | 50 |
| C project | GCC and native binary | 20 | 100 |
| Java project | JDK 21 | 20 | 100 |
| **Total** | **4 languages, 6 fixtures** | **100** | **500** |

The five manifest states are complete/narrow, broad, silently incomplete,
changed after the baseline commit, and malformed after the baseline commit.
The 100 semantic mutations contain 40 safe changes and 60 changes that must
invalidate old evidence, producing 200 safe-reuse and 300 must-rerun matrix
cases.

## Run it yourself

Clone this repository, then run one command. The helper downloads the official
Click revision from `target.lock.json`, resolves it to a full SHA, and records
that SHA in the report. A GitHub account or token is not required; downloading
the repository as a ZIP also works.

```text
# Linux or macOS
python3 run_benchmark.py -- --fail-on-unsafe

# Windows
py -3 run_benchmark.py -- --fail-on-unsafe
```

To evaluate a public fork or another Click-compatible repository:

```text
python3 run_benchmark.py \
  --target-repository OWNER/REPO \
  --target-ref BRANCH_OR_COMMIT \
  -- --fail-on-unsafe
```

The downloader uses direct argument arrays rather than a shell and accepts only
an `OWNER/REPO` name or GitHub HTTPS URL. The selected target's Python hooks are
imported and executed, so only evaluate code you trust.

Anyone can also fork this benchmark repository and use **Actions → CI → Run
workflow** to enter a target repository and branch, tag, or commit and choose
a suite or a suite group. The public job runs portability checks on Linux,
macOS, and Windows. A normal main-branch push runs both independent 100-case
suites; the older 500-cell matrix runs only when explicitly selected in the
manual workflow.

Python, Node.js, GCC, and a JDK are required. When a local JDK is unavailable,
the runner can use its digest-pinned, network-disabled Temurin container; it
never pulls the image implicitly.

Focused runs and JSON output are also available:

```text
python3 run_benchmark.py -- --manifest exact
python3 run_benchmark.py -- --profile c-native
python3 run_benchmark.py -- --json
```

## Reading the report

The report shows:

- **Correct reuse:** an irrelevant change safely reused old evidence.
- **Correct invalidation:** a relevant change caused a rerun.
- **Unsafe reuse:** a relevant change incorrectly trusted old evidence.
- **Unnecessary rerun:** an irrelevant change reran verification.
- **Shadow pass/fail:** the real fixture result, recorded separately from the
  oracle.

The initial target result is 200/200 safe reuse opportunities taken, 300/300
relevant changes invalidated, zero unsafe reuse, and zero unnecessary reruns.
These are 500 controlled matrix cells, not 500 independent production projects.
