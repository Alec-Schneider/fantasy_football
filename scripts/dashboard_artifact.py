"""Render the dashboard bundle into a single self-contained HTML page.

Second half of the two-step dashboard flow:

1. ``scripts/build_dashboard.py`` talks to Sleeper/nflverse and writes
   ``scripts/output/dashboard/bundle.json``.
2. This script reads that bundle and inlines it into
   ``scripts/templates/dashboard.html.tpl``, writing a standalone page.

The split exists because step 1 is slow and networked while step 2 is
instant and pure -- iterating on the page's design should not re-rank three
leagues' worth of free agents.

The data is inlined into the page rather than shipped as a sibling file the
page fetches. A published Artifact's CSP is hostile to outbound requests,
and an inlined bundle also means the page renders complete on first paint
with no loading state. This mirrors ``scripts/draft_board_artifact.py``'s
``{{DATA}}`` approach.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

#: The page template, with a ``{{DATA}}`` placeholder for the bundle.
TEMPLATE_PATH = Path(__file__).parent / "templates" / "dashboard.html.tpl"


def render(bundle_path: Path, template_path: Path = TEMPLATE_PATH) -> str:
    """Inline ``bundle_path``'s JSON into the dashboard template.

    Args:
        bundle_path: Path to ``bundle.json``, as written by
            ``scripts/build_dashboard.py``.
        template_path: The HTML template to fill. Defaults to
            :data:`TEMPLATE_PATH`.

    Returns:
        The complete page source.

    Raises:
        FileNotFoundError: If either the bundle or the template is missing.
    """
    bundle = json.loads(bundle_path.read_text())
    template = template_path.read_text()

    # ``</script>`` anywhere inside the JSON would close the host <script>
    # element early. Escaping the forward slash keeps the JSON byte-identical
    # to a parser while making the sequence inert to the HTML tokenizer.
    payload = json.dumps(bundle, separators=(",", ":")).replace("</", "<\\/")

    return template.replace("{{DATA}}", payload)


def main(argv: Optional[list[str]] = None) -> int:
    """Render the dashboard page and write it next to the bundle."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--bundle",
        type=Path,
        default=Path("scripts/output/dashboard/bundle.json"),
        help="Bundle written by build_dashboard.py.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("scripts/output/dashboard/dashboard.html"),
        help="Where to write the rendered page.",
    )
    args = parser.parse_args(argv)

    page = render(args.bundle)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page)

    print(f"wrote {args.out} ({args.out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
