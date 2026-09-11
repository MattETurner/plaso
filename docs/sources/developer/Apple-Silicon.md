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

## First benchmark target: M4 MacBook Air, 24 GB

User-reported target: **M4 MacBook Air, 24 GB unified memory, macOS 26.6.2
(25G83)**. Record the actual OS/build with `sw_vers` in each benchmark; this is a
target configuration, not a tested compatibility claim. Screen size, GPU core
count and SSD configuration have not been specified. Discover GPU capabilities
on the device before selecting a Metal workload.

Apple lists the M4 Air CPU as 10 cores (4 performance, 6 efficiency). Four worker
processes do not imply affinity to the four performance cores: macOS schedules
them. [Apple specifications](https://support.apple.com/en-us/122209).

| Setting | Initial experiment |
| --- | --- |
| Starting worker count | Explicit `--workers 4`; a hypothesis, not a new default |
| Worker sweep | 1, 2, 4 and 6 workers; compare against automatic selection later |
| Per-worker memory limit | Keep the existing 2 GiB limit (`2147483648` bytes) |
| Whole-machine memory | Observe aggregate process memory, Memory Pressure and swap growth; reduce workers if pressure rises |
| Power/thermal conditions | Keep power source and Low Power Mode consistent; compare repeated, sustained runs |
| GPU | CPU baseline first; no Metal backend exists in this branch |

At four workers, the sum of the per-worker limits is 8 GiB; at six it is 12 GiB.
Those are neither reservations nor a hard total cap: monitoring is periodic and
the main process, libraries, filesystem cache, macOS and other applications need
memory too. Avoid starting with the automatic nine-worker selection on this
10-core CPU before measuring its effect on the 24 GB machine.

The benchmark below runs **12 complete extractions** and keeps all outputs.
First use the tiny fixture to verify the procedure. For performance measurements,
replace it with a representative, fixed evidence file and ensure sufficient free
disk space. Run from the repository root in the validated native environment.
This block is intended for `bash` and creates a new output directory each time.

```bash
set -eu
plaso_source="$PWD/test_data/syslog.tgz"
test -f "$plaso_source"
plaso_results=$(mktemp -d "$PWD/benchmark-m4.XXXXXX")
sw_vers > "$plaso_results/macos.txt"
sysctl machdep.cpu.brand_string hw.memsize hw.ncpu > "$plaso_results/hardware.txt"
pmset -g custom > "$plaso_results/power-settings.txt"
git rev-parse HEAD > "$plaso_results/commit.txt"
git status --short > "$plaso_results/worktree.txt"
python -m pip freeze > "$plaso_results/dependencies.txt"
python utils/check_macos_native.py > "$plaso_results/architecture.json"
python utils/check_dependencies.py > "$plaso_results/dependency-check.txt"
shasum -a 256 "$plaso_source" > "$plaso_results/source.sha256"

plaso_repeat=0
for plaso_order in "2 4 6 1" "4 6 1 2" "6 1 2 4"; do
  plaso_repeat=$((plaso_repeat + 1))
  for plaso_workers in $plaso_order; do
    plaso_run="$plaso_results/r${plaso_repeat}-w${plaso_workers}"
    mkdir "$plaso_run"
    sysctl vm.swapusage > "$plaso_run/swap-before.txt"
    if /usr/bin/time -l python -m plaso.scripts.log2timeline \
      --workers "$plaso_workers" \
      --worker-memory-limit 2147483648 \
      --storage-file "$plaso_run/timeline.plaso" "$plaso_source" \
      > "$plaso_run/stdout.log" 2> "$plaso_run/time-and-stderr.log"; then
      printf '0\n' > "$plaso_run/exit-status.txt"
    else
      plaso_status=$?
      printf '%s\n' "$plaso_status" > "$plaso_run/exit-status.txt"
      printf 'Extraction failed; inspect %s\n' "$plaso_run" >&2
      exit "$plaso_status"
    fi
    sysctl vm.swapusage > "$plaso_run/swap-after.txt"
  done
done
printf 'Results: %s\n' "$plaso_results"
```

The sweep is unprofiled to reduce measurement overhead and rotates order to
reduce order bias; it does not eliminate thermal or cache effects. Source hashing
also warms the cache. Label these as cache-uncontrolled runs, not cold-cache
measurements. Record background activity and Memory Pressure during each run;
before/after swap snapshots do not reveal peak memory or prove that no swapping
occurred. Repeat the most promising setting with the profilers below to identify
hot paths. Check semantic output parity before treating a faster run as a win.

Native CI validates the runner's configuration, not this particular M4/macOS
build. The first user-reported on-device baseline is recorded below.

## First E01 baseline: four workers

User-reported result on the M4 Air / 24 GB target, using
`base-wkstn-01-c-drive.E01` from SRL-2018. This is one unprofiled run, not a
speedup comparison. The CLI reported version `20260720`. The user was instructed
to apply the RSS fallback from commit `d412f3a`; nonzero memory readings confirm
the expected behavior, but the exact checkout, dependency manifest and source
hash were not supplied with these results.

| Measurement | Reported value |
| --- | --- |
| Workers / configured per-worker limit | 4 / 2 GiB |
| Plaso processing time | 01:04:34 (3,874 seconds) |
| External wall time | 3,910.62 seconds (01:05:10.62) |
| User / system CPU time | 15,782.48 / 1,951.18 seconds |
| Tasks / main source count | 906,629 / 906,629 |
| Main event-data count | 9,159,738 |
| Queued / processing / merging / abandoned at completion | 0 / 0 / 0 / 0 |
| Extraction warnings | 10,889; contents not yet reviewed |
| Final main RSS | 620.8 MiB |
| Final worker RSS | 459.8, 464.9, 575.2, 508.9 MiB |
| External time maximum resident set size | 1,170,620,416 bytes (~1.09 GiB) |
| External time peak memory footprint | 748,733,496 bytes |
| External time page faults / swaps | 233 / 0 |

Derived rates: approximately 2,342 **event-data records** per wall-clock second,
and 4.53 CPU-seconds per wall-clock second. Event-data records are not identical
to timestamped event counts. CPU time does not establish an equivalent fraction
of the chip's maximum performance, since core capabilities and workload vary.

The final displayed RSS values sum to 2,629.6 MiB (~2.57 GiB), including possible
shared-page double counting. Final RSS is not peak aggregate RSS. The external
time maximum RSS is also not a simultaneous total of all five processes, and
its zero swaps field does not prove absence of system-wide swapping. An earlier
screenshot showed 8.54 GB of system swap in use; attribution and growth during
the run were not measured.

The output explicitly shows both VSS1 and VSS2 paths. Keep the same snapshot,
parser and hashing scope in every comparison. Omitting snapshots would change
evidence coverage and cannot be reported as an equivalent-workload speedup.

Successful completion and no abandoned tasks establish that this run finished;
they do not explain the 10,889 extraction warnings or prove complete parsing.
First inspect the default pinfo summary, which prints warning counts without
listing every warning message. In the same shell used for the baseline:

```bash
python -m plaso.scripts.pinfo "$plaso_run/timeline.plaso" \
  > "$plaso_run/summary.txt"
```

Review the warning counts by parser and the affected paths, then sample messages
from the dominant warning categories. Avoid `--sections warnings` for the initial
summary because it requests every warning's details. Preserve the baseline store
for semantic comparisons. Next, use a separate profiling run with four workers
to distinguish parsing, serialization, storage and merging costs before choosing
a code optimization or a higher worker count. Profiling timings must be labeled
separately because instrumentation adds overhead.

## Memory accounting and the smoke-test warning

The bundled `test_data/syslog.tgz` contains a malformed month (`MMM`), which
explains the `Invalid month: None` extraction warning in the reported smoke run.
That run completed with 13 event-data records and no abandoned tasks.

The separate CLI warning about failing to set `4294967296` bytes concerns the
default 4 GiB `RLIMIT_DATA` limit. It means that limit was not installed; it does
not mean the process used 4 GiB or ran out of RAM. This change leaves that warning
visible and does not claim to implement a macOS hard allocation limit.

The process-memory monitor previously summed `data` and `shared`, defaulting
missing fields to zero. macOS psutil reports RSS but not those fields, so this
could display `0 B` and prevent the periodic worker memory-limit check from
triggering. The monitor now uses RSS when either field is absent and preserves
data-plus-shared accounting where both exist. See
[psutil memory_info](https://psutil.io/api/#psutil.Process.memory_info).

RSS measures resident pages, not a total allocation cap or Apple's complete
physical-footprint metric. Shared pages can be counted in multiple processes.
The 2 GiB per-worker check remains periodic; it can overshoot between samples,
and does not cap the main process or combined CPU/GPU memory. This fix requires
on-device validation before using memory measurements for tuning.

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
