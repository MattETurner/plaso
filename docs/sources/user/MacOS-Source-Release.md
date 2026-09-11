# Native macOS source installation

Use an isolated Python environment. This fork targets native Apple Silicon
(`arm64`) first. These are development installation instructions; successful
native dependency checks and tests must establish compatibility. Not every
required library necessarily has a prebuilt macOS wheel.

## Prerequisites

Install Xcode Command Line Tools:

```bash
xcode-select --install
```

Use a native installation of [Homebrew](https://docs.brew.sh/Installation).
Its standard Apple Silicon prefix is `/opt/homebrew`; `/usr/local` is the
standard Intel prefix. Run the terminal without Rosetta, then install tools
and the Python version selected by this fork's macOS CI:

```bash
brew install python@3.14 gettext gnu-sed pkg-config
python3.14 -c 'import platform, sys; print(sys.executable, platform.machine()); assert platform.machine() == "arm64"'
```

If Python is Intel-only, correct PATH or the Python installation first. Create
a new virtual environment rather than reusing compiled Intel dependencies.

## Install the checkout

Clone the fork and select the branch or release you intend to use. From its root:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install --pre -e .
python utils/check_macos_native.py
python utils/check_dependencies.py
python run_tests.py
```

Dependencies come from `pyproject.toml`. `--pre` matches this repository's
existing development tox configuration. For reproducible casework, validate a
specific checkout and retain resolved versions and wheel files. Building libyal
bindings and pytsk3 can take considerable time when compatible wheels are
unavailable. Diagnose dependency installation failures before proceeding.

Installed commands are `log2timeline`, `psort`, `pinfo`, `psteal`, and
`image_export`, without a `.py` suffix. For example:

```bash
log2timeline --help
python -m pip freeze > installed-dependencies.txt
```

Run `deactivate` to leave the environment; activate it again before using Plaso.
The project supports Python >=3.10; the dedicated native CI environment selects
3.14. Other combinations require validation.

## Architecture audit scope

`check_macos_native.py` fails outside native macOS arm64 Python. It checks the
interpreter, `.so` extensions and bundled `.dylib` files in the active installation's
package directories and standard-library extension directory. Universal2 binaries
pass when they contain an arm64 slice; inspection errors fail the audit. Use a
dedicated environment because unrelated installed packages are also checked.

This is an architecture inventory, not a complete dynamic-loader audit. It does
not follow directory symlinks, editable packages outside those directories, or
transitive libraries outside the environment. Dependency imports and parser tests
remain necessary. Inspect linkage errors with `otool -L` on the affected extension
and `lipo -archs` on the referenced libraries.

## Source-build troubleshooting

Check `xcode-select -p` and `xcrun --show-sdk-path` for an available SDK. When a
specific dependency needs an external library, install it natively and derive
paths using `brew --prefix <formula>` instead of copying Intel include/library
paths. Avoid global `-mcpu=native` flags for distributable wheels: they can narrow
hardware compatibility. Retain the first failing package's build log.

See the [Apple Silicon development plan](../developer/Apple-Silicon.md) for
profiling, correctness validation and proposed Metal work.
