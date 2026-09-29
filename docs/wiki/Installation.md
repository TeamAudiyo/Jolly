# Installation

## PyPI command

Install Python 3.10 or later. Then run:

```bash
python -m pip install jolly-cli
jolly --version
jolly state --json
```

PyBullet can require a local C++ build when PyPI has no wheel for the current
Python and operating-system combination.

## Python development install

```bash
git clone https://github.com/TeamAudiyo/Jolly.git
cd Jolly
python -m venv .venv
. .venv/bin/activate
pip install -e '.[web,dev]'
pytest
```

## LLM skill install

```bash
npx skills add ./skills/jolly
```

## State directory

Jolly stores state in the operating system user-state directory. Set an
isolated directory for automation or tests:

```bash
export JOLLY_STATE_DIR=/tmp/jolly-state
```
