"""
Shared skill taxonomy for Code Quest's task curation.

One taxonomy for both kids, tiered by difficulty, with a per-kid ceiling
rather than two separate curricula — lets a kid graduate into harder tiers
over time without migrating them to a different skill set.
"""

SKILLS = [
    ("variables", "Variables", 1),
    ("type_casting", "Text vs. numbers (type conversion)", 1),
    ("shapes", "Basic shapes", 1),
    ("colors", "Color control", 1),
    ("loops_basic", "Single loops", 1),
    ("lists", "Lists", 1),
    ("parameters", "Function parameters", 1),
    ("nested_loops", "Nested loops", 2),
    ("conditionals", "Conditionals / input validation", 2),
    ("randomness", "Randomness", 2),
    ("functions", "Functions", 2),
    ("recursion", "Recursion", 3),
    ("event_handling", "Keyboard/event interactivity", 3),
    ("dynamic_programming", "Dynamic programming / memoization", 3),
]

KID_MAX_TIER = {"shayne": 3, "kelly": 1}


def allowed_skills(kid_id):
    max_tier = KID_MAX_TIER.get(kid_id, 1)
    return [(sid, label) for sid, label, tier in SKILLS if tier <= max_tier]
