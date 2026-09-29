# Installation

## npm global command

Install Node.js 18 or later and Python 3.10 or later. Then run:

```bash
npm install -g jolly-cli
jolly --version
jolly state --json
```

The npm package installs a private Python runtime for PyBullet. The first
command performs setup when the npm client skips install scripts. This setup can
take several minutes when PyBullet needs a local C++ build.

Set `JOLLY_PYTHON` to select a specific Python executable.

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
