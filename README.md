# Image-Baker
Let's bake an image.

## Why is it relevant?
Augmenting images has been quite popular in Deep Learning field and most of the augmentation is done around transformations like rotation, translation, resizing and pixel transformations. However, combining two relevant images as augmentation is not so popular. I think the later thing can help in detection tasks as well as segmentation. Hence, I am trying to make this project as an advanced image augmentation.

## What's up with the name?
We will try to bake image by passing ingredients and moving them around. While baking, we add layers of ingredients and finally the baked version will be different than the individual.

## To Do
- [ ] Adding annotations to each layers.
    - Annotations can be bounding box or segmentation. But it should be also applied the same transformations its image receives. Albumentations.ai package does it.
- [ ] Adding test cases.
- [ ] A way to bake order. Currently baking starts in FIFO manner.

## Models
### Segment Anything Model (SAM)
Using the official [repo](https://github.com/facebookresearch/segment-anything?tab=readme-ov-file).

## Notes
* This is not going to finish if I do not hurry up.

## Credits
* Super Market: https://www.flickr.com/photos/76758469@N00/6186540531