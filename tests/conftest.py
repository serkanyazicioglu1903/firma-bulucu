"""Keep bare-mode Streamlit unit tests from leaking UI context into AppTest.

Some existing unit tests call real form builders outside ScriptRunContext.
AppTest copies the calling context into its script thread, so pytest's single
process otherwise inherits a stale form and reports false nested-form errors.
Reset only BETWEEN tests, never during a script run.
"""
import pytest


@pytest.fixture(autouse=True)
def isolated_streamlit_layout_context():
    from streamlit.delta_generator_singletons import context_dg_stack, get_default_dg_stack_value
    for root in get_default_dg_stack_value():
        root._form_data = None
    context_dg_stack.set(get_default_dg_stack_value())
    yield
    for root in get_default_dg_stack_value():
        root._form_data = None
    context_dg_stack.set(get_default_dg_stack_value())


@pytest.fixture(autouse=True)
def restore_legacy_database_path():
    # test_core assigns this module global directly; it must not redirect later
    # AppTest cases to a previous test's SQLite file.
    import control_tower
    previous = control_tower.DB_PATH
    yield
    control_tower.DB_PATH = previous
