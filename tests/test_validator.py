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

    def test_unique_items_uses_json_equality(self):
        schema = {"type": "array", "uniqueItems": True}
        validate([{"value": True}, {"value": 1}], schema)
        with self.assertRaises(ValidationFailure) as raised:
            validate([{"value": True}, {"value": True}], schema)
        self.assertEqual(raised.exception.code, "constraint-failed")

    def test_non_string_object_keys_fail_as_validation_errors(self):
        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"known": {"type": "object"}},
        }
        for value in ({"known": {1: "bad"}}, {"known": {}, 1: "bad"}):
            with self.assertRaises(ValidationFailure) as raised:
                validate(value, schema)
            self.assertEqual(raised.exception.code, "type-mismatch")


if __name__ == "__main__":
    unittest.main()
