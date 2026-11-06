# SPDX-License-Identifier: AGPL-3.0-or-later
"""Logo et icône livrés avec l'application."""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PIL import Image  # noqa: E402

import theme  # noqa: E402


def test_icon_has_every_windows_size():
    tailles = Image.open(theme.ICONE_APPLICATION).info["sizes"]
    for cote in (16, 24, 32, 48, 256):
        assert (cote, cote) in tailles


def test_logo_is_square_and_transparent_around():
    image = Image.open(theme.chemin_ressource("logo.png"))
    assert image.size == (512, 512) and image.mode == "RGBA"
    assert image.getpixel((0, 0))[3] == 0  # coin hors du carré arrondi : transparent
