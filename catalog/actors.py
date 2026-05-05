"""Actor catalog read API.

Loads `korea/catalogs/actors.yaml` and instantiates `Actor` objects per
the loaded entries (with optional calibration overlay).
"""

from __future__ import annotations

from pathlib import Path

from core.actor import Actor, RuleBasedActor


CATALOG_PATH = (Path(__file__).resolve().parent.parent
                / "korea" / "catalogs" / "actors.yaml")


def load_catalog(path: Path | str = CATALOG_PATH) -> list[dict]:
    """Load actors.yaml as a list of dicts."""
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def build_actors(*,
                 path: Path | str = CATALOG_PATH,
                 calibrations: dict[str, dict] | None = None,
                 actor_cls: type | None = None,
                 mvp_only: bool = True,
                 ) -> list[Actor]:
    """Instantiate Actors from the YAML catalog.

    - `calibrations`: optional {actor_id: calibration_dict} map (typically
      from db.latest_calibration).
    - `actor_cls`: defaults to RuleBasedActor; pass LLMBackedActor from
      llm.actor to enable LLM decisions.
    - `mvp_only`: if True, skip entries with `mvp: false`.
    """
    from catalog.variables import for_actor as variables_for_actor

    actor_cls = actor_cls or RuleBasedActor
    calibrations = calibrations or {}

    out: list[Actor] = []
    for entry in load_catalog(path):
        if mvp_only and not entry.get("mvp", False):
            continue
        if entry.get("decision_variables") is None:
            entry = dict(entry)
            entry["decision_variables"] = [v.id for v in variables_for_actor(entry["id"])]
        a = actor_cls.from_catalog_entry(
            entry, calibration=calibrations.get(entry["id"]),
        )
        out.append(a)
    return out
