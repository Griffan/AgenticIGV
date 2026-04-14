<!-- generated-by: gsd-doc-writer -->
# Contributing to Agentic IGV

Thank you for your interest in contributing to Agentic IGV! This guide covers setup, development workflow, coding standards, and how to submit issues or pull requests.

## Development Setup

1. **Clone the repository:**
   ```bash
   git clone <repo-url>
   cd AgenticIGV
   ```
2. **Create a virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
4. **(Optional) Add environment variables:**
   - For LLM-powered features, set `OPENAI_API_KEY` and other relevant variables in a `.env` file at the project root.
   - The app can run without these for basic functionality.

5. **Run the development server:**
   ```bash
   uvicorn app.main:app --reload
   ```
   Visit [http://localhost:8000](http://localhost:8000) to access the UI.

## Coding Standards

- **Python 3.10+** is required.
- Follow PEP8 for Python code style.
- Organize new code under the `app/` directory by logical component (e.g., `agents/`, `services/`, `ui/`).
- Add docstrings to all public functions and classes.
- Use descriptive commit messages.
- Write tests for new features or bug fixes in the `tests/` directory using `pytest`.

## Testing

- Run all tests with:
  ```bash
  pytest
  ```
- Test files are located in `tests/` and use the `test_*.py` naming convention.
- Manual browser verification for Edge mode is described in `docs/EDGE_MODE_QA.md`.

## Pull Request Guidelines

- Fork the repository and create a feature branch (`feature/your-feature` or `fix/your-bug`).
- Ensure your branch is up to date with `main` before submitting a PR.
- Include a clear description of your changes and reference related issues if applicable.
- Pass all tests before requesting review.
- PRs should focus on a single feature or fix.
- If your PR adds or changes user-facing behavior, update the relevant documentation.

## Issue Reporting

- Use GitHub Issues to report bugs or request features.
- Include steps to reproduce, expected and actual behavior, and your environment (OS, Python version).
- For feature requests, describe the motivation and potential use case.

<!-- No CODE_OF_CONDUCT.md found. If one is added, link it here. -->

See `GETTING-STARTED.md` for prerequisites and first-run instructions, and `DEVELOPMENT.md` for local development setup.
