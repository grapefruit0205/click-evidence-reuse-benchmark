# Click evidence-reuse benchmark

An independent, deterministic benchmark for
[Click](https://github.com/grapefruit0205/click) cross-revision verification
evidence reuse.

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
workflow** to enter a target repository and branch, tag, or commit. The public
job runs the portability suite on Linux, macOS, and Windows and the complete
500-case matrix on Linux.

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
