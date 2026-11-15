#!/usr/bin/env python3.11
"""Exporte la documentation Markdown en PDF.

Chaîne : Markdown --(Pandoc)--> HTML --(Chromium sans affichage)--> PDF.

* Les formules LaTeX sont converties en MathML par Pandoc.
* Les schémas Mermaid sont dessinés par Chromium avec tools/vendor/mermaid.min.js.
* Les schémas *.drawio.svg sont des images SVG, affichées telles quelles par Chromium.

Seule la bibliothèque standard de Python est utilisée.
Voir README.d/build.md pour les prérequis et l'utilisation.
"""

import argparse
import base64
import fcntl
import html
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
MERMAID_JS = Path(__file__).resolve().parent / "vendor" / "mermaid.min.js"
MARKDOWN_FORMAT = "gfm+tex_math_dollars"  # même dialecte que GitHub et VS Code
CHROMIUM_NAMES = ("chromium-browser", "chromium", "google-chrome")
TIMEOUT_S = 120

# Format A4, en pouces pour Chromium
PAPER = {"paperWidth": 8.27, "paperHeight": 11.69,
         "marginTop": 0.8, "marginBottom": 0.8, "marginLeft": 0.8, "marginRight": 0.8}

FOOTER = ('<div style="font-size:8pt; width:100%; text-align:center;">'
          '<span class="pageNumber"></span> / <span class="totalPages"></span></div>')

CSS = """
body { font-family: "DejaVu Sans", "Liberation Sans", Arial, sans-serif;
       font-size: 10.5pt; line-height: 1.4; max-width: none; margin: 0; padding: 0; }
h1, h2, h3, h4 { break-after: avoid; }
h1 { font-size: 20pt; border-bottom: 1px solid #888; padding-bottom: 4pt; }
h2 { font-size: 15pt; }
h3 { font-size: 12pt; }
body.global > h1 { break-before: page; }
nav#TOC ul { list-style: none; padding-left: 1.2em; }
nav#TOC a { color: inherit; text-decoration: none; }
table { border-collapse: collapse; margin: 1em 0; font-size: 9.5pt; }
th, td { border: 1px solid #999; padding: 3pt 6pt; vertical-align: top; }
th { background: #eee; }
tr { break-inside: avoid; }
code { font-family: "DejaVu Sans Mono", "Liberation Mono", monospace; font-size: 9pt; }
td code { overflow-wrap: anywhere; }
pre { background: #f5f5f5; border: 1px solid #ddd; padding: 6pt;
      white-space: pre-wrap; overflow-wrap: anywhere; }
pre.mermaid { background: none; border: none; text-align: center; break-inside: avoid; }
img, svg { max-width: 100%; height: auto; }
figure { margin: 1em 0; text-align: center; break-inside: avoid; }
"""

# Promesse attendue avant l'impression : schémas dessinés et polices chargées.
READY_SCRIPT = """
window.__docReady = new Promise((resolve, reject) => {
  window.addEventListener('load', async () => {
    try {
      if (window.mermaid) {
        mermaid.initialize({ startOnLoad: false, theme: 'neutral' });
        await mermaid.run();
      }
      await document.fonts.ready;
      resolve('ok');
    } catch (e) {
      reject(e instanceof Error ? e : new Error(String(e)));
    }
  });
});
"""


class ExportError(Exception):
    """Erreur expliquée à l'utilisateur, sans trace d'appel."""


def warn(message):
    print(f"attention: {message}", file=sys.stderr)


# --------------------------------------------------------------------------
# Pandoc
# --------------------------------------------------------------------------

def run_pandoc(args, stdin=None):
    try:
        result = subprocess.run(["pandoc", *args], input=stdin, capture_output=True, text=True)
    except FileNotFoundError:
        raise ExportError("pandoc est introuvable (voir README.d/build.md).")
    if result.returncode != 0:
        raise ExportError(f"pandoc a échoué :\n{result.stderr.strip()}")
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    return result.stdout


def walk(node, fn):
    """Parcourt l'arbre Pandoc et applique fn à chaque élément {"t": ...}.

    fn renvoie None (élément conservé, ses enfants sont parcourus), un élément
    ou une liste d'éléments de remplacement (non parcourus).
    """
    if isinstance(node, list):
        out = []
        for item in node:
            if isinstance(item, dict) and "t" in item:
                replacement = fn(item)
                if replacement is None:
                    if "c" in item:
                        item["c"] = walk(item["c"], fn)
                    out.append(item)
                elif isinstance(replacement, list):
                    out.extend(replacement)
                else:
                    out.append(replacement)
            else:
                out.append(walk(item, fn))
        return out
    if isinstance(node, dict):
        if "t" in node:
            if "c" in node:
                node["c"] = walk(node["c"], fn)
            return node
        return {key: walk(value, fn) for key, value in node.items()}
    return node


def plain_text(inlines):
    """Texte brut d'une liste d'éléments en ligne."""
    parts = []

    def collect(element):
        if element["t"] in ("Str", "Code", "Math"):
            content = element["c"]
            parts.append(content if isinstance(content, str) else content[-1])
        elif element["t"] in ("Space", "SoftBreak", "LineBreak"):
            parts.append(" ")

    walk(inlines, collect)
    return "".join(parts)


def is_external(url):
    parts = urlsplit(url)
    return bool(parts.scheme) or url.startswith("//")


def resolve_target(source, url):
    """Chemin absolu désigné par un lien relatif, et son ancre éventuelle."""
    parts = urlsplit(url)
    return (source.parent / unquote(parts.path)).resolve(), unquote(parts.fragment)


class Document:
    """Un fichier Markdown chargé sous forme d'arbre Pandoc."""

    def __init__(self, path):
        self.path = path
        self.slug = path.stem.lower()
        self.name = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        self.ast = json.loads(run_pandoc(["-f", MARKDOWN_FORMAT, "-t", "json", str(path)]))
        self.title = None   # éléments en ligne du premier H1
        self.anchor = None  # identifiant du premier H1
        self.has_mermaid = False
        self._prefix_headers()

    def _prefix_headers(self):
        """Préfixe les identifiants des titres pour les rendre uniques dans le document global."""
        h1_count = 0

        def visit(element):
            nonlocal h1_count
            if element["t"] != "Header":
                return None
            level, attr, inlines = element["c"]
            if attr[0]:
                attr[0] = f"{self.slug}--{attr[0]}"
            if level == 1:
                h1_count += 1
                if self.title is None:
                    self.title, self.anchor = inlines, attr[0]
            return None

        self.ast["blocks"] = walk(self.ast["blocks"], visit)
        if h1_count != 1:
            warn(f"{self.name}: {h1_count} titre(s) H1, un seul attendu.")

    def linked_documents(self):
        """Fichiers Markdown existants référencés par ce document, dans l'ordre d'apparition."""
        found = []

        def visit(element):
            if element["t"] == "Link" and not is_external(element["c"][2][0]):
                target, _ = resolve_target(self.path, element["c"][2][0])
                if target.suffix == ".md" and target.is_file() and target not in found:
                    found.append(target)
            return None

        walk(self.ast["blocks"], visit)
        return found

    def rewrite(self, documents):
        """Adapte liens, images et schémas ; documents = {chemin: Document} du PDF produit."""

        def visit(element):
            kind = element["t"]
            if kind == "CodeBlock" and "mermaid" in element["c"][0][1]:
                self.has_mermaid = True
                code = html.escape(element["c"][1])
                return {"t": "RawBlock", "c": ["html", f'<pre class="mermaid">{code}</pre>']}
            if kind == "Image":
                url = element["c"][2][0]
                if not is_external(url):
                    target, _ = resolve_target(self.path, url)
                    if not target.is_file():
                        warn(f"{self.name}: image introuvable: {url}")
                    element["c"][2][0] = target.as_uri()
                return None
            if kind == "Link":
                return self._rewrite_link(element, documents)
            return None

        self.ast["blocks"] = walk(self.ast["blocks"], visit)

    def _rewrite_link(self, element, documents):
        _, inlines, target_spec = element["c"]
        url = target_spec[0]
        if is_external(url):
            return None
        target, fragment = resolve_target(self.path, url)
        if not urlsplit(url).path:  # ancre dans le même document
            target_spec[0] = f"#{self.slug}--{fragment}"
            return None
        document = documents.get(target)
        if document is None:
            # Document absent du PDF : le lien ne mènerait nulle part, on garde le texte.
            if len(documents) > 1 and target.suffix == ".md":
                warn(f"{self.name}: lien vers {url}, qui n'est pas référencé dans README.md.")
            return inlines
        if fragment:
            target_spec[0] = f"#{document.slug}--{fragment}"
        else:
            # Lien vers un document : remplacé par le nom de sa section, cliquable.
            target_spec[0] = f"#{document.anchor or ''}"
            if document is not self and document.title:
                element["c"][1] = json.loads(json.dumps(document.title))
        return None


def build_html(documents, title, is_global, workdir):
    """Assemble les documents et renvoie le chemin du fichier HTML produit."""
    by_path = {document.path: document for document in documents}
    for document in documents:
        document.rewrite(by_path)

    head = [f"<style>{CSS}</style>"]
    if any(document.has_mermaid for document in documents):
        if not MERMAID_JS.is_file():
            raise ExportError(f"{MERMAID_JS} est introuvable (voir README.d/build.md).")
        head.append(f'<script src="{MERMAID_JS.as_uri()}"></script>')
    head.append(f"<script>{READY_SCRIPT}</script>")
    head_file = workdir / "head.html"
    head_file.write_text("\n".join(head), encoding="utf-8")

    merged = dict(documents[0].ast)
    merged["meta"] = {}
    merged["blocks"] = [block for document in documents for block in document.ast["blocks"]]

    html_file = workdir / "document.html"
    args = ["-f", "json", "-t", "html5", "--standalone", "--mathml", "--number-sections",
            "--metadata", f"pagetitle={title}", "--metadata", "lang=fr",
            "--include-in-header", str(head_file), "-o", str(html_file)]
    if is_global:
        args += ["--toc", "--toc-depth=2", "--metadata", "toc-title=Table des matières"]
    run_pandoc(args, stdin=json.dumps(merged))
    if is_global:
        # Classe utilisée par la feuille de style pour le saut de page avant chaque document.
        text = html_file.read_text(encoding="utf-8")
        html_file.write_text(text.replace("<body>", '<body class="global">', 1), encoding="utf-8")
    return html_file


# --------------------------------------------------------------------------
# Chromium, piloté par le protocole DevTools sur un tube (--remote-debugging-pipe)
# --------------------------------------------------------------------------

def find_chromium():
    candidates = [os.environ.get("CHROMIUM"), *CHROMIUM_NAMES]
    for candidate in candidates:
        if candidate and shutil.which(candidate):
            return shutil.which(candidate)
    raise ExportError("Chromium est introuvable (voir README.d/build.md) ; "
                      "son chemin peut être donné par la variable CHROMIUM.")


class Browser:
    def __init__(self, workdir):
        self.log = workdir / "chromium.log"
        self.buffer = b""
        self.events = []
        self.next_id = 0
        # Chromium lit ses commandes sur le descripteur 3 et répond sur le 4.
        command_r, self.command_w = os.pipe()
        self.reply_r, reply_w = os.pipe()
        child_r = fcntl.fcntl(command_r, fcntl.F_DUPFD, 10)
        child_w = fcntl.fcntl(reply_w, fcntl.F_DUPFD, 10)
        os.close(command_r)
        os.close(reply_w)
        args = [find_chromium(), "--headless", "--remote-debugging-pipe", "--disable-gpu",
                "--no-first-run", f"--user-data-dir={workdir / 'profile'}", "about:blank"]
        with open(self.log, "wb") as log:
            self.process = subprocess.Popen(
                ["/bin/sh", "-c", f'exec "$@" 3<&{child_r} 4>&{child_w}', "sh", *args],
                pass_fds=(child_r, child_w), stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        os.close(child_r)
        os.close(child_w)
        self.deadline = time.monotonic() + TIMEOUT_S

    def _fail(self, message):
        tail = ""
        if self.log.is_file():
            tail = "\n".join(self.log.read_text(errors="replace").splitlines()[-15:])
        raise ExportError(f"{message}\n{tail}".rstrip())

    def _read_message(self):
        while b"\0" not in self.buffer:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.reply_r], [], [], remaining)[0]:
                self._fail(f"Chromium ne répond pas après {TIMEOUT_S} s.")
            chunk = os.read(self.reply_r, 1 << 20)
            if not chunk:
                self._fail("Chromium s'est arrêté de façon inattendue.")
            self.buffer += chunk
        raw, self.buffer = self.buffer.split(b"\0", 1)
        return json.loads(raw)

    def call(self, method, params=None, session=None):
        self.next_id += 1
        message = {"id": self.next_id, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        os.write(self.command_w, json.dumps(message).encode() + b"\0")
        while True:
            reply = self._read_message()
            if reply.get("id") == self.next_id:
                if "error" in reply:
                    self._fail(f"Chromium, {method} : {reply['error'].get('message')}")
                return reply.get("result", {})
            self.events.append(reply)

    def wait_event(self, name):
        while True:
            for event in self.events:
                if event.get("method") == name:
                    self.events.remove(event)
                    return event
            self.events.append(self._read_message())

    def print_to_pdf(self, html_file, pdf_file):
        target = self.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = self.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        self.call("Page.enable", session=session)
        navigation = self.call("Page.navigate", {"url": html_file.as_uri()}, session)
        if navigation.get("errorText"):
            self._fail(f"Chromium ne peut pas ouvrir {html_file} : {navigation['errorText']}")
        self.wait_event("Page.loadEventFired")
        ready = self.call("Runtime.evaluate",
                          {"expression": "window.__docReady", "awaitPromise": True}, session)
        if "exceptionDetails" in ready:
            details = ready["exceptionDetails"]
            reason = details.get("exception", {}).get("description") or details.get("text")
            raise ExportError(f"Erreur dans un schéma Mermaid ou dans la page :\n{reason}")
        pdf = self.call("Page.printToPDF", {
            **PAPER, "printBackground": True, "displayHeaderFooter": True,
            "headerTemplate": "<span></span>", "footerTemplate": FOOTER}, session)
        pdf_file.write_bytes(base64.b64decode(pdf["data"]))

    def close(self):
        try:
            if self.process.poll() is None:
                self.next_id += 1
                os.write(self.command_w, json.dumps({"id": self.next_id, "method": "Browser.close"}).encode() + b"\0")
                self.process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
        finally:
            os.close(self.command_w)
            os.close(self.reply_r)


# --------------------------------------------------------------------------
# Programme principal
# --------------------------------------------------------------------------

def collect_global():
    """README.md suivi des documents qu'il référence, dans l'ordre des liens."""
    readme = Document(README)
    paths = [path for path in readme.linked_documents() if path != README]
    for path in sorted((ROOT / "README.d").glob("*.md")):
        if path not in paths:
            warn(f"{path.relative_to(ROOT)} n'est pas référencé dans README.md : absent du PDF.")
    return [readme] + [Document(path) for path in paths]


def main():
    parser = argparse.ArgumentParser(description="Exporte la documentation Markdown en PDF.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--global", dest="is_global", action="store_true",
                      help="un seul PDF : README.md suivi des documents qu'il référence")
    mode.add_argument("--file", type=Path, metavar="FICHIER.md", help="un seul document")
    parser.add_argument("--output", type=Path, metavar="FICHIER.pdf",
                        help="fichier produit (par défaut dans build/doc/)")
    parser.add_argument("--keep-html", action="store_true",
                        help="conserve le fichier HTML intermédiaire à côté du PDF")
    args = parser.parse_args()

    try:
        if args.is_global:
            documents = collect_global()
            default_name = ROOT.name
        else:
            path = args.file.resolve()
            if not path.is_file():
                raise ExportError(f"{args.file} est introuvable.")
            documents = [Document(path)]
            default_name = path.stem
        title = plain_text(documents[0].title) if documents[0].title else default_name
        output = (args.output or ROOT / "build" / "doc" / f"{default_name}.pdf").resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="export-to-pdf-") as tmp:
            workdir = Path(tmp)
            html_file = build_html(documents, title, args.is_global, workdir)
            if args.keep_html:
                shutil.copyfile(html_file, output.with_suffix(".html"))
            browser = Browser(workdir)
            try:
                browser.print_to_pdf(html_file, output)
            finally:
                browser.close()
    except ExportError as error:
        print(f"erreur: {error}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
