Highest Priority First
----------------------
- [ ] Define a plugin method. Try to implement smokesim here.
- [x] Instead of defining everything on app.py, use different file for each tab. Try to abstract more generic things in Base classes and inherit them.
- [ ] Merging two layers
- [ ] A small dropdown on the layers list that toggles what annotation to export for this layer. Should be options: Default, Rectangle, Polygon.
- [ ] Occlusion handling.
- [ ] Instead of separate prompt model class, use a flag in the config. If a prompt is allowed, the prompt will be sent to the model else the propmt will be applied on the image i.e. if passed rectangle for non prompt segmentation model, model will receive cropped image.
- [ ] Add test scripts (to reproduce results if that is even possible).
- [ ] How to work with OCR? i.e. generating the image data with text on it.
- [ ] Add color picker from the active QWidget.
- [ ] Drawing with color.
- [ ] Layerifying the drawing.
- [ ] Option to show gridlines. Only if it does not affect the performance much.
- [ ] Add Circle mode. Now, we only have point, rectangle and polygon.
- [ ] Loading of video?
- [ ] Add pose annotation.


- [x] Copy pasting selected layer/annotation with ctrl+c ctrl+v.
- [x] Updating of annotation i.e. scaling for rectangle, moving point for polygon with cursors.
- [x] Mouse events should be same for both layers i.e. hot keys to pan, zoom select layer/annotation.
- [x] Use LayerSettings properly i.e. should be able to see layer's transformation in slider. Upon moving those sliders, layer should show the changes too. Emit the settings and update the Layer. But could be slower based on the step size.
- [x] A checkbox to toggle the layer's annotation exportation. i.e. some annotations can be skipped like for the background.
- [x] Actual baking of images has yet to be done. i.e. User should be able to click on the button called **Buffer State**. It should store the layer's settings and it's order in Canvas. Show the number of states available in buffer. 
- [x] Also show the dropdown for it and upon selecting, should change the canvas. Then add another button **Bake States**. This should apply the settings from buffer state and store the baked image and annotation. Additionally, this should be able to write the baked image and annotation to defined folder.
