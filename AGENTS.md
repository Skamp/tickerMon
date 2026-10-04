
## Project Overview
tickerMon is a PySide6 desktop application for monitoring stock tickers with local SQLite caching, PyQtGraph charts, and Yahoo Finance (yfinance) as the data source.

## Tech Stack (from requirements.txt)
- **Python**: 3.12+
- **PySide6 >= 6.6.0** - Qt6 GUI framework
- **pyqtgraph >= 0.13.3** - Interactive financial charts and plotting
- **yfinance >= 0.2.36** - Yahoo Finance market data API
- **pandas >= 2.1.0** - Data manipulation and time-series processing
- **pytest >= 7.4.0** - Unit testing framework

## Environment Setup
Create and activate a virtual environment, then install dependencies:

```bash
python -m venv .venv
source activate.sh  # or source .venv/bin/activate (Linux/WSL)
pip install -r requirements.txt
```
## Running the Application
With the virtual environment activated:

```bash
python main.py
```

##Testing
The project uses pytest (installed via requirements). Run tests with:

```bash
pytest -v
```

You can also run with unittest (as documented in README):

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## Project Conventions
- Follow PEP 8 style guidelines with 4-space indentation.
- Preserve the existing layered architecture: UI (app/ui/) → Services (app/services/) → Repositories/Database (app/database/) → External APIs.
- Mimic existing code style, naming conventions, and patterns when making changes.
- Add no comments unless explicitly requested by the user.
- Never introduce code that logs or exposes secrets/keys.
- Check existing utilities/libraries before adding new dependencies.
- Keep changes minimal and focused on the task at hand.

## Development Guidelines
- Read relevant files first to understand context before editing.
- Prefer editing existing files over creating new ones unless necessary.
- After completing changes, run tests to verify correctness when possible.
- Do not commit changes unless explicitly requested by the user.

The file captures the dependencies, setup, run/test commands, and agent-friendly conventions based on the codebase.