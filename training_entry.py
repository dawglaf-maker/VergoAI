"""VergoAI-Training entry point.

Identical app to VergoAI, preset to training mode: instead of the normal
login/hub/select flow it opens the training picker (choose brawlers + games
per brawler) and runs the bot with the learning engine forced on.
"""
import sys

if "--training" not in sys.argv:
    sys.argv.append("--training")

import main  # noqa: F401  (module-level code runs the app)
