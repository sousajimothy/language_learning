"""Quick smoke-check: imports, signature, None sentinel, 5-tuple."""
import sys, random
sys.path.insert(0, "D:/Users/sousa/dev/repos/language_learning")

from german_pipeline import drills
from cli import PracticeMode, _MODE_ALLOWED_TYPES
import inspect

# --- signature ---
sig = inspect.signature(drills.pick_drill_with_pool)
params = list(sig.parameters.keys())
print("pick_drill_with_pool params:", params)
assert "allowed_types" in params, "allowed_types param missing"

# --- None sentinel: cloze-only mode on short noun item ---
pool = [{"id": i, "de": "der Hund", "de_mit_artikel": "der Hund",
         "en": "the dog", "notes": "Substantiv"} for i in range(12)]
rng = random.Random(0)
result = drills.pick_drill_with_pool(pool[0], pool, rng, {"cloze"})
assert result is None, f"expected None for cloze-mode on noun, got {result}"
print("cloze-mode on noun → None ✓")

# --- 5-tuple: translate mode ---
rng2 = random.Random(0)
result2 = drills.pick_drill_with_pool(pool[0], pool, rng2, {"en_to_de"})
assert result2 is not None
assert result2[0] == "en_to_de"
print(f"translate-mode on noun → {result2[0]} ✓")

# --- PracticeMode enum has 5 values ---
modes = list(PracticeMode)
assert len(modes) == 5, f"expected 5 modes, got {len(modes)}: {modes}"
print(f"PracticeMode has {len(modes)} values ✓")

# --- _MODE_ALLOWED_TYPES has all 5 entries ---
assert len(_MODE_ALLOWED_TYPES) == 5
print(f"_MODE_ALLOWED_TYPES has {len(_MODE_ALLOWED_TYPES)} entries ✓")

# --- CLI --help mentions --mode ---
import subprocess, sys as _sys
out = subprocess.check_output(
    [_sys.executable, "D:/Users/sousa/dev/repos/language_learning/cli.py",
     "practice", "--help"],
    stderr=subprocess.STDOUT,
    text=True,
)
assert "--mode" in out, "--mode not found in --help output"
print("cli.py practice --help contains --mode ✓")

print("\nSmoke-check passed.")
