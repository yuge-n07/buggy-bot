"""
opbr.py
-------
One Piece Bounty Rush medal set optimizer. Loads a locally bundled
dataset and finds the best 3-medal set for up to 3 required effect
traits, each with an optional condition. Supports fixing one medal.
Now includes context‑aware scoring: archetype matching and role‑based
trait suggestions. Bonus deduplication applied.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path

logger = logging.getLogger("buggy.opbr")

DATA_PATH = Path(__file__).parent / "data" / "opbr_data.json"
IMAGE_BASE_URL = "https://ace-kyle.github.io/OPBR-medal-set-builder/img/medals"
SOURCE_URL = "https://ace-kyle.github.io/OPBR-medal-set-builder/"

REQUIRED_TRAIT_COUNT = 3
MAX_TAG_SLOTS = 6

AFFECT_TYPE_TO_TRAIT: dict[int, str] = {
    1: "Skill 1 Cooldown Reduction",
    2: "Skill 2 Cooldown Reduction",
    4: "Damage Increase",
    5: "Damage Reduction",
    8: "Dodge Cooldown Speed",
    9: "HP Recovery",
    10: "Capture Speed",
    200: "HP Increase",
    201: "ATK Increase",
    203: "Crit Rate Increase",
    401: "Status Nullification",
    603: "Damage to Defenders",
    679: "Normal Attack Damage",
    1253: "Crit Rate Increase",
    1254: "Speed Increase",
}

TRAIT_TO_AFFECT_TYPES: dict[str, set[int]] = {}
for _affect_type, _trait_name in AFFECT_TYPE_TO_TRAIT.items():
    TRAIT_TO_AFFECT_TYPES.setdefault(_trait_name, set()).add(_affect_type)

TRAIT_NAMES: list[str] = list(TRAIT_TO_AFFECT_TYPES.keys()) + ["Any"]

MAX_BUCKET_SIZE = 60

# ------------------- Context‑aware constants -------------------
ARCHETYPE_TAGS = [
    "Straw Hat Pirates",
    "Animal Kingdom Pirates",
    "Big Mom Pirates",
    "Whitebeard Pirates",
    "Worst Generation",
    "Roger Pirates / Ex-Roger Pirates",
    "Revolutionary Army",
    "Navy",
    "Land of Wano",
    "Zou / Whole Cake Island",
    "Dressrosa",
    "Sky Island / LRLL",
    "Alabasta",
    "Water 7 / Enies Lobby",
    "Thriller Bark",
    "Sabaody Archipelago / Island of Women",
    "Fish-Man Island",
    "Punk Hazard",
    "Egghead",
]

ROLE_RULES = {
    "Captain": "attacker",
    "Worst Generation": "attacker",
    "Straw Hat Pirates": "attacker",
    "Lead Performer": "defender",
    "Animal Kingdom Pirates": "defender",
    "Navy": "defender",
    "Big Mom Pirates": "defender",
    "Runner": "runner",
    "Kingsbird": "runner",
    "Navigator": "runner",
}

ROLE_TRAITS = {
    "attacker": ["Damage Increase", "Skill 1 Cooldown Reduction", "Skill 2 Cooldown Reduction"],
    "defender": ["Damage Reduction", "Skill 1 Cooldown Reduction", "Skill 2 Cooldown Reduction"],
    "runner": ["Capture Speed", "Dodge Cooldown Speed", "Skill 1 Cooldown Reduction"],
}
# -----------------------------------------------------------------


@dataclass
class MedalInfo:
    medal_id: int
    name: str
    icon_url: str
    unique_trait: str


@dataclass
class TagBonus:
    tag_name: str
    kind: str
    detail: str


@dataclass
class MedalSetResult:
    trait_names: tuple[str, str, str]
    medals: list[MedalInfo]
    score: float
    tag_matches: int
    tag_bonuses: list[TagBonus] = field(default_factory=list)


class OPBRData:
    def __init__(self, path: Path = DATA_PATH):
        if not path.exists():
            raise FileNotFoundError(
                f"OPBR dataset not found at {path}. Run "
                f"scripts/extract_opbr_data.py to generate it."
            )
        raw = json.loads(path.read_text(encoding="utf-8"))

        self.medals_by_id: dict[int, dict] = {m["medal_id"]: m for m in raw["medals"]}
        self.all_medals: list[dict] = raw["medals"]
        self.tags: dict[str, dict] = raw["tags"]
        self.abilities: dict[str, dict] = raw["abilities"]

        self.characters: list[dict] = raw.get("characters", [])
        self.character_names: list[str] = sorted({c["name"] for c in self.characters})
        self._character_by_name: dict[str, dict] = {c["name"]: c for c in self.characters}
        self._character_by_lower: dict[str, dict] = {c["name"].lower(): c for c in self.characters}

        self._tag_id_by_exact_name: dict[str, str] = {t["name"].lower(): tid for tid, t in self.tags.items()}
        self.all_tag_names: list[str] = sorted({t["name"] for t in self.tags.values() if t.get("name")})

        # -- Build condition map -------------------------------------------------
        self._cond_map: dict[tuple[int | None, int | None], str] = {}
        condition_set: set[str] = set()
        for ability in self.abilities.values():
            atype = ability.get("affect_type")
            ctype = ability.get("cond_type")
            detail = ability.get("detail", "")
            if atype is None:
                continue
            cond_name = self._extract_condition_name(detail)
            if cond_name:
                self._cond_map[(atype, ctype)] = cond_name
                condition_set.add(cond_name)
            else:
                if ctype is not None:
                    fallback = f"Condition {ctype}"
                    self._cond_map[(atype, ctype)] = fallback
                    condition_set.add(fallback)
                else:
                    self._cond_map[(atype, None)] = "Any Condition"
                    condition_set.add("Any Condition")

        for atype in set(a for a, _ in self._cond_map.keys()):
            if (atype, None) not in self._cond_map:
                self._cond_map[(atype, None)] = "Any Condition"
                condition_set.add("Any Condition")

        self._condition_names: list[str] = sorted(
            [c for c in condition_set if c != "Any Condition"]
        )
        self._condition_names.insert(0, "Any Condition")

        self._trait_to_conditions: dict[str, set[str]] = {}
        for trait_name in TRAIT_NAMES:
            if trait_name == "Any":
                self._trait_to_conditions[trait_name] = set(self._condition_names)
                continue
            affect_types = TRAIT_TO_AFFECT_TYPES.get(trait_name, set())
            cond_set = set()
            for (atype, ctype), name in self._cond_map.items():
                if atype in affect_types:
                    cond_set.add(name)
            cond_set.add("Any Condition")
            self._trait_to_conditions[trait_name] = cond_set

        logger.info(
            "Extracted %d unique condition names for %d affect_type/cond_type pairs",
            len(self._condition_names), len(self._cond_map)
        )

        self._medal_affect_type: dict[int, int | None] = {}
        self._medal_cond_type: dict[int, int | None] = {}
        for medal in self.all_medals:
            ability = self.abilities.get(str(medal.get("ability_id")))
            if ability:
                self._medal_affect_type[medal["medal_id"]] = ability.get("affect_type")
                self._medal_cond_type[medal["medal_id"]] = ability.get("cond_type")
            else:
                self._medal_affect_type[medal["medal_id"]] = None
                self._medal_cond_type[medal["medal_id"]] = None

        self._trait_buckets: dict[str, list[dict]] = {name: [] for name in TRAIT_NAMES}
        for medal in self.all_medals:
            self._trait_buckets["Any"].append(medal)
            affect_type = self._medal_affect_type.get(medal["medal_id"])
            trait_name = AFFECT_TYPE_TO_TRAIT.get(affect_type)
            if trait_name and trait_name in self._trait_buckets:
                self._trait_buckets[trait_name].append(medal)

        logger.info(
            "Loaded %d medals, %d tags, %d traits, %d characters",
            len(self.medals_by_id), len(self.tags), len(TRAIT_NAMES), len(self.characters)
        )

    # ---------- Character methods ----------
    def search_characters(self, query: str, limit: int = 25) -> list[str]:
        query = query.strip().lower()
        if not query:
            return self.character_names[:limit]
        starts = [n for n in self.character_names if n.lower().startswith(query)]
        contains = [n for n in self.character_names if query in n.lower() and n not in starts]
        return (starts + contains)[:limit]

    def get_character_medals(self, character_name: str) -> list[tuple[int, str]]:
        char = self._character_by_name.get(character_name) or self._character_by_lower.get(character_name.lower())
        if not char:
            return []
        medal_ids = char.get("medal_ids", [])
        result = []
        for mid in medal_ids:
            medal = self.medals_by_id.get(mid)
            if medal:
                result.append((mid, medal.get("name", f"Medal {mid}")))
        return result

    # ---------- Condition methods ----------
    def _extract_condition_name(self, detail: str) -> str | None:
        if not detail:
            return None
        patterns = [
            r"(?i)^(?:When|After|If)\s+([^.]+)",
            r"(?i)when\s+([^.]+)",
            r"(?i)after\s+([^.]+)",
            r"(?i)if\s+([^.]+)",
        ]
        for pat in patterns:
            m = re.search(pat, detail)
            if m:
                cond = m.group(1).strip()
                cond = re.sub(r"[: -]+$", "", cond)
                if cond:
                    return cond
        for sep in [":", "–", "-"]:
            if sep in detail:
                part = detail.split(sep, 1)[0].strip()
                if part and len(part) < 50:
                    return part
        if len(detail) > 10:
            return detail[:30].strip()
        return None

    def get_condition_options(self) -> list[str]:
        return self._condition_names

    def get_conditions_for_trait(self, trait_name: str) -> list[str]:
        if trait_name not in self._trait_to_conditions:
            return self._condition_names
        return sorted(self._trait_to_conditions[trait_name])

    def resolve_condition(self, trait_name: str, cond_name: str) -> tuple[int | None, int | None] | str:
        if trait_name == "Any":
            return (None, None)
        affect_types = TRAIT_TO_AFFECT_TYPES.get(trait_name)
        if not affect_types:
            return f"Unknown trait: {trait_name}"
        if cond_name.lower() in ["any condition", "any", ""]:
            return (next(iter(affect_types)), None)

        cond_lower = cond_name.lower()
        for (atype, ctype), name in self._cond_map.items():
            if atype in affect_types and cond_lower in name.lower():
                return (atype, ctype)

        try:
            ctype = int(cond_name)
            for (atype, ctype2), name in self._cond_map.items():
                if atype in affect_types and ctype2 == ctype:
                    return (atype, ctype)
        except ValueError:
            pass

        return f"Condition '{cond_name}' not found for trait '{trait_name}'."

    # ---------- Tag search ----------
    def search_tags(self, query: str, limit: int = 25) -> list[str]:
        query = query.strip().lower()
        if not query:
            return self.all_tag_names[:limit]
        starts = [n for n in self.all_tag_names if n.lower().startswith(query)]
        contains = [n for n in self.all_tag_names if query in n.lower() and n not in starts]
        return (starts + contains)[:limit]

    def resolve_tag_id(self, name: str) -> str | None:
        return self._tag_id_by_exact_name.get(name.strip().lower())

    # ---------- Lookups ----------
    def medal_icon_url(self, medal: dict) -> str:
        icon_name = medal.get("icon_name") or f"img_icon_medal_{medal['medal_id']}"
        return f"{IMAGE_BASE_URL}/{icon_name}.webp"

    def ability_detail(self, ability_id: int | None) -> str:
        if not ability_id:
            return ""
        entry = self.abilities.get(str(ability_id))
        return entry["detail"] if entry else ""

    # ---------- Context‑aware profile ----------
    def get_medal_profile(self, medal_id: int) -> dict:
        medal = self.medals_by_id.get(medal_id)
        if not medal:
            return {}
        tag_ids = medal.get("tag_ids", [])
        tag_names = [self.tags.get(str(tid), {}).get("name", "") for tid in tag_ids]
        tag_names = [t for t in tag_names if t]

        profile = {
            "tags": set(tag_names),
            "role": None,
            "archetype": None,
        }

        for tag in tag_names:
            if tag in ROLE_RULES:
                profile["role"] = ROLE_RULES[tag]
                break

        for tag in tag_names:
            if tag in ARCHETYPE_TAGS:
                profile["archetype"] = tag
                break

        return profile

    def suggest_traits_for_role(self, role: str) -> list[str] | None:
        return ROLE_TRAITS.get(role)

    # ---------- Scoring ----------
    def _score_trio(
        self,
        medals: tuple[dict, dict, dict],
        required_tag_ids: list[str] | None = None,
        fixed_medal_id: int | None = None,
    ) -> tuple[float, int, list[TagBonus]]:
        required_tag_ids = required_tag_ids or []
        score = 100.0
        tag_matches = 0

        # 1. Requested tag matching
        if required_tag_ids:
            for medal in medals:
                medal_tags = {str(t) for t in medal.get("tag_ids", [])}
                tag_matches += sum(1 for tid in required_tag_ids if tid in medal_tags)
            score += tag_matches * 5

        # 2. Tag synergy (pair/trio bonuses) with deduplication
        tag_counts: dict[str, int] = {}
        for medal in medals:
            for tag_id in medal.get("tag_ids", []):
                try:
                    tag_counts[str(tag_id)] = tag_counts.get(str(tag_id), 0) + 1
                except Exception:
                    continue

        raw_bonuses: list[TagBonus] = []
        for tag_id, count in tag_counts.items():
            tag = self.tags.get(tag_id)
            if not tag:
                continue
            if count >= 2 and tag.get("set2_ability_id"):
                detail = self.ability_detail(tag["set2_ability_id"])
                if detail:
                    score += 10
                    raw_bonuses.append(TagBonus(tag["name"], "pair", detail))
            if count == 3 and tag.get("set3_ability_id"):
                detail = self.ability_detail(tag["set3_ability_id"])
                if detail:
                    score += 20
                    raw_bonuses.append(TagBonus(tag["name"], "trio", detail))

        # Deduplicate: keep only highest level per tag
        bonus_map: dict[str, TagBonus] = {}
        for bonus in raw_bonuses:
            existing = bonus_map.get(bonus.tag_name)
            if not existing or (bonus.kind == "trio" and existing.kind == "pair"):
                bonus_map[bonus.tag_name] = bonus
        bonuses = list(bonus_map.values())

        # 3. Context‑aware bonus (archetype only)
        if fixed_medal_id is not None:
            fixed_profile = self.get_medal_profile(fixed_medal_id)
            fixed_archetype = fixed_profile.get("archetype")
            if fixed_archetype:
                for medal in medals:
                    m_profile = self.get_medal_profile(medal["medal_id"])
                    if m_profile.get("archetype") == fixed_archetype:
                        score += 30

        return score, tag_matches, bonuses

    def _trimmed_bucket(self, trait_name: str, exclude_ids: set[int]) -> list[dict]:
        bucket = [m for m in self._trait_buckets.get(trait_name, []) if m["medal_id"] not in exclude_ids]
        if len(bucket) <= MAX_BUCKET_SIZE:
            return bucket
        bucket.sort(key=lambda m: len(m.get("tag_ids", [])), reverse=True)
        return bucket[:MAX_BUCKET_SIZE]

    # ---------- Public API ----------
    def resolve_traits(
        self,
        trait1: str | None,
        cond1: str | None,
        trait2: str | None = None,
        cond2: str | None = None,
        trait3: str | None = None,
        cond3: str | None = None,
    ) -> list[tuple[str, int | None, int | None]] | str:
        t1 = trait1.strip() if trait1 and trait1.strip() else "Any"
        c1 = cond1.strip() if cond1 and cond1.strip() else "Any Condition"
        t2 = trait2.strip() if trait2 and trait2.strip() else "Any"
        c2 = cond2.strip() if cond2 and cond2.strip() else "Any Condition"
        t3 = trait3.strip() if trait3 and trait3.strip() else "Any"
        c3 = cond3.strip() if cond3 and cond3.strip() else "Any Condition"

        traits = []
        raw_pairs = [
            (t1, c1),
            (t2, c2),
            (t3, c3),
        ]
        for tname, cname in raw_pairs:
            if tname not in TRAIT_NAMES:
                return f"'{tname}' isn't a recognized trait."
            result = self.resolve_condition(tname, cname)
            if isinstance(result, str):
                return result
            atype, ctype = result
            traits.append((tname, atype, ctype))
        return traits

    def resolve_tags(self, tag_names: list[str]) -> list[str] | str:
        tag_ids: list[str] = []
        for name in tag_names:
            if not name:
                continue
            tid = self.resolve_tag_id(name)
            if not tid:
                return f"'{name}' isn't a tag I recognize."
            if tid not in tag_ids:
                tag_ids.append(tid)
        return tag_ids[:MAX_TAG_SLOTS]

    def find_best_set(
        self,
        trait_conditions: list[tuple[str, int | None, int | None]],
        required_tag_ids: list[str] | None = None,
        exclude_ids: set[int] | None = None,
        fixed_medal_id: int | None = None,
    ) -> MedalSetResult | str:
        required_tag_ids = required_tag_ids or []
        exclude_ids = exclude_ids or set()

        # Auto‑suggest traits if all "Any" and fixed medal has a role
        if fixed_medal_id is not None:
            all_any = all(tname == "Any" for tname, _, _ in trait_conditions)
            if all_any:
                profile = self.get_medal_profile(fixed_medal_id)
                role = profile.get("role")
                if role:
                    suggested = self.suggest_traits_for_role(role)
                    if suggested and len(suggested) == 3:
                        new_conditions = []
                        for trait_name in suggested:
                            atype = next(iter(TRAIT_TO_AFFECT_TYPES.get(trait_name, set())), None)
                            if atype is not None:
                                new_conditions.append((trait_name, atype, None))
                            else:
                                new_conditions.append(("Any", None, None))
                        trait_conditions = new_conditions

        # Validate fixed medal
        if fixed_medal_id is not None:
            fixed_medal = self.medals_by_id.get(fixed_medal_id)
            if not fixed_medal:
                return f"Fixed medal {fixed_medal_id} not found."
            fixed_atype = self._medal_affect_type.get(fixed_medal_id)
            matches_any = False
            for tname, atype, ctype in trait_conditions:
                if atype is None:
                    matches_any = True
                    break
                if fixed_atype == atype:
                    matches_any = True
                    break
            if not matches_any:
                return f"Fixed medal does not match any of the required trait/condition slots."

        # Build buckets
        buckets = []
        for trait_name, atype, ctype in trait_conditions:
            if atype is None:
                bucket = self._trait_buckets.get("Any", [])
            else:
                bucket = self._trait_buckets.get(trait_name, [])
                if ctype is not None:
                    bucket = [m for m in bucket if self._medal_cond_type.get(m["medal_id"]) == ctype]
                bucket = [m for m in bucket if self._medal_affect_type.get(m["medal_id"]) == atype]

            bucket = [m for m in bucket if m["medal_id"] not in exclude_ids]
            if not bucket:
                return f"No medals left covering '{trait_name}' with that condition."

            def relevance(m: dict) -> tuple[int, int]:
                medal_tags = {str(t) for t in m.get("tag_ids", [])}
                requested_hits = sum(1 for tid in required_tag_ids if tid in medal_tags)
                return (requested_hits, len(medal_tags))
            bucket.sort(key=relevance, reverse=True)
            buckets.append(bucket[:MAX_BUCKET_SIZE])

        best_medals: tuple[dict, dict, dict] | None = None
        best_score = -1.0
        best_tag_matches = 0
        best_bonuses: list[TagBonus] = []

        for combo in product(*buckets):
            if len({m["medal_id"] for m in combo}) != 3:
                continue
            if fixed_medal_id is not None:
                if sum(1 for m in combo if m["medal_id"] == fixed_medal_id) != 1:
                    continue
            score, tag_matches, bonuses = self._score_trio(
                combo, required_tag_ids, fixed_medal_id
            )
            if score > best_score:
                best_score = score
                best_medals = combo
                best_tag_matches = tag_matches
                best_bonuses = bonuses

        if not best_medals:
            return "Couldn't find a valid medal set for that combination."

        medal_infos = [
            MedalInfo(
                medal_id=medal["medal_id"],
                name=medal.get("name", "Unknown Medal"),
                icon_url=self.medal_icon_url(medal),
                unique_trait=self.ability_detail(medal.get("ability_id")),
            )
            for medal in best_medals
        ]

        display_traits = [t[0] for t in trait_conditions]

        return MedalSetResult(
            trait_names=tuple(display_traits),
            medals=medal_infos,
            score=best_score,
            tag_matches=best_tag_matches,
            tag_bonuses=best_bonuses,
        )

    def find_replacement(
        self,
        trait_conditions: list[tuple[str, int | None, int | None]],
        slot_index: int,
        fixed_medals: list[dict],
        required_tag_ids: list[str] | None = None,
        exclude_ids: set[int] | None = None,
    ) -> MedalSetResult | str:
        required_tag_ids = required_tag_ids or []
        exclude_ids = set(exclude_ids or set())
        exclude_ids |= {m["medal_id"] for i, m in enumerate(fixed_medals) if i != slot_index}

        trait_name, atype, ctype = trait_conditions[slot_index]

        if atype is None:
            bucket = self._trait_buckets.get("Any", [])
        else:
            bucket = self._trait_buckets.get(trait_name, [])
            if ctype is not None:
                bucket = [m for m in bucket if self._medal_cond_type.get(m["medal_id"]) == ctype]
            bucket = [m for m in bucket if self._medal_affect_type.get(m["medal_id"]) == atype]

        bucket = [m for m in bucket if m["medal_id"] not in exclude_ids]
        if not bucket:
            return f"No alternative medals left covering '{trait_name}' with that condition."

        def relevance(m: dict) -> tuple[int, int]:
            medal_tags = {str(t) for t in m.get("tag_ids", [])}
            requested_hits = sum(1 for tid in required_tag_ids if tid in medal_tags)
            return (requested_hits, len(medal_tags))
        bucket.sort(key=relevance, reverse=True)
        bucket = bucket[:MAX_BUCKET_SIZE]

        best_medal: dict | None = None
        best_score = -1.0
        best_tag_matches = 0
        best_bonuses: list[TagBonus] = []

        for candidate in bucket:
            combo = list(fixed_medals)
            combo[slot_index] = candidate
            if len({m["medal_id"] for m in combo}) != 3:
                continue
            score, tag_matches, bonuses = self._score_trio(
                tuple(combo), required_tag_ids, fixed_medal_id=fixed_medals[0]["medal_id"]
            )
            if score > best_score:
                best_score = score
                best_medal = candidate
                best_tag_matches = tag_matches
                best_bonuses = bonuses

        if not best_medal:
            return f"No alternative medals left covering '{trait_name}' with that condition."

        final_medals = list(fixed_medals)
        final_medals[slot_index] = best_medal

        medal_infos = [
            MedalInfo(
                medal_id=medal["medal_id"],
                name=medal.get("name", "Unknown Medal"),
                icon_url=self.medal_icon_url(medal),
                unique_trait=self.ability_detail(medal.get("ability_id")),
            )
            for medal in final_medals
        ]

        display_traits = [t[0] for t in trait_conditions]

        return MedalSetResult(
            trait_names=tuple(display_traits),
            medals=medal_infos,
            score=best_score,
            tag_matches=best_tag_matches,
            tag_bonuses=best_bonuses,
        )


_opbr_data: OPBRData | None = None

def get_opbr_data() -> OPBRData:
    global _opbr_data
    if _opbr_data is None:
        _opbr_data = OPBRData()
    return _opbr_data