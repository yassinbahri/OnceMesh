"""Deterministic readable-v1 HTML-to-Markdown evaluation adapter."""

from __future__ import annotations

from html.parser import HTMLParser
import re

from ..canonical import digest_bytes


def build_html_to_markdown_action(html: bytes, *, media_type: str = "text/html") -> dict:
    return {
        "spec_version": "oncemesh.action/v0",
        "operation": {"name": "document.html-to-markdown", "version": "1"},
        "inputs": {
            "content": {
                "digest": digest_bytes(html),
                "size": len(html),
                "media_type": media_type,
            }
        },
        "executor": {
            "name": "oncemesh.html-markdown",
            "version": "1",
            "config": {"profile": "readable-v1"},
        },
        "output_schema": "oncemesh.document/markdown-v1",
        "vary": {},
    }


class _ReadableMarkdownParser(HTMLParser):
    ignored = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignore_depth = 0
        self.link_targets: list[str] = []

    def _block(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n\n"):
            self.parts.append("\n\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.ignored:
            self.ignore_depth += 1
            return
        if self.ignore_depth:
            return
        attributes = dict(attrs)
        if tag in {"p", "div", "section", "article", "blockquote"}:
            self._block()
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._block()
            self.parts.append("#" * int(tag[1]) + " ")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "li":
            self._block()
            self.parts.append("- ")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("_")
        elif tag == "code":
            self.parts.append("`")
        elif tag == "a":
            self.parts.append("[")
            self.link_targets.append(attributes.get("href") or "")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.ignored:
            if self.ignore_depth:
                self.ignore_depth -= 1
            return
        if self.ignore_depth:
            return
        if tag in {"p", "div", "section", "article", "blockquote", "li", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._block()
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag in {"em", "i"}:
            self.parts.append("_")
        elif tag == "code":
            self.parts.append("`")
        elif tag == "a":
            target = self.link_targets.pop() if self.link_targets else ""
            self.parts.append(f"]({target})" if target else "]")

    def handle_data(self, data: str) -> None:
        if self.ignore_depth:
            return
        self.parts.append(re.sub(r"[\t\r\n ]+", " ", data))

    def render(self) -> str:
        value = "".join(self.parts)
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
        output: list[str] = []
        for line in lines:
            if line:
                output.append(line)
            elif output and output[-1] != "":
                output.append("")
        return "\n".join(output).strip() + "\n"


def html_to_markdown_artifacts(html: bytes) -> dict[str, tuple[bytes, str]]:
    parser = _ReadableMarkdownParser()
    parser.feed(html.decode("utf-8"))
    parser.close()
    return {"document": (parser.render().encode("utf-8"), "text/markdown; charset=utf-8")}
