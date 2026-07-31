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


if __name__ == "__main__":
    unittest.main()
