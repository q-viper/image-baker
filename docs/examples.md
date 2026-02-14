# Examples

This page demonstrates various ways to use ImageBaker with real code examples and their outputs.

## Example 1: Simple API Usage - Two Layer Composition

Create a simple composition by loading two images and positioning one on top of the other.

**Script: `examples/api_example.py` (excerpt)**

```python
from imagebaker import ImageBaker, create_annotation, AnnotationType

# Initialize ImageBaker
baker = ImageBaker(output_dir="./output")

# Add background layer
layer1 = baker.add_layer_from_file(
    "assets/desk.png",
    layer_name="Background",
    opacity=1.0
)

# Add foreground layer
layer2 = baker.add_layer_from_file(
    "assets/pen.png",
    layer_name="Foreground",
    opacity=0.7
)

# Position and scale the foreground
baker.set_layer_position(layer2, x=50, y=50)
baker.set_layer_scale(layer2, 0.5)  # Scale down to 50%

# Add an annotation
ann = create_annotation(
    label="object",
    annotation_type=AnnotationType.RECTANGLE,
    coordinates=[(100, 100), (200, 200)],
    color=(255, 0, 0)
)
baker.add_annotation(layer2, ann)

# Bake and save
result = baker.bake()
output_path = baker.save(result, save_annotations=True)
print(f"Saved to: {output_path}")
```

**Output:**

![Two layer composition](../assets/demo/api_samples/ImageBaker_20260214_234822.png)

*Result: Desk background with pen overlay at position (50, 50) scaled to 50%*

---

## Example 2: Animation Frames - Multiple States

Create an animation by saving multiple states with different positions and rotations.

**Script: `examples/api_example.py` (excerpt)**

```python
from imagebaker import ImageBaker

baker = ImageBaker()

# Add layers
bg = baker.add_layer_from_file("assets/desk.png")
sprite = baker.add_layer_from_file("assets/pen.png")

# State 0: Initial position
baker.set_layer_position(sprite, x=50, y=50)
baker.set_layer_rotation(sprite, 0)
baker.save_state(step=0)

# State 1: Moved and rotated
baker.set_layer_position(sprite, x=100, y=100)
baker.set_layer_rotation(sprite, 15)
baker.save_state(step=1)

# State 2: Moved and rotated more
baker.set_layer_position(sprite, x=150, y=150)
baker.set_layer_rotation(sprite, 30)
baker.save_state(step=2)

# Bake all states
for step in range(3):
    result = baker.bake(step=step)
    baker.save(result, output_path=f"frame_{step}.png")
```

**Output Frames:**

<table>
<tr>
<td align="center">
<img src="../assets/demo/api_samples/frame_0.png" width="300"/>
<br/><strong>Frame 0</strong>
<br/><em>Initial position</em>
</td>
<td align="center">
<img src="../assets/demo/api_samples/frame_1.png" width="300"/>
<br/><strong>Frame 1</strong>
<br/><em>Moved & rotated 15°</em>
</td>
<td align="center">
<img src="../assets/demo/api_samples/frame_2.png" width="300"/>
<br/><strong>Frame 2</strong>
<br/><em>Moved & rotated 30°</em>
</td>
</tr>
</table>

*Animation sequence showing layer position and rotation changes across three states*

---

## Example 3: CLI - Simple Bake Command

Use the command-line interface to quickly composite images without writing code.

**Command:**

```bash
imagebaker cli bake simple assets/desk.png assets/pen.png assets/me.jpg \
    -o output.png \
    --positions "0,0;100,50;200,100" \
    --opacities "1.0,0.8,0.6" \
    --scales "1.0,0.5,0.3"
```

**Output:**

![CLI Simple Bake](../assets/demo/api_samples/cli_simple_bake.png)

*Result: Three layers composited with custom positions, opacities, and scales*

---

## Example 4: CLI - Config-Based Baking

Use a Python configuration file for more complex compositions.

**Configuration File: `examples/bake_config.py`**

```python
bake_config = {
    'layers': [
        {
            'file': 'assets/desk.png',
            'position': (0, 0),
            'opacity': 1.0,
            'scale': 1.0,
            'rotation': 0,
            'visible': True
        },
        {
            'file': 'assets/pen.png',
            'position': (100, 100),
            'opacity': 0.8,
            'scale': 0.5,
            'rotation': 15,
            'visible': True
        },
        {
            'file': 'assets/me.jpg',
            'position': (200, 50),
            'opacity': 0.6,
            'scale': 0.3,
            'rotation': -10,
            'visible': True
        },
    ],
    'output': 'output/baked_from_config.png',
}
```

**Command:**

```bash
imagebaker cli bake from-config examples/bake_config.py
```

**Output:**

![CLI Config Bake](../assets/demo/api_samples/cli_config_bake.png)

*Result: Multi-layer composition with position, rotation, and opacity from Python config file*

---

## Example 5: Working with NumPy Arrays

Integrate ImageBaker with NumPy for programmatic image generation.

**Script:**

```python
from imagebaker import ImageBaker
import numpy as np

baker = ImageBaker()

# Generate gradient programmatically
width, height = 640, 480
gradient = np.zeros((height, width, 3), dtype=np.uint8)
for i in range(height):
    gradient[i, :, 0] = int(255 * i / height)  # Red gradient
    gradient[i, :, 2] = int(255 * (1 - i / height))  # Blue gradient

# Add as layer
layer = baker.add_layer_from_array(gradient, "gradient")

# Add another image on top
overlay = baker.add_layer_from_file("assets/pen.png")
baker.set_layer_position(overlay, 200, 150)
baker.set_layer_opacity(overlay, 0.7)

# Bake and convert back to numpy
result = baker.bake()
numpy_image = baker.to_numpy(result)

print(f"Result shape: {numpy_image.shape}")
print(f"Result dtype: {numpy_image.dtype}")
```

---

## Example 6: Integration with OpenCV

Use ImageBaker with OpenCV for advanced image processing.

**Script:**

```python
from imagebaker import ImageBaker
import cv2

# Read with OpenCV
image = cv2.imread("assets/desk.png")
image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

# Use in ImageBaker
baker = ImageBaker()
layer = baker.add_layer_from_array(image_rgb, "opencv_image")

# Add another layer
overlay = baker.add_layer_from_file("assets/pen.png")
baker.set_layer_position(overlay, 100, 100)

# Bake and convert back
result = baker.bake()
output = baker.to_numpy(result)

# Save with OpenCV
output_bgr = cv2.cvtColor(output[:, :, :3], cv2.COLOR_RGB2BGR)
cv2.imwrite("output_opencv.jpg", output_bgr)
print("Saved with OpenCV")
```

---

## Example 7: Batch Processing

Process multiple images in a directory.

**Script:**

```python
from imagebaker import ImageBaker
from pathlib import Path

def process_batch(input_dir, output_dir):
    """Process all images in a directory."""
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    for img_file in input_path.glob("*.png"):
        baker = ImageBaker()
        layer = baker.add_layer_from_file(img_file)
        
        # Apply transformation
        baker.set_layer_opacity(layer, 0.8)
        baker.set_layer_scale(layer, 0.9)
        
        # Bake and save
        result = baker.bake()
        output_file = output_path / f"processed_{img_file.name}"
        baker.save(result, output_file)
        print(f"Processed: {img_file.name}")

# Process all images in assets folder
process_batch("assets", "output/processed")
```

---

## Running the Examples

To run any of these examples:

1. **Make sure ImageBaker is installed:**
   ```bash
   pip install imagebaker
   ```

2. **Clone the repository to get example files:**
   ```bash
   git clone https://github.com/q-viper/image-baker.git
   cd image-baker
   ```

3. **Run an example:**
   ```bash
   # Python API examples
   python examples/api_example.py
   python examples/test_api.py
   
   # CLI examples
   imagebaker cli bake simple assets/desk.png assets/pen.png -o output.png
   imagebaker cli bake from-config examples/bake_config.py
   ```

## Next Steps

- **API Reference**: See [API Usage](api-usage.md) for complete API documentation
- **Quick Start**: Check [Quick Start](QUICKSTART.md) for getting started guide
- **GUI Mode**: Run `imagebaker` to launch the visual interface
