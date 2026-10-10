"""Guard against accidental fictional data seeding on application startup."""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DemoSeedSafetyTests(unittest.TestCase):
    def test_render_requires_explicit_opt_in_for_all_demo_seeders(self):
        tree = ast.parse((ROOT / "control_tower.py").read_text(encoding="utf-8"))
        render = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == "render_control_tower")
        seeds = {"seed_once", "seed_product_catalog", "seed_warehouses"}
        found = set()
        for node in ast.walk(render):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in seeds:
                    found.add(node.func.id)
        self.assertEqual(found, seeds)
        # All three seed calls must be directly inside a single guarded IF.
        guards = [node for node in render.body if isinstance(node, ast.If)
                  and seeds == {
                      call.func.id for call in ast.walk(node)
                      if isinstance(call, ast.Call)
                      and isinstance(call.func, ast.Name)
                      and call.func.id in seeds
                  }]
        self.assertEqual(len(guards), 1)
        guard = guards[0]
        self.assertIn("AS_CONTROL_TOWER_DEMO_SEED", ast.unparse(guard.test))
        self.assertIn('== \'1\'', ast.unparse(guard.test))


if __name__ == "__main__":
    unittest.main()
