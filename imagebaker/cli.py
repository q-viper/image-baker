"""
ImageBaker CLI

Command-line interface for ImageBaker operations.
"""

import sys
from pathlib import Path
from typing import List, Optional

import typer
# Initialize Qt application for headless operation
from PySide6.QtWidgets import QApplication

_app = None

def ensure_qapp():
    """Ensure QApplication is initialized."""
    global _app
    if _app is None:
        _app = QApplication.instance() or QApplication(sys.argv)
    return _app

from imagebaker import logger
from imagebaker.api import AnnotationType, ImageBaker, create_annotation
from imagebaker.core.configs import CanvasConfig, LayerConfig

# Create main app
app = typer.Typer(
    name="imagebaker",
    help="ImageBaker - Image composition and annotation tool",
    add_completion=False,
    invoke_without_command=True,
)

# Create CLI subcommand group
cli = typer.Typer(help="Command-line interface operations")
app.add_typer(cli, name="cli")

# Create bake subcommands under cli
bake_app = typer.Typer(help="Baking (compositing) operations")
cli.add_typer(bake_app, name="bake")


@app.callback()
def main_callback(ctx: typer.Context):
    """
    ImageBaker - Image composition and annotation tool
    
    Run without arguments to launch the GUI.
    Use 'imagebaker cli' to see command-line interface options.
    """
    # If no subcommand is provided, launch GUI
    if ctx.invoked_subcommand is None:
        from imagebaker.window.app import run as gui_run
        gui_run(
            models_file="loaded_models.py",
            project_dir=".",
            configs_file="imagebaker/core/configs.py"
        )


@app.command()
def gui(
    models_file: Optional[str] = typer.Option(
        None, help="Path to Python file defining LOADED_MODELS."
    ),
    project_dir: str = typer.Option(
        ".", help="The project directory to use for the application."
    ),
    configs_file: Optional[str] = typer.Option(
        None,
        help="Python file with LayerConfig and CanvasConfig subclasses.",
    ),
):
    """
    Launch the ImageBaker GUI application.
    """
    from imagebaker.window.app import run as gui_run

    # Call the original GUI run function
    gui_run(
        models_file=models_file or "loaded_models.py",
        project_dir=project_dir,
        configs_file=configs_file or "imagebaker/core/configs.py"
    )


@bake_app.command("simple")
def bake_simple(
    images: List[Path] = typer.Argument(..., help="Image files to composite"),
    output: Path = typer.Option(
        "output.png", "-o", "--output", help="Output image path"
    ),
    positions: Optional[str] = typer.Option(
        None, "-p", "--positions",
        help="Comma-separated positions as 'x1,y1;x2,y2;...' (e.g., '0,0;100,50')"
    ),
    opacities: Optional[str] = typer.Option(
        None, "--opacities",
        help="Comma-separated opacity values 0.0-1.0 (e.g., '1.0,0.5,0.8')"
    ),
    scales: Optional[str] = typer.Option(
        None, "--scales",
        help="Comma-separated scale values (e.g., '1.0,0.5,1.2')"
    ),
    save_json: bool = typer.Option(
        False, "--json", help="Save annotations as JSON"
    ),
):
    """
    Simple baking: composite multiple images into one.
    
    Example:
        imagebaker bake simple image1.png image2.png -o output.png \\
            --positions "0,0;100,100" --opacities "1.0,0.5"
    """
    # Ensure Qt application is initialized
    ensure_qapp()
    
    try:
        baker = ImageBaker()
        
        # Parse positions
        position_list = []
        if positions:
            for pos_str in positions.split(';'):
                x, y = map(float, pos_str.split(','))
                position_list.append((x, y))
        else:
            position_list = [(0, 0)] * len(images)
        
        # Parse opacities
        opacity_list = []
        if opacities:
            opacity_list = [float(o) for o in opacities.split(',')]
        else:
            opacity_list = [1.0] * len(images)
        
        # Parse scales
        scale_list = []
        if scales:
            scale_list = [float(s) for s in scales.split(',')]
        else:
            scale_list = [1.0] * len(images)
        
        # Validate lengths
        if len(position_list) != len(images):
            typer.echo(f"Error: Number of positions ({len(position_list)}) "
                      f"must match number of images ({len(images)})")
            raise typer.Exit(1)
        
        if len(opacity_list) != len(images):
            typer.echo(f"Error: Number of opacities ({len(opacity_list)}) "
                      f"must match number of images ({len(images)})")
            raise typer.Exit(1)
        
        if len(scale_list) != len(images):
            typer.echo(f"Error: Number of scales ({len(scale_list)}) "
                      f"must match number of images ({len(images)})")
            raise typer.Exit(1)
        
        # Add layers
        typer.echo(f"Adding {len(images)} layers...")
        for i, img_path in enumerate(images):
            if not img_path.exists():
                typer.echo(f"Error: Image not found: {img_path}")
                raise typer.Exit(1)
            
            layer_id = baker.add_layer_from_file(img_path)
            baker.set_layer_position(layer_id, *position_list[i])
            baker.set_layer_opacity(layer_id, opacity_list[i])
            baker.set_layer_scale(layer_id, scale_list[i])
            
            typer.echo(f"  Layer {i}: {img_path.name} at {position_list[i]} "
                      f"(opacity={opacity_list[i]}, scale={scale_list[i]})")
        
        # Bake
        typer.echo("Baking...")
        result = baker.bake()
        
        # Save
        output_path = baker.save(result, output, save_annotations=save_json)
        
        typer.echo(f"✓ Saved to: {output_path}")
        if save_json:
            typer.echo(f"✓ Annotations saved to: {output_path.with_suffix('.json')}")
        
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        logger.exception(e)
        raise typer.Exit(1)


@bake_app.command("from-config")
def bake_from_config(
    config: Path = typer.Argument(..., help="Python config file with baking instructions"),
    output: Optional[Path] = typer.Option(None, "-o", "--output", help="Output image path"),
):
    """
    Bake images using a Python configuration file.
    
    The config file should define a 'bake_config' dictionary with layers and their properties.
    
    Example config.py:
        bake_config = {
            'layers': [
                {'file': 'bg.png', 'position': (0, 0), 'opacity': 1.0},
                {'file': 'fg.png', 'position': (100, 100), 'opacity': 0.5, 'rotation': 45},
            ],
            'output': 'result.png'
        }
    """
    # Ensure Qt application is initialized
    ensure_qapp()
    
    if not config.exists():
        typer.echo(f"Error: Config file not found: {config}")
        raise typer.Exit(1)
    
    try:
        import runpy
        config_globals = runpy.run_path(str(config))
        
        if 'bake_config' not in config_globals:
            typer.echo("Error: Config file must define 'bake_config' dictionary")
            raise typer.Exit(1)
        
        bake_config = config_globals['bake_config']
        baker = ImageBaker()
        
        # Add layers from config
        for layer_cfg in bake_config.get('layers', []):
            file_path = Path(layer_cfg['file'])
            if not file_path.exists():
                typer.echo(f"Error: Image not found: {file_path}")
                raise typer.Exit(1)
            
            layer_id = baker.add_layer_from_file(file_path)
            
            if 'position' in layer_cfg:
                baker.set_layer_position(layer_id, *layer_cfg['position'])
            if 'opacity' in layer_cfg:
                baker.set_layer_opacity(layer_id, layer_cfg['opacity'])
            if 'rotation' in layer_cfg:
                baker.set_layer_rotation(layer_id, layer_cfg['rotation'])
            if 'scale' in layer_cfg:
                scale = layer_cfg['scale']
                if isinstance(scale, (list, tuple)):
                    baker.set_layer_scale(layer_id, *scale)
                else:
                    baker.set_layer_scale(layer_id, scale)
            if 'visible' in layer_cfg:
                baker.set_layer_visibility(layer_id, layer_cfg['visible'])
        
        # Bake
        typer.echo(f"Baking {len(bake_config.get('layers', []))} layers...")
        result = baker.bake()
        
        # Determine output path
        output_path = output or bake_config.get('output', 'output.png')
        saved_path = baker.save(result, output_path)
        
        typer.echo(f"✓ Saved to: {saved_path}")
        
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        logger.exception(e)
        raise typer.Exit(1)


@cli.command()
def info(
    image: Path = typer.Argument(..., help="Image file to inspect"),
):
    """
    Display information about an image file.
    """
    # Ensure Qt application is initialized
    ensure_qapp()
    
    if not image.exists():
        typer.echo(f"Error: Image not found: {image}")
        raise typer.Exit(1)
    
    try:
        from PySide6.QtGui import QPixmap
        pixmap = QPixmap(str(image))
        
        if pixmap.isNull():
            typer.echo(f"Error: Failed to load image: {image}")
            raise typer.Exit(1)
        
        typer.echo(f"Image: {image}")
        typer.echo(f"  Size: {pixmap.width()} x {pixmap.height()}")
        typer.echo(f"  Depth: {pixmap.depth()} bits")
        typer.echo(f"  Has alpha: {pixmap.hasAlpha()}")
        typer.echo(f"  File size: {image.stat().st_size / 1024:.2f} KB")
        
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@cli.command()
def version():
    """Show ImageBaker version."""
    from imagebaker import __version__
    typer.echo(f"ImageBaker version {__version__}")


def main():
    """Main CLI entry point."""
    app()


if __name__ == "__main__":
    main()
