# -*- coding: utf-8 -*-
"""UI 模块主责模型路由回归（平台 v6-3 取证：占位壳 0/32）。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


class TestUiModelRouting:
    """平台 v6-3 取证：UI 是最重产物，flash 写前端产出占位壳——
    UI/组装模块路由到主帅模型。"""

    def _engine(self):
        from tests.test_dev_loop import make_engine
        import inspect
        return make_engine

    def test_ui_module_routes_to_main_model(self):
        from app.agents.dev_loop import DevLoopEngine
        eng = DevLoopEngine.__new__(DevLoopEngine)
        eng.main_model = "openai/deepseek-v4-pro"
        eng.dev_model = "openai/deepseek-v4-flash"
        assert eng._model_for_module(
            "view", "组装全部页面与静态资源") == "openai/deepseek-v4-pro"
        assert eng._model_for_module(
            "web_ui", "前端页面") == "openai/deepseek-v4-pro"

    def test_backend_module_stays_dev_model(self):
        from app.agents.dev_loop import DevLoopEngine
        eng = DevLoopEngine.__new__(DevLoopEngine)
        eng.main_model = "openai/deepseek-v4-pro"
        eng.dev_model = "openai/deepseek-v4-flash"
        assert eng._model_for_module(
            "data_core", "SQLite 数据层与建表") == "openai/deepseek-v4-flash"

    def test_same_model_formation_no_change(self):
        from app.agents.dev_loop import DevLoopEngine
        eng = DevLoopEngine.__new__(DevLoopEngine)
        eng.main_model = "openai/glm-5.3"
        eng.dev_model = "openai/glm-5.3"
        assert eng._model_for_module(
            "view", "前端页面") == "openai/glm-5.3"
