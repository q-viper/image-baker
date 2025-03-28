from imagebaker.core.defs import LayerState
from PySide6.QtCore import QPointF


def calculate_intermediate_states(previous_state, current_state, steps: int):
    """
    Calculate intermediate states between previous_state and current_state for a layer.
    Append the current_state to the list of states after calculating intermediates.
    """
    if not previous_state or not current_state:
        return [current_state]  # If no previous state, return only the current state

    intermediate_states = []
    for i in range(steps):
        # Interpolate attributes between previous_state and current_state
        interpolated_state = LayerState(
            layer_id=current_state.layer_id,
            layer_name=current_state.layer_name,
            opacity=previous_state.opacity
            + (current_state.opacity - previous_state.opacity) * (i / steps),
            position=QPointF(
                previous_state.position.x()
                + (current_state.position.x() - previous_state.position.x())
                * (i / steps),
                previous_state.position.y()
                + (current_state.position.y() - previous_state.position.y())
                * (i / steps),
            ),
            rotation=previous_state.rotation
            + (current_state.rotation - previous_state.rotation) * (i / steps),
            scale=previous_state.scale
            + (current_state.scale - previous_state.scale) * (i / steps),
            scale_x=previous_state.scale_x
            + (current_state.scale_x - previous_state.scale_x) * (i / steps),
            scale_y=previous_state.scale_y
            + (current_state.scale_y - previous_state.scale_y) * (i / steps),
            transform_origin=QPointF(
                previous_state.transform_origin.x()
                + (
                    current_state.transform_origin.x()
                    - previous_state.transform_origin.x()
                )
                * (i / steps),
                previous_state.transform_origin.y()
                + (
                    current_state.transform_origin.y()
                    - previous_state.transform_origin.y()
                )
                * (i / steps),
            ),
            order=current_state.order,
            visible=current_state.visible,
            allow_annotation_export=current_state.allow_annotation_export,
            playing=current_state.playing,
            selected=current_state.selected,
            is_annotable=current_state.is_annotable,
            status=current_state.status,
        )
        intermediate_states.append(interpolated_state)

    # Append the current state as the final state
    intermediate_states.append(current_state)

    return intermediate_states
