import json
from pathlib import Path
import unittest


FNV_OFFSET = 2166136261
FNV_PRIME = 16777619
NGRAM_FEATURES = 4096
NGRAM_MASK = NGRAM_FEATURES - 1


def hash3(c0, c1, c2):
    value = FNV_OFFSET
    for char in (c0, c1, c2):
        value ^= char
        value = (value * FNV_PRIME) & 0xFFFFFFFF
    return value & NGRAM_MASK


def route_prompt(model, prompt):
    scores = list(model["bias"])
    data = prompt.lower().encode()

    for i in range(max(0, len(data) - 2)):
        feature = hash3(data[i], data[i + 1], data[i + 2])
        for class_id in range(3):
            scores[class_id] += model["weights"][class_id][feature]

    route = max(range(3), key=lambda class_id: scores[class_id])
    return model["classes"][route], scores


class NgramRoutingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        model_path = Path(__file__).resolve().parents[1] / "models" / "xdp_ngram_model_fnv.json"
        with model_path.open() as file:
            cls.model = json.load(file)

    def test_model_shape_matches_xdp_constants(self):
        self.assertEqual(["coding", "general", "reasoning"], self.model["classes"])
        self.assertEqual([3, 3], self.model["ngram_range"])
        self.assertEqual(NGRAM_FEATURES, self.model["n_features"])
        self.assertEqual("xdp_fnv_v1", self.model["hash"])
        self.assertEqual(3, len(self.model["weights"]))
        self.assertTrue(all(len(weights) == NGRAM_FEATURES for weights in self.model["weights"]))

    def test_prompt_routes_are_deterministic(self):
        cases = {
            "Debug this Python TypeError in my code": "coding",
            "Write a Python function that parses JSON safely": "coding",
            "Refactor this Rust code to improve error handling": "coding",
            "Solve this logic puzzle step by step": "reasoning",
            "What is the capital of France?": "general",
            "Explain renewable energy in simple terms": "general",
            "Optimize a C implementation of quicksort.": "coding",
            "Analyze the tradeoffs and choose a strategy for planning a migration with rollback risk.": "reasoning",
            "Give me a practical checklist for planning a monthly budget." : "general",
            "Explain sleep hygiene in simple terms for a beginner.": "general"
        }

        for prompt, expected_route in cases.items():
            with self.subTest(prompt=prompt):
                route, scores = route_prompt(self.model, prompt)
                print(f"{prompt!r} -> {route} {scores}")
                self.assertEqual(expected_route, route)


if __name__ == "__main__":
    unittest.main(verbosity=2)
