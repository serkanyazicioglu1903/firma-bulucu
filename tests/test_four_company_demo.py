from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest

from four_company_demo import valid_company, _relation, _fields, add_record, update_record, delete_record


def test_only_four_companies():
    assert valid_company("AS_ILERI_GIDA") == "AS_ILERI_GIDA"
    with pytest.raises(ValueError):
        valid_company("OTHER")


def test_field_validation():
    assert _fields("Ürünler", {"name": "Gluten", "supplier": "X", "unit": "kg", "stock_kg": "25"})["stock_kg"] == Decimal("25")
    with pytest.raises(ValueError):
        _fields("Ürünler", {"name": "Gluten", "supplier": "X", "unit": "kg", "stock_kg": "-1"})
    with pytest.raises(ValueError):
        _fields("Müşteriler", {"name": "", "country": "", "contact": "", "email": ""})


def test_no_arbitrary_sql_table():
    with pytest.raises(ValueError):
        _relation("ct_app.customers")


def test_different_company_code_is_always_in_sql_params():
    class Cursor:
        def __init__(self):
            self.sql = ""
            self.params = ()
        def execute(self, sql, params):
            self.sql, self.params = sql, params
        def fetchone(self):
            return (12,)
    class Ctx:
        def __init__(self, value):
            self.value = value
        def __enter__(self):
            return self.value
        def __exit__(self, *args):
            pass
    cur = Cursor()
    class Conn:
        def cursor(self):
            return Ctx(cur)
    with patch("four_company_demo._db", return_value=Ctx(Conn())):
        add_record("AS_FOOD_GLOBAL", "Müşteriler", {
            "name": "Example", "country": "", "contact": "", "email": ""})
    assert cur.params[0] == "AS_FOOD_GLOBAL"
    assert "ct_demo.customers" in cur.sql
    assert "ct_app" not in cur.sql
