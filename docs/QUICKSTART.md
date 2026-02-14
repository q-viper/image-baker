# ImageBaker Quick Start Guide

Welcome to ImageBaker! This guide will get you up and running in minutes.

## Installation

```bash
pip install imagebaker
```

Or for development:
```bash
git clone https://github.com/q-viper/image-baker.git
cd image-baker
pip install -e .
```

## Three Ways to Use ImageBaker

### 1. GUI Mode (Visual Interface)

Perfect for interactive work and exploration.

```bash
# Launch GUI (default - no command needed!)
imagebaker

# Or explicitly
imagebaker gui

# With ML models
imagebaker gui --models-file examples/loaded_models.py

# With custom config
imagebaker gui --configs-file my_config.py --project-dir ./my_project
```

**Features:**
- Visual layer manipulation
- Real-time preview
- Drawing and annotation tools
- Model integration for detection/segmentation
- State management

### 2. CLI Mode (Command Line)

Perfect for automation, scripting, and batch processing.

```bash
# Composite two images
imagebaker cli bake simple background.png foreground.png -o output.png

# With positioning and transparency
imagebaker cli bake simple bg.png fg1.png fg2.png -o result.png \
    --positions "0,0;100,50;200,100" \
    --opacities "1.0,0.8,0.6" \
    --scales "1.0,0.5,0.8"

# From configuration file
imagebaker cli bake from-config config.py

# Get image info
imagebaker cli info myimage.png

# Check version
imagebaker cli version
```

### 3. Library Mode (Python API)

Perfect for integration into your projects and programmatic control.

```python
from imagebaker import ImageBaker, create_annotation, AnnotationType

# Create baker
baker = ImageBaker()

# Add and configure layers
bg = baker.add_layer_from_file("background.png")
fg = baker.add_layer_from_file("object.png")

baker.set_layer_position(fg, x=100, y=100)
baker.set_layer_opacity(fg, 0.8)
baker.set_layer_rotation(fg, 45)
baker.set_layer_scale(fg, 0.5)

# Add annotation
ann = create_annotation(
    label="person",
    annotation_type=AnnotationType.RECTANGLE,
    coordinates=[(50, 50), (150, 150)],
    color=(255, 0, 0)
)
baker.add_annotation(fg, ann)

# Bake and save
result = baker.bake()
baker.save(result, "output.png", save_annotations=True)
```

## Common Use Cases

### Use Case 1: Simple Image Composition

**CLI:**
```bash
imagebaker bake simple layer1.png layer2.png -o composed.png \
    --positions "0,0;50,50" --opacities "1.0,0.5"
```

**Python:**
```python
from imagebaker import ImageBaker

baker = ImageBaker()
baker.add_layer_from_file("layer1.png")
l2 = baker.add_layer_from_file("layer2.png")
baker.set_layer_position(l2, 50, 50)
baker.set_layer_opacity(l2, 0.5)
baker.bake_and_save("composed.png")
```

### Use Case 2: Creating Animation Frames

```python
from imagebaker import ImageBaker

baker = ImageBaker()
bg = baker.add_layer_from_file("background.png")
sprite = baker.add_layer_from_file("sprite.png")

# Create 10 frames
for i in range(10):
    baker.set_layer_position(sprite, i * 50, i * 30)
    baker.set_layer_rotation(sprite, i * 36)
    baker.save_state(step=i)

# Export all frames
for i in range(10):
    result = baker.bake(step=i)
    baker.save(result, f"frame_{i:03d}.png")
```

### Use Case 3: Batch Processing

```python
from imagebaker import ImageBaker
from pathlib import Path

def process_folder(input_dir, output_dir):
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    for img in input_path.glob("*.png"):
        baker = ImageBaker()
        layer = baker.add_layer_from_file(img)
        baker.set_layer_scale(layer, 0.5)
        baker.bake_and_save(output_path / f"scaled_{img.name}")

process_folder("input", "output")
```

### Use Case 4: With ML Model Predictions

```python
from imagebaker import ImageBaker, load_models
from imagebaker.api.annotation import rectangle_annotation
import cv2

# Load models
models = load_models("examples/loaded_models.py")
detector = models["RTDetrV2"]

# Process image
baker = ImageBaker()
img_layer = baker.add_layer_from_file("scene.jpg")

# Run detection
image = cv2.imread("scene.jpg")
predictions = detector.predict(image)

# Add predictions as annotations
for pred in predictions:
    if pred.rectangle:
        x1, y1, x2, y2 = pred.rectangle
        ann = rectangle_annotation(
            pred.class_name, x1, y1, x2, y2,
            score=pred.score
        )
        baker.add_annotation(img_layer, ann)

# Save with annotations
result = baker.bake()
baker.save(result, "detected.png", save_annotations=True)
```

## Configuration File Format (for CLI)

Create a `bake_config.py` file:

```python
bake_config = {
    'layers': [
        {
            'file': 'background.png',
            'position': (0, 0),
            'opacity': 1.0,
            'scale': 1.0,
            'rotation': 0,
            'visible': True
        },
        {
            'file': 'foreground.png',
            'position': (100, 100),
            'opacity': 0.8,
            'scale': 0.5,
            'rotation': 15,
            'visible': True
        },
    ],
    'output': 'result.png'
}
```

Then run:
```bash
imagebaker bake from-config bake_config.py
```

## Tips & Tricks

### 1. Working with Numpy Arrays

```python
import numpy as np
from imagebaker import ImageBaker

# Create image programmatically
image = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

baker = ImageBaker()
baker.add_layer_from_array(image, "generated")
```

### 2. Multiple States for Variations

```python
baker = ImageBaker()
# ... add layers ...

# Save different variations
baker.set_layer_opacity(0, 1.0)
baker.save_state(step=0)  # Full opacity

baker.set_layer_opacity(0, 0.5)
baker.save_state(step=1)  # Half opacity

# Bake each
result1 = baker.bake(step=0)
result2 = baker.bake(step=1)
```

### 3. Get Layer Information

```python
info = baker.get_layer_info(layer_id)
print(f"Position: {info['position']}")
print(f"Opacity: {info['opacity']}")
print(f"Rotation: {info['rotation']}")
print(f"Scale: {info['scale']}")
```

### 4. Convert Results to Numpy

```python
result = baker.bake()
numpy_array = baker.to_numpy(result)

# Use with OpenCV
import cv2
bgr = cv2.cvtColor(numpy_array[:, :, :3], cv2.COLOR_RGB2BGR)
cv2.imwrite("output.jpg", bgr)
```

## Next Steps

- **Full API Documentation**: See [API Usage](api-usage.md)
- **Examples**: Check the `examples/` folder in the repository
- **GUI Features**: See the [Home](index.md) for GUI shortcuts and features
- **Contributing**: See CONTRIBUTING for contribution guidelines

## Getting Help

- **Issues**: [GitHub Issues](https://github.com/q-viper/image-baker/issues)
- **Documentation**: [Full API Reference](api-usage.md)
- **Examples**: Run `python examples/test_api.py` to test your installation

## What's Different from GUI-Only?

**Before (GUI only):**
```bash
imagebaker  # Always launches GUI
```

**Now (Three modes):**
```bash
imagebaker gui              # Launch GUI
imagebaker bake simple ...  # CLI commands
python -c "from imagebaker import ImageBaker; ..."  # Library
```

Everything is backward compatible! The GUI hasn't changed at all.
