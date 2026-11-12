"""Undo/redo stack management and clipboard copy/paste for AnnotableLayer."""

from imagebaker.core.defs import Annotation, MouseMode
from imagebaker.layers.base_layer import BaseLayer


class AnnotableHistoryMixin:
    """Mixin managing per-file undo/redo history and annotation clipboard ops."""

    def _history_pair(self) -> tuple[list, list]:
        key = str(self.file_path or "Runtime")
        if key not in self._history_by_file:
            self._history_by_file[key] = ([], [])
        return self._history_by_file[key]

    @property
    def _undo_stack(self) -> list:
        return self._history_pair()[0]

    @_undo_stack.setter
    def _undo_stack(self, value: list):
        key = str(self.file_path or "Runtime")
        _, redo_s = self._history_pair()
        self._history_by_file[key] = (list(value), redo_s)

    @property
    def _redo_stack(self) -> list:
        return self._history_pair()[1]

    @_redo_stack.setter
    def _redo_stack(self, value: list):
        key = str(self.file_path or "Runtime")
        undo_s, _ = self._history_pair()
        self._history_by_file[key] = (undo_s, list(value))

    @staticmethod
    def _annotation_signature(ann: Annotation) -> tuple:
        pts = tuple((round(p.x(), 3), round(p.y(), 3)) for p in (ann.points or []))
        rect = (
            (
                round(ann.rectangle.x(), 3),
                round(ann.rectangle.y(), 3),
                round(ann.rectangle.width(), 3),
                round(ann.rectangle.height(), 3),
            )
            if ann.rectangle
            else None
        )
        poly = (
            tuple((round(p.x(), 3), round(p.y(), 3)) for p in ann.polygon)
            if ann.polygon
            else None
        )
        mask_sig = (
            (ann.mask.shape, int(ann.mask.sum()))
            if ann.mask is not None
            else None
        )
        col = (
            (ann.color.red(), ann.color.green(), ann.color.blue())
            if ann.color
            else (255, 255, 255)
        )
        return (
            ann.label,
            col,
            pts,
            rect,
            poly,
            mask_sig,
            bool(ann.visible),
            getattr(ann, "caption", ""),
        )

    @classmethod
    def _annotations_equal(
        cls, before: list[Annotation], after: list[Annotation]
    ) -> bool:
        if len(before) != len(after):
            return False
        return all(
            cls._annotation_signature(a) == cls._annotation_signature(b)
            for a, b in zip(before, after, strict=False)
        )

    def _snapshot_annotations(self):
        return [ann.copy() for ann in self.annotations]

    def _restore_annotations(self, snapshot):
        self.annotations = [ann.copy() for ann in snapshot]
        for idx, ann in enumerate(self.annotations):
            ann.annotation_id = idx
            ann.selected = False
        self.selected_annotation = None
        self.current_annotation = None
        self.update()

    def _push_undo_state(self):
        snapshot = self._snapshot_annotations()
        if self._undo_stack and self._annotations_equal(self._undo_stack[-1], snapshot):
            self._redo_stack.clear()
            return
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > self._max_history:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self):
        if not self._undo_stack:
            self.messageSignal.emit("Nothing to undo.")
            return
        self._redo_stack.append(self._snapshot_annotations())
        self._restore_annotations(self._undo_stack.pop())
        self.annotationRemoved.emit()
        self.messageSignal.emit("Undo applied.")

    def redo(self):
        if not self._redo_stack:
            self.messageSignal.emit("Nothing to redo.")
            return
        self._undo_stack.append(self._snapshot_annotations())
        self._restore_annotations(self._redo_stack.pop())
        self.annotationRemoved.emit()
        self.messageSignal.emit("Redo applied.")

    def copy_annotation(self):
        self._copy_annotation()

    def paste_annotation(self):
        self._paste_annotation()

    def _copy_annotation(self):
        selected_annotations = [ann for ann in self.annotations if ann.selected]
        if not selected_annotations:
            self.selected_annotation = self._get_selected_annotation()
            if self.selected_annotation:
                selected_annotations = [self.selected_annotation]

        if selected_annotations:
            copied_annotations = [ann.copy() for ann in selected_annotations]
            for ann in copied_annotations:
                ann.selected = False
            BaseLayer.annotation_clipboard = copied_annotations
            self.copied_annotation = copied_annotations[0]
            self.messageSignal.emit(
                f"Copied {len(copied_annotations)} annotation(s)"
            )
            self.mouse_mode = MouseMode.IDLE
        else:
            self.messageSignal.emit("No annotation selected to copy.")

    def _paste_annotation(self):
        clipboard = BaseLayer.annotation_clipboard
        if clipboard:
            self._push_undo_state()
            pasted_annotations = []
            for copied_annotation in clipboard:
                new_annotation = copied_annotation.copy()
                new_annotation.annotation_id = len(self.annotations)
                new_annotation.selected = False
                new_annotation.file_path = self.file_path
                new_annotation._skip_label_registry = True
                self.annotations.append(new_annotation)
                self.annotationAdded.emit(new_annotation)
                self.thumbnails[new_annotation.annotation_id] = self.get_thumbnail(
                    new_annotation
                )
                pasted_annotations.append(new_annotation)

            self.messageSignal.emit(
                f"Pasted {len(pasted_annotations)} annotation(s)"
            )
            self.update()
        else:
            self.messageSignal.emit("No annotation copied to paste.")
