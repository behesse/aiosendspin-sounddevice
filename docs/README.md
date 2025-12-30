# Documentation

This directory contains the Sphinx documentation for aiosendspin-sounddevice.

## Building the Documentation

To build the HTML documentation locally:

```bash
# Install dependencies (if not already installed)
pip install -e ".[dev]"

# Build single version (for development)
cd docs
make html

# Build all versions (tags and branches)
cd docs
sphinx-multiversion source build/html
```

The generated HTML documentation will be in `docs/build/html/`. For multiversion builds, each version gets its own directory (e.g., `main/`, `v0.1.0/`, etc.).

**Note:** For local development, use `make html`. For building all versions (like in CI), use `sphinx-multiversion`.

## Development

The documentation source files are in `docs/source/`:
- `index.rst` - Main documentation index
- `api/index.rst` - API reference documentation
- `conf.py` - Sphinx configuration

The documentation is automatically generated from the module's docstrings using Sphinx's autodoc extension.

## Updating Documentation

To update the documentation:
1. Update docstrings in the source code
2. Rebuild the documentation: `cd docs && make html`
3. Review the generated HTML in `docs/build/html/`

