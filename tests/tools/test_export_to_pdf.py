#!/usr/bin/env python3.11
"""Tests de tools/export-to-pdf.py.

Ils lancent l'outil comme le ferait un utilisateur, puis relisent le texte du
PDF avec pdftotext et pdfinfo (paquet poppler-utils).

Lancement, depuis la racine du dépôt :

    python3.11 -m unittest discover -s tests/tools -v
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOOL = ROOT / "tools" / "export-to-pdf.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

MISSING = [name for name in ("pandoc", "pdftotext", "pdfinfo") if not shutil.which(name)]


def first_h1(path):
    """Titre H1 d'un fichier Markdown."""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


@unittest.skipIf(MISSING, f"outils absents : {', '.join(MISSING)}")
class ExportToPdfTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="test-export-to-pdf-")
        self.addCleanup(self._tmp.cleanup)
        self.pdf = Path(self._tmp.name) / "out.pdf"

    def export(self, *args):
        return subprocess.run([str(TOOL), *args, "--output", str(self.pdf)],
                              capture_output=True, text=True, timeout=180)

    def pdf_text(self):
        return subprocess.run(["pdftotext", "-layout", str(self.pdf), "-"],
                              capture_output=True, text=True, check=True).stdout

    def pdf_pages(self):
        info = subprocess.run(["pdfinfo", str(self.pdf)],
                              capture_output=True, text=True, check=True).stdout
        return int(next(line.split()[1] for line in info.splitlines() if line.startswith("Pages:")))

    def assert_exported(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.pdf.read_bytes()[:5], b"%PDF-")

    # ----- un seul document -------------------------------------------------

    def test_file_with_diagrams_and_formulas(self):
        result = self.export("--file", str(FIXTURES / "diagrams.md"))
        self.assert_exported(result)
        self.assertEqual(result.stderr, "")
        text = self.pdf_text()
        # Titres numérotés
        self.assertIn("1 Essai des schémas", text)
        self.assertIn("1.1 Mermaid", text)
        # Schémas Mermaid dessinés : leurs libellés sont dans la page, pas leur code source
        self.assertIn("PUT /transmissions/{id}", text)
        self.assertIn("Acquittée", text)
        self.assertNotIn("sequenceDiagram", text)
        self.assertNotIn("stateDiagram", text)
        self.assertNotIn("Syntax error", text)
        # Schéma drawio : le texte du schéma, pas le texte de repli du SVG
        self.assertIn("Bloc drawio", text)
        self.assertNotIn("Text is not SVG", text)
        # Formules converties : plus de code LaTeX
        self.assertNotIn("\\frac", text)
        self.assertNotIn("\\text", text)
        self.assertNotIn("$", text)
        # Lien vers un document absent du PDF : le texte reste
        self.assertIn("un autre document", text)
        # Pied de page
        self.assertRegex(text, r"1 ?/ ?2")

    def test_broken_mermaid_diagram_fails(self):
        result = self.export("--file", str(FIXTURES / "broken-diagram.md"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("schéma Mermaid n° 2", result.stderr)
        self.assertFalse(self.pdf.exists())

    def test_warnings(self):
        result = self.export("--file", str(FIXTURES / "missing-image.md"))
        self.assert_exported(result)
        self.assertIn("image introuvable: media/does-not-exist.svg", result.stderr)
        self.assertIn("2 titre(s) H1", result.stderr)

    def test_missing_file(self):
        result = self.export("--file", str(FIXTURES / "does-not-exist.md"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("introuvable", result.stderr)
        self.assertFalse(self.pdf.exists())

    def test_mode_is_required(self):
        result = self.export()
        self.assertEqual(result.returncode, 2)

    # ----- document global --------------------------------------------------

    def test_global_document(self):
        result = self.export("--global")
        self.assert_exported(result)
        text = self.pdf_text()
        self.assertIn("Table des matières", text)
        documents = [ROOT / "README.md", *sorted((ROOT / "README.d").glob("*.md"))]
        self.assertGreaterEqual(self.pdf_pages(), len(documents))
        # Chaque document forme une section numérotée, README.md en premier
        self.assertIn(f"1 {first_h1(ROOT / 'README.md')}", text)
        for document in documents:
            self.assertIn(first_h1(document), text, document.name)
        # Aucun document oublié dans README.md
        self.assertNotIn("n'est pas référencé", result.stderr)
        # Aucun lien ne pointe encore vers un fichier Markdown
        links = subprocess.run(["pdftohtml", "-q", "-i", "-noframes", "-stdout", str(self.pdf)],
                               capture_output=True, text=True).stdout
        self.assertNotIn('.md"', links)


if __name__ == "__main__":
    unittest.main()
