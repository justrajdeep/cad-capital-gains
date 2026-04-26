# Contributing
You are free to work on any bug fix or feature from the issues tab. If you intend to do so, please create a new issue if it doesn't yet exist, and assign yourself to the issue so that we know someone is actively working on it.

# Developing
Below is a small guide for getting your environment set up and running/testing the tool. We use [uv](https://docs.astral.sh/uv/) to manage dependencies.

## Getting started and getting the latest dependencies
```bash
uv sync
```

## Code Style
We follow PEP 8 style guidelines. You can automatically fix formatting issues using yapf:
```bash
# Fix formatting issues according to the style defined in pyproject.toml
uv run yapf --in-place --recursive --parallel -vv .
```

Then run flake8 to check for any remaining style issues:
```bash
uv run flake8 capgains tests
```

## Running tests manually
GitHub Actions runs the test suite, Python linting, and coverage on pushes and
pull requests (see `.github/workflows/`). Your code will need to pass these
checks to merge. You can run the same checks locally before you push:
```bash
# Run the test suite manually using your system's default python version:
uv run pytest --cov-report term --cov=capgains tests/

# Run the linter against the project's default python version
uv run flake8 capgains tests

# Linter only via tox (does not run the pytest matrix)
uv run tox -e flake8

# Run the test suite on each supported Python version, then flake8.
# You need those interpreters installed or you will get
# `InterpreterNotFoundError` (use `tox -e flake8` for lint only).
uv run tox
```

## Running the tool manually
```
uv run capgains ...
```

## Creating a release
Once you have all the changes you desire for a release, do the following. Note that
we follow [semantic versioning](https://semver.org/) for our projects.

1. Create a new branch
2. Bump up the release numbers in `pyproject.toml` and `capgains/__init__.py`
3. Push + create PR. Once PR is ready, merge it into the master branch.
4. Create a new release using the Github release tools. This will create a new tag and
kick off a CI build. The ensuing CI build will notice that this is a tagged commit and
will package the project and push it to PyPI.
