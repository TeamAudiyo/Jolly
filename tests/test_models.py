from jolly.core.models import get_model, list_models, model_path


def test_bundled_models_exist() -> None:
    models = list_models()
    assert {model["id"] for model in models} == {"jolly6", "so100", "so101"}
    assert get_model("jolly6").dof == 6
    assert get_model("so101").dof == 5
    assert model_path(get_model("jolly6")).is_file()
