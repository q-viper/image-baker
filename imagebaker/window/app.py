from imagebaker.window.main_window import MainWindow
from imagebaker.core.configs import LayerConfig, CanvasConfig
from imagebaker import logger

import importlib.util
import runpy
import ast
import typer
from pathlib import Path
from PySide6.QtWidgets import QApplication

app_cli = typer.Typer()


def find_and_import_subclass(file_path: str, base_class_name: str):
    """
    Find and import the first subclass of a given base class in a Python file.

    Args:
        file_path (str): The path to the Python file to inspect.
        base_class_name (str): The name of the base class to look for subclasses of.

    Returns:
        type: The first subclass found, or None if no subclass is found.
    """
    with open(file_path, "r") as file:
        tree = ast.parse(file.read(), filename=file_path)

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id == base_class_name:
                    # Dynamically import the file and return the class
                    module_name = Path(file_path).stem
                    spec = importlib.util.spec_from_file_location(
                        module_name, file_path
                    )
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    return getattr(module, node.name)
    return None


def load_models(file_path: str):
    """Dynamically load the LOADED_MODELS object from the specified file."""
    try:
        # Ensure the file path is absolute
        file_path = Path(file_path).resolve()

        # Execute the file and return its global variables
        loaded_globals = runpy.run_path(str(file_path))
    except Exception as e:
        logger.error(f"Failed to load models from {file_path}: {e}")
        return {}

    # Ensure LOADED_MODELS exists in the loaded context
    if "LOADED_MODELS" not in loaded_globals:
        logger.warning(f"No LOADED_MODELS object found in {file_path}.")
        return {}

    return loaded_globals.get("LOADED_MODELS", {})


@app_cli.command()
def run(
    models_file: str = typer.Option(
        "loaded_models.py", help="Path to the Python file defining LOADED_MODELS."
    ),
    project_dir: str = typer.Option(
        ".", help="The project directory to use for the application."
    ),
    configs_file: str = typer.Option(
        "imagebaker/core/configs.py",
        help="The Python file to search for LayerConfig and CanvasConfig subclasses.",
    ),
):
    """
    Run the ImageBaker application.

    Args:
        models_file (str): Path to the Python file defining LOADED_MODELS.
        project_dir (str): The project directory to use for the application.
        configs_file (str): The Python file to search for LayerConfig and CanvasConfig subclasses.
    """
    models_file_path = Path(models_file)
    if not models_file_path.is_file():
        logger.warning(f"Models file not found: {models_file_path}")
        LOADED_MODELS = {None: None}
    else:
        LOADED_MODELS = load_models(models_file_path)

    configs_file_path = Path(configs_file)
    if not configs_file_path.is_file():
        logger.warning(f"Configs file not found: {configs_file_path}")
        layer_config_class = None
        canvas_config_class = None
    else:
        # Find and import subclasses of LayerConfig and CanvasConfig
        layer_config_class = find_and_import_subclass(configs_file_path, "LayerConfig")
        canvas_config_class = find_and_import_subclass(
            configs_file_path, "CanvasConfig"
        )

    # Use the imported subclass if found, or fall back to the default
    if layer_config_class:
        logger.info(f"Using LayerConfig subclass: {layer_config_class.__name__}")
        layer_config = layer_config_class()
    else:
        logger.info("No LayerConfig subclass found. Using default LayerConfig.")
        layer_config = LayerConfig(project_dir=project_dir)

    if canvas_config_class:
        logger.info(f"Using CanvasConfig subclass: {canvas_config_class.__name__}")
        canvas_config = canvas_config_class()
    else:
        logger.info("No CanvasConfig subclass found. Using default CanvasConfig.")
        canvas_config = CanvasConfig(project_dir=project_dir)

    main(layer_config, canvas_config, LOADED_MODELS)


def main(layer_config, canvas_config, LOADED_MODELS):

    # Initialize the application
    app = QApplication([])
    window = MainWindow(
        layerify_config=layer_config,
        canvas_config=canvas_config,
        loaded_models=LOADED_MODELS,
    )
    window.show()
    app.exec()


if __name__ == "__main__":
    app_cli()
