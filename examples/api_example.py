"""
Example: Using ImageBaker as a Python library

This script demonstrates how to use ImageBaker programmatically
without the GUI.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for development
sys.path.insert(0, str(Path(__file__).parent.parent))

if (
    sys.platform != "win32"
    and not os.environ.get("DISPLAY")
    and not os.environ.get("WAYLAND_DISPLAY")
):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Initialize Qt application for headless operation
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from imagebaker import AnnotationType, ImageBaker, create_annotation  # noqa: E402
from imagebaker.api.annotation import brush_annotation  # noqa: E402
from imagebaker.utils.annotation_formats import export_annotations_data  # noqa: E402
import numpy as np


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
    baker.add_layer_from_file(
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
    print("Example 4: Occluded Instance Segmentation with Brush & Z-Order Occlusion")
    print("-" * 40)
    occ_baker = ImageBaker(output_dir="./examples/output")

    # Background + Underlying object (left+right parts via brush mask or polygon) + Upper occluder pole
    bg_arr = np.full((200, 260, 4), (50, 60, 70, 255), dtype=np.uint8)
    car_arr = np.zeros((200, 260, 4), dtype=np.uint8)
    car_arr[80:140, 40:220] = (40, 120, 230, 255)
    pole_arr = np.zeros((200, 260, 4), dtype=np.uint8)
    pole_arr[20:190, 115:145] = (220, 220, 220, 255)

    occ_baker.add_layer_from_array(bg_arr, layer_name="StreetBg")
    car_mask = (car_arr[:, :, 3] > 0).astype(np.uint8)
    car_idx = occ_baker.add_layer_from_array(car_arr, layer_name="Car")
    occ_baker.add_annotation(
        car_idx,
        brush_annotation(
            label="car",
            mask=car_mask,
            color=(40, 120, 230),
            caption="Car split by foreground pole",
        ),
    )
    occ_baker.add_layer_from_array(pole_arr, layer_name="ForegroundPole")
    occ_res = occ_baker.bake()
    coco_out = export_annotations_data(
        occ_res.annotations, fmt="coco", image_name="occluded_scene.png", image_width=260, image_height=200
    )
    print(f"✓ Baked occluded scene annotations: {len(occ_res.annotations)} instance(s)")
    if coco_out["data"]["annotations"]:
        segs = coco_out["data"]["annotations"][0]["segmentation"]
        print(f"✓ Single COCO instance segmentation parts after pole occlusion: {len(segs)}")

    print("\n" + "=" * 40)
    print("✓ All examples completed successfully!")


if __name__ == "__main__":
    main()
