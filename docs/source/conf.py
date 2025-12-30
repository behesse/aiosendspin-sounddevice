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
html_static_path = ['_static']

# -- Options for intersphinx extension ---------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/intersphinx.html#configuration

intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'aiosendspin': ('https://aiosendspin.readthedocs.io/', None),
}

# -- Options for sphinx-multiversion ------------------------------------------
# https://holzhaus.github.io/sphinx-multiversion/master/configuration.html

# Whitelist pattern for tags (matched against git tag)
# Match tags like v0.1.0, v1.0.0, etc.
smv_tag_whitelist = r'^v\d+\.\d+.*$'

# Whitelist pattern for branches (matched against git branch)
# Only main/master branches
smv_branch_whitelist = r'^(main|master)$'

# Whitelist pattern for remotes (matched against git remote)
smv_remote_whitelist = r'^origin$'

# Pattern for released versions (tags that are considered releases)
smv_released_pattern = r'^refs/tags/v\d+\.\d+.*$'

# Output directory format - each version gets its own directory
smv_outputdir_format = '{ref.name}'
