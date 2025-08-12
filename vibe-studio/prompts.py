# engine/prompts.py
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

import yaml

PLACEHOLDERS = [
    "subject_or_subjects",
    "location_description",
    "pose",
    "facial_expression",
    "clothing",
    "accessories",
    "hairstyle",
    "background_elements",
    "lighting",
    "camera_angle_and_composition",
]


@dataclass
class Tile:
    id: str
    title: str
    defaults: Dict[str, Any] = field(default_factory=dict)
    category_id: Optional[str] = None


@dataclass
class Category:
    id: str
    title: str
    tiles: List[Tile] = field(default_factory=list)


@dataclass
class PromptConfig:
    version: int
    template: str
    id: str = field(default_factory=lambda: str(uuid4()))
    globals_defaults: Dict[str, Any] = field(default_factory=dict)
    mixins: Dict[str, Any] = field(default_factory=dict)
    categories: List[Category] = field(default_factory=list)


class PromptConfigError(Exception):
    pass


class PromptBuilder:
    """
    Build prompts from a versioned YAML config using a strict placeholder set.

    Usage:
        pb = PromptBuilder("prompts/tiles_v2.yaml")
        prompt = pb.build("city.neon_rain_corner", overrides={"subject_or_subjects": "she"})
    """

    def __init__(self, yaml_path: Union[str, Path]):
        self.yaml_path = Path(yaml_path)
        self.config = self._load_yaml(self.yaml_path)
        self._tile_index: Dict[str, Tile] = {}
        self._index_tiles()

    # ------------- Public API -------------

    def list_tiles(self) -> List[str]:
        """Return fully-qualified tile ids: '<category>.<tile>'."""
        return sorted(self._tile_index.keys())

    def build(self, tile_key: str, overrides: Optional[Dict[str, Any]] = None) -> str:
        """
        Build the final prompt string.
        :param tile_key: either '<category>.<tile>' or a bare tile id if globally unique
        :param overrides: dict overriding any placeholder
        """
        overrides = overrides or {}
        # If a pre-baked prompt is provided, use it directly
        if overrides.get("all") is not None:
            return str(overrides.get("all", ""))
        tile = self._resolve_tile(tile_key)
        context = self._compose_context(tile, overrides)
        return self._render(self.config.template, context)

    def dry_run_context(
        self, tile_key: str, overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Return the merged, resolved placeholder map (pre-render)."""
        tile = self._resolve_tile(tile_key)
        return self._compose_context(tile, overrides or {})

    # ------------- Internal: loading & validation -------------

    def _load_yaml(self, path: Path) -> PromptConfig:
        if not path.exists():
            raise PromptConfigError(f"YAML not found: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))

        # Minimal validation
        version = int(data.get("version", 0))
        if version != 2:
            raise PromptConfigError(f"Unsupported version: {version} (expected 2)")

        template = data.get("template", "")
        if not template or not isinstance(template, str):
            raise PromptConfigError("Missing/invalid 'template'")

        globals_defaults = (data.get("globals", {}) or {}).get("defaults", {}) or {}
        mixins = (data.get("globals", {}) or {}).get("mixins", {}) or {}
        categories_raw = data.get("categories", []) or []

        categories: List[Category] = []
        for cat in categories_raw:
            cid = cat.get("id")
            title = cat.get("title", cid)
            tiles_raw = cat.get("tiles", []) or []
            tiles: List[Tile] = []
            for t in tiles_raw:
                tid = t.get("id")
                if not tid:
                    raise PromptConfigError(f"Tile missing id in category '{cid}'")
                tiles.append(
                    Tile(
                        id=tid,
                        title=t.get("title", tid),
                        defaults=t.get("defaults", {}) or {},
                        category_id=cid,
                    )
                )
            categories.append(Category(id=cid, title=title, tiles=tiles))

        return PromptConfig(
            version=version,
            template=template,
            globals_defaults=globals_defaults,
            mixins=mixins,
            categories=categories,
        )

    def _index_tiles(self) -> None:
        # Index as '<category>.<tile>' and also allow bare unique id
        bare_counts: Dict[str, int] = {}
        for cat in self.config.categories:
            for tile in cat.tiles:
                fqid = f"{cat.id}.{tile.id}"
                self._tile_index[fqid] = tile
                bare_counts[tile.id] = bare_counts.get(tile.id, 0) + 1

        # Add bare ids that are unique
        for fqid, tile in list(self._tile_index.items()):
            if bare_counts[tile.id] == 1:
                self._tile_index[tile.id] = tile

    def _resolve_tile(self, key: str) -> Tile:
        tile = self._tile_index.get(key)
        if not tile:
            raise PromptConfigError(f"Unknown tile: {key}. Known: {', '.join(self.list_tiles())}")
        return tile

    # ------------- Internal: composition & rendering -------------

    def _compose_context(self, tile: Tile, overrides: Dict[str, Any]) -> Dict[str, Any]:
        # Merge: globals.defaults -> tile.defaults -> overrides
        merged: Dict[str, Any] = {}
        merged.update(self.config.globals_defaults or {})
        merged.update(tile.defaults or {})
        merged.update(overrides or {})

        # Resolve @mixin.* tokens and normalize values
        out: Dict[str, Any] = {}
        for key in PLACEHOLDERS:
            val = merged.get(key, "")
            val = self._resolve_value(val)
            out[key] = self._normalize_value(val)

        return out

    def _resolve_value(self, val: Any) -> str:
        """
        Resolve values:
          - Lists -> comma-joined string
          - '@mixin.<path>' -> look up in globals.mixins
          - '@clear' -> empty string
        """
        if val is None:
            return ""
        if isinstance(val, list):
            # Join to a phrase; add 'and' if desired later
            return ", ".join([str(x) for x in val if str(x).strip()])
        if isinstance(val, (int, float)):
            return str(val)
        s = str(val).strip()

        if not s:
            return ""

        if s == "@clear":
            return ""

        if s.startswith("@mixin."):
            # Example: @mixin.lighting.moody_neon
            mixin_value = self._lookup_mixin(s.replace("@mixin.", "", 1))
            return str(mixin_value).strip()

        return s

    def _lookup_mixin(self, path: str) -> str:
        node: Any = self.config.mixins
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise PromptConfigError(f"Mixin not found: {path}")
            node = node[part]
        if isinstance(node, list):
            return ", ".join([str(x) for x in node if str(x).strip()])
        return str(node)

    @staticmethod
    def _strip_trailing_punct(s: str) -> str:
        # Avoid duplicating punctuation when template adds commas/periods.
        return re.sub(r"[,\.;:\s]+$", "", s.strip())

    def _normalize_value(self, s: str) -> str:
        s = " ".join(s.split())  # collapse whitespace
        s = self._strip_trailing_punct(s)
        return s

    def _render(self, template: str, context: Dict[str, str]) -> str:
        """
        Render line-by-line, dropping any line where a placeholder is empty.
        Also ensures clean spacing around punctuation added by the template.
        """
        lines_out: List[str] = []
        for raw_line in template.splitlines():
            line = raw_line.rstrip()
            if not line.strip():
                # keep structural blank lines as-is
                lines_out.append("")
                continue

            ph_names = re.findall(r"\{([a-zA-Z0-9_]+)\}", line)
            if not ph_names:
                # constant line
                lines_out.append(line)
                continue

            # If any placeholder is empty -> drop this line entirely
            vals = {name: context.get(name, "").strip() for name in ph_names}
            if any(v == "" for v in vals.values()):
                continue

            # Replace placeholders
            for name, val in vals.items():
                line = line.replace(f"{{{name}}}", val)

            # Clean stray spaces before punctuation
            line = re.sub(r"\s+([,\.])", r"\1", line)
            # Remove double punctuation artifacts
            line = re.sub(r"([,\.])\1+", r"\1", line)

            lines_out.append(line)

        # Trim leading/trailing blank lines; collapse triple blanks
        text = "\n".join(lines_out).strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text


# --------- CLI-ish helper for quick manual testing ----------
if __name__ == "__main__":
    # Example quick check:
    cfg_path = Path(__file__).resolve().parents[0] / "example.yaml"
    if cfg_path.exists():
        pb = PromptBuilder(cfg_path)
        print("Tiles:", ", ".join(pb.list_tiles()))
        print("--- Example build ---")
        prompt = pb.build(
            pb.list_tiles()[0],
            overrides={
                "subject_or_subjects": "she",
                # override clothing for demo
                "clothing": "a cobalt long-sleeve diagonal cut-out top and leather micro shorts, ankle boots",
            },
        )
        print(prompt)
    else:
        print("example.yaml not found for demo")
