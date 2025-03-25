import torch
import requests
from PIL import Image
import numpy as np
from typing import List
import cv2
from transformers import RTDetrV2ForObjectDetection, RTDetrImageProcessor

from loguru import logger
import time

# Import your base classes
from imagebaker.models.base_model import (
    BaseDetectionModel,
    DefaultModelConfig,
    ModelType,
    PredictionResult,
)


class RTDetrModelConfig(DefaultModelConfig):
    model_type: ModelType = ModelType.DETECTION
    model_name: str = "RTDetr-V2"
    model_description: str = (
        "Real-time Detection Transformer V2 model for object detection"
    )
    model_version: str = "r18vd"
    model_author: str = "PekingU"
    model_license: str = "Apache-2.0"
    pretrained_model_name: str = "PekingU/rtdetr_v2_r18vd"
    confidence_threshold: float = 0.5
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    return_annotated_image: bool = True

    # Annotation parameters
    box_thickness: int = 2
    text_thickness: int = 1
    text_scale: float = 0.5
    font_face: int = cv2.FONT_HERSHEY_SIMPLEX
    color_map: dict = {}


class RTDetrDetectionModel(BaseDetectionModel):
    def __init__(self, config: RTDetrModelConfig = RTDetrModelConfig()):
        super().__init__(config)

    def setup(self):
        """Initialize the model and processor"""
        logger.info(f"Loading RTDetr model from {self.config.pretrained_model_name}")

        # Load the image processor and model
        self.processor = RTDetrImageProcessor.from_pretrained(
            self.config.pretrained_model_name
        )
        self.model = RTDetrV2ForObjectDetection.from_pretrained(
            self.config.pretrained_model_name, device_map=self.config.device
        )

        # Update class names from the model
        if hasattr(self.model.config, "id2label"):
            self.config.class_names = list(self.model.config.id2label.values())

        # Generate color map for annotations if not provided
        if not self.config.color_map:
            self.generate_color_map()

        logger.info(f"Loaded model with {len(self.config.class_names)} classes")
        logger.info(f"Model running on {self.config.device}")

    def generate_color_map(self):
        """Generate a color map for the classes"""
        num_classes = len(self.config.class_names)
        np.random.seed(42)  # For reproducible colors

        colors = {}
        for i, class_name in enumerate(self.config.class_names):
            # Generate distinct colors with good visibility
            # Using HSV color space for better distribution
            hue = i / num_classes
            saturation = 0.8 + np.random.random() * 0.2
            value = 0.8 + np.random.random() * 0.2

            # Convert HSV to BGR (OpenCV uses BGR)
            hsv_color = np.array(
                [[[hue * 180, saturation * 255, value * 255]]], dtype=np.uint8
            )
            bgr_color = cv2.cvtColor(hsv_color, cv2.COLOR_HSV2BGR)[0][0]

            # Store as (B, G, R) tuple
            colors[class_name] = (
                int(bgr_color[0]),
                int(bgr_color[1]),
                int(bgr_color[2]),
            )

        self.config.color_map = colors

    def preprocess(self, image: np.ndarray):
        """Convert numpy array to PIL Image for the RTDetr processor"""
        self._original_image = (
            image.copy() if isinstance(image, np.ndarray) else np.array(image)
        )

        if isinstance(image, np.ndarray):
            # Convert numpy array to PIL Image
            pil_image = Image.fromarray(image.astype("uint8"))
            return pil_image
        return image

    def predict_boxes(self, image):
        """Run object detection on the input image"""
        # Prepare inputs
        inputs = self.processor(images=image, return_tensors="pt")

        # Move inputs to the same device as the model
        inputs = {k: v.to(self.config.device) for k, v in inputs.items()}

        # Run inference
        with torch.no_grad():
            outputs = self.model(**inputs)

        # Get original image dimensions for post-processing
        if isinstance(image, Image.Image):
            image_size = torch.tensor([(image.height, image.width)])
        else:
            # Assuming numpy array with shape (height, width, channels)
            image_size = torch.tensor([(image.shape[0], image.shape[1])])

        # Post-process the outputs
        results = self.processor.post_process_object_detection(
            outputs,
            target_sizes=torch.tensor(self.image_shape)
            .unsqueeze(0)
            .to(self.config.device),
            threshold=self.config.confidence_threshold,
        )

        return results[0]  # Return the first (and only) result

    def annotate_image(
        self, image: np.ndarray, results: List[PredictionResult]
    ) -> np.ndarray:
        """
        Draw bounding boxes and labels on the image

        Args:
            image: The original image as a numpy array
            results: List of PredictionResult objects

        Returns:
            Annotated image as a numpy array
        """
        annotated_image = image.copy()

        for result in results:
            # Extract data from result
            box = result.rectangle  # [x1, y1, x2, y2]
            score = result.score
            class_name = result.class_name

            if not box:
                continue

            # Get color for this class
            color = self.config.color_map.get(
                class_name, (0, 255, 0)
            )  # Default to green if not found

            # Draw bounding box
            cv2.rectangle(
                annotated_image,
                (box[0], box[1]),
                (box[2], box[3]),
                color,
                self.config.box_thickness,
            )

            # Prepare label text with class name and score
            label_text = f"{class_name}: {score:.2f}"

            # Calculate text size to create background rectangle
            (text_width, text_height), baseline = cv2.getTextSize(
                label_text,
                self.config.font_face,
                self.config.text_scale,
                self.config.text_thickness,
            )

            # Draw text background
            cv2.rectangle(
                annotated_image,
                (box[0], box[1] - text_height - 5),
                (box[0] + text_width, box[1]),
                color,
                -1,  # Fill the rectangle
            )

            # Draw text
            cv2.putText(
                annotated_image,
                label_text,
                (box[0], box[1] - 5),
                self.config.font_face,
                self.config.text_scale,
                (255, 255, 255),  # White text
                self.config.text_thickness,
            )

        return annotated_image

    def postprocess(self, output) -> List[PredictionResult]:
        """Convert model output to PredictionResult objects"""
        results = []

        # Extract outputs
        scores = output["scores"].cpu().numpy()
        labels = output["labels"].cpu().numpy()
        boxes = output["boxes"].cpu().numpy()

        annotation_time = time.time()

        for score, label_id, box in zip(scores, labels, boxes):
            # Get the class name
            class_name = self.model.config.id2label[label_id.item()]

            # Convert box coordinates to integers of x, y, w, h
            x = int(box[0])
            y = int(box[1])
            w = int(box[2] - box[0])
            h = int(box[3] - box[1])

            # Create a PredictionResult
            result = PredictionResult(
                class_name=class_name,
                class_id=int(label_id),
                score=float(score),
                rectangle=[x, y, w, h],
                annotation_time=f"{annotation_time:.6f}",
            )

            results.append(result)

        # If needed, add annotated image
        if (
            self.config.return_annotated_image
            and len(results) > 0
            and hasattr(self, "_original_image")
        ):
            annotated_image = self.annotate_image(self._original_image, results)

            # Update all results with the same annotated image
            for result in results:
                result.annotated_image = annotated_image

        return results


# Example usage
if __name__ == "__main__":
    import time
    import matplotlib.pyplot as plt

    # Create configuration
    config = RTDetrModelConfig()

    # Create model
    model = RTDetrDetectionModel(config)

    # Test with an image from URL
    url = "http://images.cocodataset.org/val2017/000000039769.jpg"
    response = requests.get(url, stream=True)
    image = Image.open(response.raw)

    # Convert to numpy array for compatibility with your pipeline
    image_np = np.array(image)

    # Run prediction
    t0 = time.time()
    prediction_results = model.predict(image_np)
    t1 = time.time()

    print(f"Total prediction time: {t1-t0:.4f} seconds")
    print(f"Found {len(prediction_results)} objects:")

    for result in prediction_results:
        print(f"{result.class_name}: {result.score:.2f} at {result.rectangle}")

    # Display the annotated image if available
    if prediction_results and prediction_results[0].annotated_image is not None:
        plt.figure(figsize=(12, 8))
        plt.imshow(
            cv2.cvtColor(prediction_results[0].annotated_image, cv2.COLOR_BGR2RGB)
        )
        plt.axis("off")
        plt.show()
