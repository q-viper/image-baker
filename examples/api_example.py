"""
Example: Using ImageBaker as a Python library

This script demonstrates how to use ImageBaker programmatically
without the GUI.
"""

import sys
from pathlib import Path

# Add parent directory to path for development
sys.path.insert(0, str(Path(__file__).parent.parent))

# Initialize Qt application for headless operation
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from imagebaker import AnnotationType, ImageBaker, create_annotation


def main():
    print("=== ImageBaker API Example ===\n")
    
    # Initialize ImageBaker
    baker = ImageBaker(output_dir="./examples/output")
    
    # Example 1: Simple composition
    print("Example 1: Simple two-layer composition")
    print("-" * 40)
    
    # Check if example images exist, otherwise use any available images
    assets_dir = Path("assets")
    if not assets_dir.exists():
        print("Error: assets directory not found")
        return
    
    images = list(assets_dir.glob("*.png")) + list(assets_dir.glob("*.jpg"))
    if len(images) < 2:
        print("Error: Need at least 2 images in assets folder")
        return
    
    # Add first layer as background
    layer1 = baker.add_layer_from_file(
        images[0],
        layer_name="Background",
        opacity=1.0
    )
    print(f"Added layer 0: {images[0].name}")
    
    # Add second layer on top
    layer2 = baker.add_layer_from_file(
        images[1],
        layer_name="Foreground",
        opacity=0.7
    )
    baker.set_layer_position(layer2, x=50, y=50)
    baker.set_layer_scale(layer2, 0.5)  # Scale down to 50%
    print(f"Added layer 1: {images[1].name} at (50, 50) with 50% scale")
    
    # Add an annotation to layer 1
    ann = create_annotation(
        label="object",
        annotation_type=AnnotationType.RECTANGLE,
        coordinates=[(100, 100), (200, 200)],
        color=(255, 0, 0)
    )
    baker.add_annotation(layer2, ann)
    print("Added rectangle annotation to layer 1")
    
    # Save the current state
    baker.save_state()
    print("Saved state 0")
    
    # Bake and save
    result = baker.bake()
    output_path = baker.save(result, save_annotations=True)
    print(f"\n✓ Baked image saved to: {output_path}")
    print(f"✓ Image size: {result.image.width()}x{result.image.height()}")
    
    # Example 2: Multiple states
    print("\n" + "=" * 40)
    print("Example 2: Multiple states animation")
    print("-" * 40)
    
    # Modify layer 2 position and save new state
    baker.set_layer_position(layer2, x=100, y=100)
    baker.set_layer_rotation(layer2, 15)
    baker.save_state()
    print("Saved state 1: moved and rotated layer 1")
    
    baker.set_layer_position(layer2, x=150, y=150)
    baker.set_layer_rotation(layer2, 30)
    baker.save_state()
    print("Saved state 2: moved and rotated further")
    
    # Bake all states
    for step in range(3):
        result = baker.bake(step=step)
        output_path = baker.save(result, output_path=f"./examples/output/frame_{step}.png")
        print(f"✓ Saved frame {step}: {output_path}")
    
    # Example 3: Layer info
    print("\n" + "=" * 40)
    print("Example 3: Layer information")
    print("-" * 40)
    
    for i in range(baker.get_layer_count()):
        info = baker.get_layer_info(i)
        print(f"\nLayer {i}:")
        print(f"  Name: {info['name']}")
        print(f"  Position: {info['position']}")
        print(f"  Opacity: {info['opacity']}")
        print(f"  Rotation: {info['rotation']}°")
        print(f"  Scale: {info['scale']}")
        print(f"  Annotations: {info['annotation_count']}")
    
    print("\n" + "=" * 40)
    print("✓ All examples completed successfully!")


if __name__ == "__main__":
    main()
