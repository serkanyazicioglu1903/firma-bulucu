"""No external connections; group selector authorization is fail-closed."""
import unittest

from scripts.group_company_catalog import (
    COMPANY_LABELS, CompanyScopeDenied, require_explicit_company_scope,
    review_group_catalog,
)


class FourCompanyGroupTests(unittest.TestCase):
    def test_all_four_incorporated_company_labels_are_configured(self):
        self.assertEqual(tuple(COMPANY_LABELS), (
            "AS_ILERI_GIDA", "PLANET_INGREDIENTS",
            "AS_FOOD_GLOBAL", "AS_ILERI_HOLDING",
        ))
        review = review_group_catalog()
        self.assertEqual(review["entity_count"], 4)
        self.assertEqual(len(review["entities"]), 4)
        self.assertTrue(review["incorporation_user_confirmed"])
        self.assertFalse(review["verified_legal_names"])
        self.assertFalse(review["finance_isolation_verified"])
        self.assertFalse(review["consolidation_verified"])

    def test_company_selector_requires_explicit_server_grant(self):
        self.assertEqual(
            require_explicit_company_scope(
                "AS_FOOD_GLOBAL", frozenset({"AS_ILERI_GIDA", "AS_FOOD_GLOBAL"})
            ),
            "AS_FOOD_GLOBAL",
        )
        for code in COMPANY_LABELS:
            with self.subTest(unauthorized=code):
                with self.assertRaises(CompanyScopeDenied):
                    require_explicit_company_scope(code, ())
        with self.assertRaises(CompanyScopeDenied):
            require_explicit_company_scope("AS_FOOD_GLOBAL", {"AS_ILERI_GIDA"})
        with self.assertRaises(CompanyScopeDenied):
            require_explicit_company_scope("AS_FOOD_GLOBAL", None)
        with self.assertRaises(CompanyScopeDenied):
            require_explicit_company_scope("AS_FOOD_GLOBAL", "*")
        with self.assertRaises(CompanyScopeDenied):
            require_explicit_company_scope("MISSING_COMPANY", set(COMPANY_LABELS))

    def test_holding_and_admin_do_not_implicitly_grant_other_companies(self):
        with self.assertRaises(CompanyScopeDenied):
            require_explicit_company_scope("AS_ILERI_GIDA", ("AS_ILERI_HOLDING",))
        for code in COMPANY_LABELS:
            self.assertEqual(
                require_explicit_company_scope(code, tuple(COMPANY_LABELS)), code
            )


if __name__ == "__main__":
    unittest.main()
