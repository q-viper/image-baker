"""
Simple test script to verify ImageBaker API functionality.
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Initialize Qt application for testing
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

# Use ASCII-safe check marks
PASS = "[OK]"
FAIL = "[FAIL]"


def test_imports():
    """Test that all API components can be imported."""
    print("Testing imports...")
    try:
        from imagebaker import (AnnotationType, ImageBaker, Layer, __version__,
                                create_annotation, load_model)
        print(f"{PASS} All imports successful (version {__version__})")
        return True
    except Exception as e:
        print(f"{FAIL} Import failed: {e}")
        return False


def test_layer_creation():
    """Test Layer class functionality."""
    print("\nTesting Layer creation...")
    try:
        import numpy as np

        from imagebaker import Layer

        # Create from array
        image = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        layer = Layer.from_array(image, "test_layer")
        
        # Test methods
        layer.set_position(10, 20)
        layer.set_rotation(45)
        layer.set_scale(0.5)
        layer.set_opacity(0.7)
        
        print(f"[OK] Layer created and configured: {layer}")
        return True
    except Exception as e:
        print(f"[FAIL] Layer test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_annotation_creation():
    """Test annotation creation."""
    print("\nTesting Annotation creation...")
    try:
        from imagebaker import AnnotationType, create_annotation
        from imagebaker.api.annotation import (point_annotation,
                                               polygon_annotation,
                                               rectangle_annotation)

        # Rectangle
        rect = rectangle_annotation("person", 10, 10, 100, 100, color=(255, 0, 0))
        print(f"[OK] Rectangle annotation: {rect.label}")
        
        # Polygon
        poly = polygon_annotation("object", [(0, 0), (50, 0), (50, 50), (0, 50)])
        print(f"[OK] Polygon annotation: {poly.label}")
        
        # Points
        pts = point_annotation("keypoint", [(10, 10), (20, 20)])
        print(f"[OK] Point annotation: {pts.label}")
        
        # Generic
        ann = create_annotation(
            "generic",
            AnnotationType.RECTANGLE,
            [(0, 0), (100, 100)]
        )
        print(f"[OK] Generic annotation: {ann.label}")
        
        return True
    except Exception as e:
        print(f"[FAIL] Annotation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_baker_basic():
    """Test ImageBaker basic functionality."""
    print("\nTesting ImageBaker basic operations...")
    try:
        import numpy as np

        from imagebaker import ImageBaker
        
        baker = ImageBaker()
        
        # Create test images
        img1 = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
        img2 = np.random.randint(0, 255, (80, 80, 3), dtype=np.uint8)
        
        # Add layers
        layer1 = baker.add_layer_from_array(img1, "layer1")
        layer2 = baker.add_layer_from_array(img2, "layer2")
        
        print(f"[OK] Added {baker.get_layer_count()} layers")
        
        # Configure layers
        baker.set_layer_position(layer2, 10, 10)
        baker.set_layer_opacity(layer2, 0.5)
        baker.set_layer_scale(layer2, 0.8)
        
        info = baker.get_layer_info(layer2)
        print(f"[OK] Layer 2 info: position={info['position']}, opacity={info['opacity']}")
        
        # Save state
        baker.save_state()
        print("[OK] State saved")
        
        # Bake (without saving to disk)
        result = baker.bake()
        print(f"[OK] Baked image: {result.image.width()}x{result.image.height()}")
        
        # Convert to numpy
        arr = baker.to_numpy(result)
        print(f"[OK] Converted to numpy: {arr.shape}")
        
        return True
    except Exception as e:
        print(f"[FAIL] Baker test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_cli_help():
    """Test that CLI can show help."""
    print("\nTesting CLI help...")
    try:
        from imagebaker.cli import cli

        # Just check it can be imported
        print("[OK] CLI module loaded successfully")
        return True
    except Exception as e:
        print(f"[FAIL] CLI test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("ImageBaker API Test Suite")
    print("=" * 60)
    
    tests = [
        test_imports,
        test_layer_creation,
        test_annotation_creation,
        test_baker_basic,
        test_cli_help,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[FAIL] Test crashed: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    if failed == 0:
        print("\n[OK] All tests passed!")
        return 0
    else:
        print(f"\n[FAIL] {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
