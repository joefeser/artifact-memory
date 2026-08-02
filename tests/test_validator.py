import unittest

from artifact_memory.validator import ValidationFailure, validate


class ValidatorTests(unittest.TestCase):
    def test_const_and_enum_do_not_coerce_booleans_to_numbers(self):
        for schema in ({"const": True}, {"enum": [True]}):
            validate(True, schema)
            with self.assertRaises(ValidationFailure):
                validate(1, schema)

        validate(1, {"const": 1.0})
        validate({"nested": True}, {"const": {"nested": True}})
        with self.assertRaises(ValidationFailure):
            validate({"nested": 1}, {"const": {"nested": True}})

    def test_dependent_required_fields_are_paired(self):
        schema = {
            "type": "object",
            "dependentRequired": {"rule_id": ["evidence_tier"], "evidence_tier": ["rule_id"]},
        }
        validate({}, schema)
        validate({"rule_id": "rule", "evidence_tier": "tier"}, schema)
        with self.assertRaises(ValidationFailure):
            validate({"rule_id": "rule"}, schema)
        with self.assertRaises(ValidationFailure):
            validate({"evidence_tier": "tier"}, schema)

    def test_max_items_is_enforced(self):
        schema = {"type": "array", "minItems": 1, "maxItems": 1, "items": {"type": "string"}}
        validate(["one"], schema)
        with self.assertRaises(ValidationFailure) as raised:
            validate(["one", "two"], schema)
        self.assertEqual(raised.exception.code, "constraint-failed")


if __name__ == "__main__":
    unittest.main()
