# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys
from pathlib import Path

# Add the project root to the path so autodoc can find the module
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'aiosendspin-sounddevice'
copyright = '2025, Benjamin Hesse'
author = 'Benjamin Hesse'

version = '0.1.0'
release = '0.1.0'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.intersphinx',
    'sphinx.ext.viewcode',
    'sphinx_multiversion',
]

templates_path = ['_templates']
exclude_patterns = []

language = 'en'

# -- Options for autodoc -----------------------------------------------------
autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
    'special-members': '__init__',
    'undoc-members': True,
    'exclude-members': '__weakref__',
}

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
# Create _static directory if it doesn't exist (for CI builds)
static_dir = Path(__file__).parent / '_static'
static_dir.mkdir(exist_ok=True)
html_static_path = ['_static'] if static_dir.exists() else []

# RTD theme version switcher configuration
# sphinx-multiversion will automatically inject 'versions' into html_context
html_context = {
    'display_version': True,
    'current_version': version,
    'version': version,
}

# Add version switcher to sidebar
html_sidebars = {
    '**': ['versions.html'],
}

# -- Options for intersphinx extension ---------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/intersphinx.html#configuration

intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    # Note: aiosendspin docs URL may not be available, so we skip it
    # 'aiosendspin': ('https://aiosendspin.readthedocs.io/', None),
}

# -- Options for sphinx-multiversion ------------------------------------------
# https://holzhaus.github.io/sphinx-multiversion/master/configuration.html

def _get_latest_patch_tags():
    """Get only the latest patch version for each minor version."""
    import subprocess
    from collections import defaultdict
    from packaging import version
    import re
    
    result = subprocess.run(['git', 'tag', '--list', 'v*'], capture_output=True, text=True, check=False)
    tags = [t.strip() for t in result.stdout.strip().split('\n') if t.strip()]
    
    if not tags:
        return r'^v\d+\.\d+.*$'
    
    # Group by major.minor, keep latest patch
    groups = defaultdict(list)
    for tag in tags:
        try:
            v = version.parse(tag.lstrip('v'))
            if isinstance(v, version.Version):
                groups[(v.major, v.minor)].append(tag)
        except version.InvalidVersion:
            continue
    
    latest = [max(group, key=lambda t: version.parse(t.lstrip('v'))) for group in groups.values()]
    return '^(' + '|'.join(re.escape(t) for t in latest) + ')$' if latest else r'^v\d+\.\d+.*$'

smv_tag_whitelist = _get_latest_patch_tags()
smv_branch_whitelist = r'^(main|master)$'
smv_remote_whitelist = r'^$'
smv_released_pattern = r'^refs/tags/v\d+\.\d+.*$'
smv_outputdir_format = '{ref.name}'

# Prefer local branches over remote refs to avoid conflicts
smv_prefer_remote_refs = False

# Show banner for unreleased versions
smv_show_banner = True
