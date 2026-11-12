"""Tests for Dataset generation, splitting, leakage prevention, and PyTorch integration."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from imagebaker.dataset import (  # noqa: E402
    CacheDatasetGenerator,
    DatasetBakeConfig,
    ImageBakerTorchDataset,
)


class TestDatasetGeneration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_imagebaker_dataset_"))
        self.cache_dir = self.temp_dir / "cache"
        self.layers_dir = self.cache_dir / "baker_layers"
        self.layers_dir.mkdir(parents=True, exist_ok=True)

        # Create 4 synthetic background images
        for i in range(4):
            bg = np.zeros((600, 800, 4), dtype=np.uint8)
            bg[:, :] = (30 * i, 50 * i, 70, 255)
            cv2.imwrite(str(self.layers_dir / f"bg_{i}.png"), bg)

        # Create 2 labeled foreground objects
        # 1: target_circle
        fg1 = np.zeros((100, 100, 4), dtype=np.uint8)
        cv2.circle(fg1, (50, 50), 40, (200, 100, 50, 255), -1)
        cv2.imwrite(str(self.layers_dir / "fg_circle.png"), fg1)

        # 2: target_box
        fg2 = np.zeros((80, 80, 4), dtype=np.uint8)
        cv2.rectangle(fg2, (10, 10), (70, 70), (40, 210, 80, 255), -1)
        cv2.imwrite(str(self.layers_dir / "fg_box.png"), fg2)

        # Create 1 unlabeled noise layer
        noise = np.zeros((70, 70, 4), dtype=np.uint8)
        cv2.circle(noise, (35, 35), 25, (128, 128, 128, 150), -1)
        cv2.imwrite(str(self.layers_dir / "noise_layer.png"), noise)

        # Write baker_cache.json
        cache_data = {
            "version": 1,
            "canvases": [
                {
                    "canvas_id": "c1",
                    "layers": [
                        {
                            "layer_id": f"bg_{i}",
                            "name": f"background_{i}",
                            "label": "background",
                            "image_file": f"baker_layers/bg_{i}.png",
                            "is_background": True,
                        }
                        for i in range(4)
                    ]
                    + [
                        {
                            "layer_id": "fg_1",
                            "name": "circle",
                            "label": "circle",
                            "image_file": "baker_layers/fg_circle.png",
                            "is_background": False,
                        },
                        {
                            "layer_id": "fg_2",
                            "name": "box",
                            "label": "box",
                            "image_file": "baker_layers/fg_box.png",
                            "is_background": False,
                        },
                        {
                            "layer_id": "noise_1",
                            "name": "distractor",
                            "label": "noise",
                            "image_file": "baker_layers/noise_layer.png",
                            "is_background": False,
                        },
                    ],
                }
            ],
        }
        (self.cache_dir / "baker_cache.json").write_text(json.dumps(cache_data), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_config_serialization_and_reproducibility(self):
        """Verify config can be saved, loaded, and produces deterministic results with seed."""
        cfg1 = DatasetBakeConfig(
            seed=42,
            background_size=(512, 512),
            split_ratios={"train": 0.8, "val": 0.2},
            unlabeled_labels=["noise"],
            export_format="coco",
        )
        cfg_path = self.temp_dir / "cfg.json"
        cfg1.to_json(cfg_path)
        self.assertTrue(cfg_path.exists())

        cfg2 = DatasetBakeConfig.from_json(cfg_path)
        self.assertEqual(cfg2.seed, 42)
        self.assertEqual(cfg2.background_size, (512, 512))
        self.assertEqual(cfg2.split_ratios, {"train": 0.8, "val": 0.2})
        self.assertEqual(cfg2.unlabeled_labels, ["noise"])
        self.assertEqual(cfg2.export_format, "coco")

        # Determinism check
        gen1 = CacheDatasetGenerator(cache_dir=self.cache_dir, config=cfg1)
        gen2 = CacheDatasetGenerator(cache_dir=self.cache_dir, config=cfg2)

        s1 = gen1.generate_sample(split="train", sample_index=0)
        s2 = gen2.generate_sample(split="train", sample_index=0)

        np.testing.assert_array_equal(s1["image"], s2["image"])
        self.assertEqual(len(s1["annotations"]), len(s2["annotations"]))

    def test_background_partition_isolation_without_leakage(self):
        """Verify backgrounds do not cross split boundaries when prevent_background_leakage=True."""
        cfg = DatasetBakeConfig(
            seed=999,
            split_ratios={"train": 0.5, "val": 0.25, "test": 0.25},
            prevent_background_leakage=True,
        )
        gen = CacheDatasetGenerator(cache_dir=self.cache_dir, config=cfg)
        bgs_partition = gen._partition_backgrounds()

        train_bgs = {b.source_file for b in bgs_partition["train"]}
        val_bgs = {b.source_file for b in bgs_partition["val"]}
        test_bgs = {b.source_file for b in bgs_partition["test"]}

        # Check for zero leakage / disjoint sets
        self.assertTrue(train_bgs.isdisjoint(val_bgs))
        self.assertTrue(train_bgs.isdisjoint(test_bgs))
        self.assertTrue(val_bgs.isdisjoint(test_bgs))
        self.assertEqual(len(train_bgs) + len(val_bgs) + len(test_bgs), 4)

    def test_unlabeled_noise_layers(self):
        """Verify noise layers are composited into the image but not included in ground truth annotations."""
        cfg = DatasetBakeConfig(
            seed=10,
            layers_per_image=(3, 3),  # Ensure all layers are used
            unlabeled_labels=["noise", "background"],
        )
        gen = CacheDatasetGenerator(cache_dir=self.cache_dir, config=cfg)
        sample = gen.generate_sample(split="train", sample_index=1)

        # Ground truth annotations should ONLY contain circle or box, NEVER noise
        ann_labels = [ann["label"] for ann in sample["annotations"]]
        for label in ann_labels:
            self.assertNotEqual(label, "noise")
            self.assertIn(label, ["circle", "box", "Undefined"])

    def test_background_resize_and_crop(self):
        """Verify aspect-ratio preserving resize and optional crop."""
        cfg = DatasetBakeConfig(
            background_size=(320, 240),
            preserve_aspect_ratio=True,
            crop_large_background=True,
            crop_mode="center",
            pad_color=(114, 114, 114),
        )
        gen = CacheDatasetGenerator(cache_dir=self.cache_dir, config=cfg)
        bg = gen.background_assets[0]
        prepared = gen.prepare_background(bg, np.random.RandomState(42))

        self.assertEqual(prepared.shape, (240, 320, 4))

    def test_layer_min_max_size_clamping(self):
        """Verify layer min/max bounds are strictly enforced."""
        cfg = DatasetBakeConfig(
            layer_min_size=(25, 25),
            layer_max_size=(150, 150),
        )
        gen = CacheDatasetGenerator(cache_dir=self.cache_dir, config=cfg)
        # Check clamp on tiny scale
        sx, sy = gen._clamp_layer_size(100, 100, target_scale=0.1)
        self.assertGreaterEqual(100 * sx, 25)
        self.assertGreaterEqual(100 * sy, 25)

        # Check clamp on huge scale
        sx2, sy2 = gen._clamp_layer_size(100, 100, target_scale=5.0)
        self.assertLessEqual(100 * sx2, 150)
        self.assertLessEqual(100 * sy2, 150)

    def test_offline_export_yolo(self):
        """Verify export_dataset in YOLO format creates data.yaml, images/, labels/."""
        cfg = DatasetBakeConfig(
            seed=12,
            background_size=(320, 320),
            split_ratios={"train": 0.6, "val": 0.4},
            export_format="yolo",
        )
        gen = CacheDatasetGenerator(cache_dir=self.cache_dir, config=cfg)
        out_yolo = self.temp_dir / "yolo_export"
        meta = gen.extract_dataset(output_dir=out_yolo, num_samples=5, format="yolo")

        self.assertEqual(meta["format"], "yolo")
        self.assertTrue((out_yolo / "data.yaml").exists())
        self.assertTrue((out_yolo / "classes.txt").exists())
        self.assertTrue((out_yolo / "images" / "train").exists())
        self.assertTrue((out_yolo / "labels" / "train").exists())
        self.assertTrue((out_yolo / "images" / "val").exists())
        self.assertTrue((out_yolo / "labels" / "val").exists())

        # Verify a label file is formatted correctly (class_id xc yc w h or class_id x1 y1 x2 y2 ...)
        label_files = list((out_yolo / "labels" / "train").glob("*.txt"))
        if label_files:
            lines = label_files[0].read_text().strip().splitlines()
            for line in lines:
                parts = line.split()
                # Detection: 5 items (class_id xc yc w h)
                # Segmentation: >= 7 items (class_id x1 y1 x2 y2 ...)
                self.assertTrue(len(parts) == 5 or (len(parts) >= 7 and len(parts) % 2 == 1))
                cls_idx = int(parts[0])
                self.assertGreaterEqual(cls_idx, 0)
                coords = [float(p) for p in parts[1:]]
                for c in coords:
                    self.assertTrue(0.0 <= c <= 1.0)

    def test_offline_export_coco(self):
        """Verify export_dataset in COCO format creates instances_train.json."""
        cfg = DatasetBakeConfig(
            seed=13,
            background_size=(320, 320),
            split_ratios={"train": 0.7, "val": 0.3},
            export_format="coco",
        )
        gen = CacheDatasetGenerator(cache_dir=self.cache_dir, config=cfg)
        out_coco = self.temp_dir / "coco_export"
        meta = gen.extract_dataset(output_dir=out_coco, num_samples=6, format="coco")

        self.assertEqual(meta["format"], "coco")
        ann_file = out_coco / "annotations" / "instances_train.json"
        self.assertTrue(ann_file.exists())
        coco_data = json.loads(ann_file.read_text())
        self.assertIn("images", coco_data)
        self.assertIn("annotations", coco_data)
        self.assertIn("categories", coco_data)

    def test_offline_export_default(self):
        """Verify export_dataset in default format creates per-image JSON annotations."""
        cfg = DatasetBakeConfig(
            seed=14,
            background_size=(320, 320),
            split_ratios={"train": 1.0},
            export_format="default",
        )
        gen = CacheDatasetGenerator(cache_dir=self.cache_dir, config=cfg)
        out_default = self.temp_dir / "default_export"
        meta = gen.extract_dataset(output_dir=out_default, num_samples=3, format="default")

        self.assertEqual(meta["format"], "default")
        train_anns = list((out_default / "train" / "annotations").glob("*.json"))
        self.assertGreaterEqual(len(train_anns), 1)

    def test_pytorch_dataset_sample_generation(self):
        """Verify ImageBakerTorchDataset returns sample images and targets."""
        cfg = DatasetBakeConfig(
            seed=55,
            background_size=(256, 256),
            split_ratios={"train": 1.0},
        )
        dataset = ImageBakerTorchDataset(
            cache_dir=self.cache_dir,
            config=cfg,
            split="train",
            length=10,
        )
        self.assertEqual(len(dataset), 10)

        image, target = dataset[0]
        self.assertIsNotNone(image)
        self.assertIn("boxes", target)
        self.assertIn("labels", target)
        self.assertIn("area", target)
        self.assertIn("polygons", target)
        self.assertIn("masks", target)
        self.assertEqual(target["width"], 256)
        self.assertEqual(target["height"], 256)

    def test_brush_rle_two_part_instance_dataset_and_pytorch_masks(self):
        """Verify two-part occluded RLE brush asset preserves single-instance COCO/YOLO/Default & PyTorch masks."""
        from imagebaker.utils.annotation_formats import mask_to_rle, rle_to_mask

        split_dir = Path(tempfile.mkdtemp(prefix="test_brush_rle_ds_"))
        try:
            cache_dir = split_dir / "cache"
            layers_dir = cache_dir / "baker_layers"
            layers_dir.mkdir(parents=True, exist_ok=True)

            bg = np.full((320, 320, 4), (35, 45, 55, 255), dtype=np.uint8)
            cv2.imwrite(str(layers_dir / "bg.png"), bg)

            # Single instance visually split by an occluder gap into left + right islands
            part_rgba = np.zeros((60, 140, 4), dtype=np.uint8)
            part_rgba[10:50, 10:50] = (20, 180, 240, 255)
            part_rgba[10:50, 90:130] = (20, 180, 240, 255)
            cv2.imwrite(str(layers_dir / "split_part.png"), part_rgba)

            bin_mask = (part_rgba[:, :, 3] > 0).astype(np.uint8)
            rle = mask_to_rle(bin_mask)

            cache_data = {
                "version": 1,
                "canvases": [
                    {
                        "canvas_id": "c_split",
                        "layers": [
                            {
                                "layer_id": "bg_0",
                                "name": "background_0",
                                "label": "background",
                                "image_file": "baker_layers/bg.png",
                                "is_background": True,
                            },
                            {
                                "layer_id": "fg_split",
                                "name": "split_plate",
                                "label": "split_plate",
                                "image_file": "baker_layers/split_part.png",
                                "is_background": False,
                                "annotation": {
                                    "annotation_id": 1,
                                    "label": "split_plate",
                                    "type": "brushlabels",
                                    "format": "rle",
                                    "rle": rle,
                                    "mask_size": [60, 140],
                                },
                            },
                        ],
                    }
                ],
            }
            (cache_dir / "baker_cache.json").write_text(json.dumps(cache_data), encoding="utf-8")

            cfg = DatasetBakeConfig(
                seed=7,
                background_size=(256, 256),
                split_ratios={"train": 1.0},
                layers_per_image=(1, 1),
                layer_min_size=20,
                layer_max_size=200,
                rotation_range=(0.0, 0.0),
                scale_range=(1.0, 1.0),
                opacity_range=(255.0, 255.0),
                position_mode="center",
            )
            gen = CacheDatasetGenerator(cache_dir=cache_dir, config=cfg)
            self.assertEqual(len(gen.foreground_assets), 1)
            self.assertIsNotNone(gen.foreground_assets[0].mask)

            # Default export preserves RLE two-island brush annotation
            out_def = split_dir / "out_default"
            gen.extract_dataset(output_dir=out_def, num_samples=2, format="default")
            ann_files = list((out_def / "train" / "annotations").glob("*.json"))
            self.assertGreaterEqual(len(ann_files), 1)
            def_anns = json.loads(ann_files[0].read_text())
            self.assertEqual(len(def_anns), 1)
            self.assertEqual(def_anns[0]["type"], "brushlabels")
            self.assertEqual(def_anns[0]["format"], "rle")
            self.assertTrue(len(def_anns[0]["rle"]) > 0)
            decoded = rle_to_mask(
                def_anns[0]["rle"],
                height=int(def_anns[0]["mask_size"][0]),
                width=int(def_anns[0]["mask_size"][1]),
            )
            num_labels, _ = cv2.connectedComponents((decoded > 0).astype(np.uint8))
            self.assertEqual(num_labels - 1, 2)

            # COCO export has 1 instance annotation with >= 2 segmentation polygons
            out_coco = split_dir / "out_coco"
            gen.extract_dataset(output_dir=out_coco, num_samples=2, format="coco")
            coco_data = json.loads((out_coco / "annotations" / "instances_train.json").read_text())
            self.assertGreaterEqual(len(coco_data["annotations"]), 1)
            first_coco = coco_data["annotations"][0]
            self.assertGreaterEqual(len(first_coco["segmentation"]), 2)

            # YOLO export bridges islands onto 1 instance segmentation line
            out_yolo = split_dir / "out_yolo"
            gen.extract_dataset(output_dir=out_yolo, num_samples=2, format="yolo")
            txt_files = list((out_yolo / "labels" / "train").glob("*.txt"))
            self.assertGreaterEqual(len(txt_files), 1)
            yolo_lines = [ln for ln in txt_files[0].read_text().splitlines() if ln.strip()]
            self.assertEqual(len(yolo_lines), 1)
            self.assertGreaterEqual(len(yolo_lines[0].split()), 9)

            # PyTorch dataset returns valid per-instance binary masks matching RLE islands
            ds = ImageBakerTorchDataset(cache_dir=cache_dir, config=cfg, split="train", length=2)
            _img, target = ds[0]
            masks = target["masks"]
            self.assertEqual(tuple(masks.shape), (1, 256, 256))
            self.assertGreater(int(masks.sum()), 0)
        finally:
            shutil.rmtree(split_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
