"""
Settings package.

Default to local settings. Override with DJANGO_SETTINGS_MODULE:
  - core.settings.local
  - core.settings.production
"""

from .local import *  # noqa: F401, F403
