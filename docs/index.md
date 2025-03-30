# Image-Baker

Let's bake an image.

## Why is it relevant?

When training computer vision models (especially for detection and segmentation), labeling large amounts of data is crucial for better model performance. Often, the process involves multiple cycles of labeling, training, and evaluation. By generating multiple realistic labeled datasets from a single image, the time spent on labeling can be significantly reduced.

## What's up with the name?

The concept involves extracting portions of an image (e.g., objects of interest) using tools like polygons or models such as Segment Anything. These extractions are treated as layers, which can then be copied, pasted, and manipulated to create multiple instances of the desired object. By combining these layers step by step, a new labeled image with annotations in JSON format is created. The term "Baking" refers to the process of merging these layers into a single cohesive image.

## Getting Started

### Installation

#### Using PIP
This project is also available in PyPI server.

```bash
pip install imagebaker
```

#### Developing
Please, clone this repository and install it locally:

```bash
git clone https://github.com/q-viper/image-baker.git 
cd image-baker
pip install -e .
```

### First Run

Run the following command to launch the GUI:

```bash
imagebaker
```

If the command does not work, try running the example script after cloning the project.:

```bash
python examples/app.py
```

## Features

- **Annotating Images**: Load a folder of images and annotate them using bounding boxes or polygons.
- **Model Testing**: Define models for detection, segmentation, and prompts (e.g., points or rectangles) by following the base model structure in [imagebaker/models/base_model.py](imagebaker/models/base_model.py). See [examples/loaded_models.py](examples/loaded_models.py) for a working example.
- **Layerifying**: Crop images based on annotations to create reusable layers. Each cropped image represents a single layer.
- **Baking States**: Arrange layers to create image variations by dragging, rotating, adjusting opacity, and more. Save the state using the **Save State** button or **Ctrl + S**.
- **Playing States**: Replay saved states, export them locally, or use them for further predictions.
- **Exporting States**: Export the final annotated JSON and the baked multilayer image.

### Shortcuts
* **Ctrl + C**: Copy selected annotation/layer.
* **Ctrl + V**: Paste copied annotation/layer in its parent image/layer if it is currently open.
* **Delete**: Delete selected annotation/layer.
* **Left Click**: Select an annotation/layer on mouse position.
* **Left Click + Drag**: Drag a selected annotation/layer.
* **Double Left Click**: When using Polygon annotation, completes the polygon.
* **Right Click**: Deselect an annotation/layer. While on annotating polygon, undo last point.
* **Ctrl + Mouse Wheel**: Zoom In/Out on the mouse position i.e. resizes the viewport.
* **Ctrl + Drag**: If done on the background, the viewport is panned.
* **Ctrl + S**: Save State on Baker Tab.
* **Ctrl + D**: Draw Mode on Baker Tab. Drawing can happen on a selected or main layer.
* **Ctrl + E**: Erase Mode on Baker Tab.
* **Wheel**: Change size of the drawing pointer.


## Demo

## Demo

To see the tool in action, check out the demo video below:

[![Demo Video](https://img.youtube.com/vi/WckMT0r-2Lc/0.jpg)](https://youtu.be/WckMT0r-2Lc)

Click on the image above to play the video on YouTube.


## Contributions

Contributions are welcome! 

Do you find this project to be useful and looking for some features that is not implemented yet? Feel free to open issues or submit pull requests to improve the project.
