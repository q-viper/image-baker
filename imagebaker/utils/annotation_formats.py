"""Facade module re-exporting RLE, normalization, export, and import helpers."""

from imagebaker.utils.annotation_export import (
    export_annotations_data,
    save_annotations_to_path,
)
from imagebaker.utils.annotation_import import (
    load_annotation_dicts_from_data,
    load_annotations_from_path,
)
from imagebaker.utils.annotation_normalize import (
    SUPPORTED_ANNOTATION_FORMATS,
    UNDEFINED_LABEL,
    _deterministic_color_rgb,
    _infer_image_dimensions,
    _polygon_area,
    dict_to_annotation,
    normalize_annotation_dict,
)
from imagebaker.utils.rle import (
    _decode_label_studio_bitstream_rle,
    _extract_mask_geometry,
    mask_to_rle,
    rle_to_mask,
    shift_binary_mask,
)

__all__ = [
    "SUPPORTED_ANNOTATION_FORMATS",
    "UNDEFINED_LABEL",
    "_decode_label_studio_bitstream_rle",
    "_deterministic_color_rgb",
    "_extract_mask_geometry",
    "_infer_image_dimensions",
    "_polygon_area",
    "dict_to_annotation",
    "export_annotations_data",
    "load_annotation_dicts_from_data",
    "load_annotations_from_path",
    "mask_to_rle",
    "normalize_annotation_dict",
    "rle_to_mask",
    "save_annotations_to_path",
    "shift_binary_mask",
]
