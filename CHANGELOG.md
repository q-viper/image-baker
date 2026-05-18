## May 19 2026

## Added
* Help tab with shortcuts and workflow hints for Layerify and Baker.
* Baker plugin framework with auto-discovery on tab switch and multi-select plugin options.
* Built-in plugins: `SineMovement`, `GaussianBlur`, and `PerspectiveTransform`.
* Baker undo/redo support (`Ctrl+Z` / `Ctrl+Y`) for canvas edits.
* Layer grouping by button and `Ctrl+G`, with ungroup support on grouped layers.
* Multi-layer selection in Baker with `Ctrl+Click` on canvas/layer list.
* Annotation conversion in Baker between polygon and rectangle for selected layers.
* Export-time brush annotation generation alongside baked masks/images.

## Updated
* Grid rendering now appears in front, follows page scale/zoom, and highlights around mouse position.
* Theme handling improved with more usable dark/light styling across tabs and docks.
* Baker state sequencing and timeline behavior improved to inspect plugin effects per step.
* `Steps` value resets to `1` after saving state while preserving saved state timeline.
* Layer insertion in Baker now consistently centers new layers and places them on top.
* Drawing done in Baker is preserved and passed back through Layerify/export flow.
* Layerify/Baker handoff for drawing/annotation data is more consistent and less error-prone.
* Plugin mask handling now falls back safely when annotation geometry does not map to layer-local pixels.
* Plugin option application now defaults to all layers when none are selected.

## May 18 2026
Worked on [#19](https://github.com/q-viper/image-baker/issues/19), [#24](https://github.com/q-viper/image-baker/issues/24), [#30](https://github.com/q-viper/image-baker/issues/30), and [#38](https://github.com/q-viper/image-baker/issues/38).

## Added
* Randomize states option in Baker tab.
* Brush-derived annotation export during baking.
* Distinct cursor visuals for all mouse modes, including zoom cursors.

## Updated
* Layer insertion in Baker tab now places new layers on top and centered in the current viewport.
* Label color handling now enforces a single color per label across annotation add/update/load flows and cached data.

## April 2 2025
Worked on [#3](https://github.com/q-viper/image-baker/issues/3), [#4](https://github.com/q-viper/image-baker/issues/4), [#5](https://github.com/q-viper/image-baker/issues/5) and [#6](https://github.com/q-viper/image-baker/issues/6).

## Fixed
* Handling of point movement in polygon.
* Can control the recursive image laoding or partial from config.

## Added
* Double click on edge of polygon will add a point.
* Double click on a polygon point will remove that point.
* Can move point polygon around.

## Removed
* Double click to select unselect annotation.

## March 24 2025
### Added
* Tested with Segmentation, Detection and Prompt models.
* Transformation of annotation and export.

### Updated
* Handling of model predictions.
* Handling of draging layer.


### Removed
