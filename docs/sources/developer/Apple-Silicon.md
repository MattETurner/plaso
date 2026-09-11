# Apple Silicon modernization

## Target and status

Target native macOS `arm64` across M-series Macs. ARM9 is not the build target;
individual M-series CPU and GPU capabilities vary. Detect optional acceleration
features at runtime rather than assuming one GPU family across all models.

This initial change establishes architecture checks and updates installation
guidance. It does **not** add GPU kernels, change parser behavior, or demonstrate
a performance improvement. Native execution and speed measurements require Apple
hardware; Linux tests of the audit logic cannot establish those results.

Baseline inspected: `00fcc6e7f95a002c85464f0dfd193396bd7d86d3`.

| Component | Observed implementation | Next useful work |
| --- | --- | --- |
| Packaging | `pyproject.toml`, Python >=3.10; many libyal bindings and pytsk3 | Validate native dependencies and retain build provenance |
| macOS CI | Already selects `macos-26` and Python 3.14 | Enforce arm64 Python/binaries and stop masking Homebrew failures |
| Extraction | `plaso/multi_process/extraction_engine.py`: CPU count minus one, clamped to 2–99 workers | Measure worker scaling against RAM pressure and merge throughput |
| Worker memory | `plaso/lib/definitions.py`: 2 GiB limit per worker | Measure whole-process-tree memory; per-worker limits are not a total budget |
| IPC/tasks | Processes, ZeroMQ queues and status RPC | Profile dispatch, task size and merge backlog |
| Storage | `plaso/storage/sqlite/sqlite_file.py`: acstore SQLite, JSON and zlib | Profile serialization, compression, transaction costs and merging |
| Instrumentation | Existing CPU, memory, storage and queue profilers | Establish reproducible baselines using existing instrumentation |

These are code-level candidates, not measured bottlenecks. Preserve the parser
API, CLI and storage compatibility through small, independently measured changes.

## Native validation

Follow the [macOS installation guide](../user/MacOS-Source-Release.md). The
dedicated tox environment runs architecture, dependency and existing unit-test
checks in the same Python environment:

```bash
python -m pip install tox
python -m tox -e macos-arm64
```

`macos-26` is currently an arm64 GitHub-hosted runner. Explicit checks protect
against a changed interpreter or mixed installation. The audit utility's
stdlib-only tests also run on Linux:

```bash
python -m unittest tests.utils.check_macos_native
```

Installation and the full suite still require successful native results. Run
the existing end-to-end suite on the target Mac as well:

```bash
python tests/end-to-end.py --debug -c config/end-to-end.ini --results-directory results-e2e
```

## Performance baseline

Use a fixed, hashed corpus covering EVTX, Registry, browser SQLite, text logs,
compressed input and disk images. Record Git commit, resolved dependencies,
macOS version, chip, RAM, power mode and input/output storage location. Compare
against the same native arm64 baseline; report Rosetta comparisons separately.
Keep parser selection, hashing, output format and compression constant.

Start with 1, 2 and 4 workers, then try higher counts while memory pressure and
throughput permit. Example using a small repository fixture from an activated
environment (each output directory must be new):

```bash
mkdir -p benchmark/w2/profile
/usr/bin/time -l log2timeline \
  --workers 2 \
  --profilers parsers,analyzers,processing,serializers,memory,storage,task_queue \
  --profiling-directory benchmark/w2/profile \
  --storage-file benchmark/w2/timeline.plaso \
  test_data/syslog.tgz \
  > benchmark/w2/stdout.log 2> benchmark/w2/stderr.log
```

This tiny fixture is a smoke test, not a throughput benchmark. Use representative
larger evidence for tuning. Repeat each worker setting at least three times;
retain samples and compare medians and variability. Separate warm-cache and
cold-cache observations. Run unprofiled timing trials too: profiling adds overhead.
Do not interpret `/usr/bin/time` peak RSS as a simultaneous total for the worker
tree; use the memory profiler and system memory-pressure/swap observations.

Record wall time, events/second, input bytes/second, event count, parser and
serialization time, storage traffic, merge backlog, worker restarts, parse errors,
aggregate memory and swap growth. Measure energy per completed run where possible
and state the measurement method.

CPU tuning comes first: benchmark workers and task batching, identify expensive
Python loops for selective native optimization, and assess JSON/zlib costs.
Preserve supported macOS multiprocessing behavior; do not force `fork` around
native libraries or a future Metal context to reduce startup time. Do not assume
performance-core-only execution is optimal: let macOS schedule workers and measure
policy changes before adoption.

## Metal candidates

Apple unified memory can remove explicit CPU-to-GPU copies for shared buffers.
It does not remove Python marshaling, batching, synchronization, kernel dispatch
or shared memory-bandwidth costs. Metal does not accelerate arbitrary Python
parser code simply by being enabled.

| Workload | Initial assessment | Prototype requirement |
| --- | --- | --- |
| EVTX/Registry/SQLite parsing, filesystem traversal, IPC, database writes | Poor initial GPU targets: branching, irregular access or I/O | Optimize measured CPU/I/O costs first |
| Large independent fixed-pattern byte scans | Plausible experiment | Preserve offsets, overlaps and chunk-boundary matches; compare with native CPU scanning |
| Hashing many independent buffers/files | Conditional experiment | Match existing algorithms and compare with optimized native CPU hashing; a single standard streaming digest cannot be arbitrarily split |
| Large numeric event aggregations | Possible downstream experiment | Preserve timestamp precision and deterministic ties; include materialization costs |
| General regex/YARA | Not a drop-in GPU replacement | Preserve full semantics; any deliberately limited GPU prefilter needs CPU verification |

Choose a profiler-confirmed fixed-pattern scanning hot path for the first GPU
experiment. Expose a small optional native backend, for example Objective-C++
with a Python binding. Retain CPU fallback, explicit opt-in and bounded batches.
Create the Metal device/queue in its owning process after startup; do not send
GPU objects through Python process queues. Start with one owner and measure
communication costs before introducing shared buffers or a broker.

Detect device capabilities at runtime. Compare CPU/GPU outputs for empty inputs,
binary bytes, overlapping patterns, chunk boundaries, large offsets and malformed
inputs. Keep small batches on CPU when dispatch costs dominate. Enable no GPU
path by default until it improves end-to-end throughput with equivalent results
and acceptable memory/energy use. Record hardware, batch threshold and crossover
point rather than promising a speedup.

## Forensic correctness

Compare semantic output rather than `.plaso` file hashes: metadata and insertion
order can differ between runs. Check timestamps at full precision, event types,
source paths/offsets, parser identities, values, tags and event multiplicity.
Normalize only documented nonsemantic run metadata. Preserve duplicates unless
the workflow explicitly requests deduplication. Compare errors/warnings and
retain upstream malformed/truncated-input coverage.

## Milestones

1. Native foundation (this change): architecture gate, strict CI and updated docs.
2. Reproducible dependency builds and a corpus baseline on a named target Mac.
3. One measured CPU/storage improvement per change, with semantic parity results.
4. One optional Metal prototype, shipped only if full-pipeline measurements justify it.

## References

* [Apple: Building a universal macOS binary](https://developer.apple.com/documentation/apple-silicon/building-a-universal-macos-binary)
* [Apple: Metal Compute on MacBook Pro](https://developer.apple.com/videos/play/tech-talks/10580/)
* [GitHub-hosted runner architectures](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
* [Python multiprocessing contexts and start methods](https://docs.python.org/3/library/multiprocessing.html#contexts-and-start-methods)
* [Existing Plaso profiling guide](Profiling.md)
