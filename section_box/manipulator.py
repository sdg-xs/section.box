"""Persistent viewport shapes for moving and resizing the section box."""

from __future__ import annotations

import math

import omni.kit.viewport.utility as vp_util
import omni.ui as ui
import omni.ui.scene as sc
from pxr import Gf

from .manipulator_model import SectionBoxManipulatorModel
from .model import AXIS_VECTORS, EDGE_INDICES, Face

_WIRE_COLOR = ui.color(0.2, 0.85, 1.0, 0.9)
_FACE_COLOR = [0.2, 0.85, 1.0, 0.08]
_HANDLE_COLOR = ui.color(1.0, 0.6, 0.1, 1.0)
_HANDLE_HIT_COLOR = ui.color(1.0, 0.6, 0.1, 0.01)
_CENTER_COLOR = ui.color(1.0, 1.0, 0.2, 1.0)
_ARROW_TRIANGLES = [0, 1, 4, 1, 2, 4, 2, 3, 4, 3, 0, 4]


class _GripSelectionGate:
    def __init__(self, viewport_api):
        self._viewport_api = viewport_api
        self._active = set()
        self._guard = None

    def begin(self, gesture):
        if self._viewport_api is None:
            return
        self._active.add(gesture)
        if self._guard is None:
            self._guard = vp_util.disable_selection(self._viewport_api)

    def end(self, gesture):
        self._active.discard(gesture)
        if not self._active:
            self.release()

    def sync(self):
        self._active = {
            gesture for gesture in self._active if gesture.state in (sc.GestureState.BEGAN, sc.GestureState.CHANGED)
        }
        if not self._active:
            self.release()

    def release(self):
        self._active.clear()
        self._guard = None


class _GripGestureManager(sc.GestureManager):
    def should_prevent(self, gesture, preventer):
        if isinstance(gesture, _BoxDragGesture) and isinstance(preventer, _GripPressGesture):
            return False
        return super().should_prevent(gesture, preventer)


class _GripPressGesture(sc.ClickGesture):
    def __init__(self, selection_gate, manager):
        super().__init__(manager=manager)
        self._selection_gate = selection_gate

    def on_began(self):
        self._selection_gate.begin(self)

    def on_ended(self):
        self._selection_gate.end(self)

    def on_canceled(self):
        self._selection_gate.end(self)


class _BoxDragGesture(sc.DragGesture):
    def __init__(self, model: SectionBoxManipulatorModel, selection_gate=None, **kwargs):
        super().__init__(**kwargs)
        self._model = model
        self._selection_gate = selection_gate

    @property
    def priority(self):
        return 10

    def on_began(self):
        if self._selection_gate is not None:
            self._selection_gate.begin(self)
        self._model.state.begin_edit()

    def on_ended(self):
        try:
            self._model.state.end_edit()
        finally:
            if self._selection_gate is not None:
                self._selection_gate.end(self)

    def on_canceled(self):
        self.on_ended()


class _TranslateDragGesture(_BoxDragGesture):
    def on_changed(self):
        moved = self.sender.gesture_payload.moved
        state = self._model.state
        state.edit(box=state.box.translated(Gf.Vec3d(*moved)))


class _ResizeDragGesture(_BoxDragGesture):
    def __init__(self, model: SectionBoxManipulatorModel, face: Face, **kwargs):
        super().__init__(model, **kwargs)
        self._face = face
        self._last_mouse = None
        self._last_point = None

    def on_began(self):
        super().on_began()
        if self.sender:
            box = self._model.state.box
            local = AXIS_VECTORS[self._face.axis] * self._face.sign * box.size[self._face.axis] * 0.5
            self._plane_point = box.transform.Transform(local)
            self._view_direction = Gf.Vec3d(*self.raw_input.mouse_direction).GetNormalized()
            self._last_point = self._project_mouse()
            self._last_mouse = tuple(self.raw_input.mouse)

    def _project_mouse(self):
        origin = Gf.Vec3d(*self.raw_input.mouse_origin)
        ray = Gf.Vec3d(*self.raw_input.mouse_direction)
        denominator = Gf.Dot(ray, self._view_direction)
        if abs(denominator) < 1e-8:
            return None
        distance = Gf.Dot(self._plane_point - origin, self._view_direction) / denominator
        return origin + ray * distance

    def on_changed(self):
        point = self._project_mouse()
        if point is None or self._last_point is None:
            return
        box = self._model.state.box
        moved = point - self._last_point
        self._last_point = point
        outward = box.transform.TransformDir(AXIS_VECTORS[self._face.axis] * self._face.sign)
        length = outward.GetLength()
        if length == 0.0:
            return
        direction = outward / length
        if abs(Gf.Dot(direction, self._view_direction)) > 0.9:
            mouse = tuple(self.raw_input.mouse)
            dx, dy = mouse[0] - self._last_mouse[0], mouse[1] - self._last_mouse[1]
            distance = math.hypot(dx, dy)
            delta = moved.GetLength() * dy / distance / length if distance else 0.0
            self._last_mouse = mouse
        else:
            delta = Gf.Dot(moved, direction) / length
        self._model.state.edit(box=box.resized(self._face, delta))


class SectionBoxManipulator(sc.Manipulator):
    def __init__(self, model: SectionBoxManipulatorModel, viewport_api=None, **kwargs):
        self._model = model
        self._root = None
        self._lines = []
        self._faces = {}
        self._handles = {}
        self._arrows = {}
        self._face_gestures = {}
        self._selection_gate = _GripSelectionGate(viewport_api)
        self._gesture_manager = _GripGestureManager()
        self._center = None
        super().__init__(model=model, **kwargs)

    def on_build(self):
        self._selection_gate.release()
        self._lines = []
        self._faces = {}
        self._handles = {}
        self._arrows = {}
        self._face_gestures = {}
        with sc.Transform() as self._root:
            for _ in EDGE_INDICES:
                self._lines.append(sc.Line([0, 0, 0], [0, 0, 0], color=_WIRE_COLOR, thickness=1.5))
            for face in Face:
                self._faces[face] = sc.PolygonMesh([[0, 0, 0]] * 4, [_FACE_COLOR] * 4, [4], [0, 1, 2, 3])
                shaft_gesture, tip_gesture, point_gesture = (
                    _ResizeDragGesture(
                        self._model, face, selection_gate=self._selection_gate, manager=self._gesture_manager
                    )
                    for _ in range(3)
                )
                shaft_press, tip_press, point_press = (
                    _GripPressGesture(self._selection_gate, self._gesture_manager) for _ in range(3)
                )
                self._face_gestures[face] = (shaft_gesture, tip_gesture, point_gesture)
                shaft = sc.Line(
                    [0, 0, 0],
                    [0, 0, 0],
                    color=_HANDLE_COLOR,
                    thickness=2.5,
                    intersection_thickness=12,
                    gestures=[shaft_gesture, shaft_press],
                )
                tip = sc.PolygonMesh(
                    [[0, 0, 0]] * 5,
                    [_HANDLE_COLOR] * 5,
                    [3] * 4,
                    _ARROW_TRIANGLES,
                    gestures=[tip_gesture, tip_press],
                )
                self._arrows[face] = (shaft, tip)
                self._handles[face] = self._create_handle(9.0, _HANDLE_HIT_COLOR, point_gesture, point_press)
            self._center = self._create_handle(
                7.0,
                _CENTER_COLOR,
                _TranslateDragGesture(self._model, selection_gate=self._selection_gate, manager=self._gesture_manager),
                _GripPressGesture(self._selection_gate, self._gesture_manager),
            )
        self._update_geometry()

    def sync_selection_guard(self):
        self._selection_gate.sync()

    def destroy(self):
        self._selection_gate.release()
        super().destroy()

    @staticmethod
    def _create_handle(radius, color, gesture, press=None):
        with sc.Transform() as position:
            with sc.Transform(look_at=sc.Transform.LookAt.CAMERA, scale_to=sc.Space.SCREEN):
                sc.Rectangle(radius * 2, radius * 2, color=color, gestures=[gesture, press] if press else [gesture])
        return position

    def on_model_updated(self, item):
        # Keep gesture senders alive throughout a drag instead of rebuilding them.
        if self._root is not None:
            self._update_geometry()

    def _update_geometry(self):
        state = self._model.state
        self._root.visible = state.enabled and state.show_box
        box = state.box
        positive_sizes = [size for size in box.size if size > 0]
        arrow_length = min(positive_sizes, default=100.0) * 0.12
        corners = [list(point) for point in box.corners()]
        for line, (a, b) in zip(self._lines, EDGE_INDICES):
            line.start, line.end = corners[a], corners[b]
            line.visible = any(
                bool(a & (1 << face.axis)) == bool(b & (1 << face.axis)) == (face.sign > 0) for face in box.faces
            )
        for face in Face:
            indices = [i for i in range(8) if bool(i & (1 << face.axis)) == (face.sign > 0)]
            # Corner bit order makes a perimeter in 0, 1, 3, 2 order, even after rotation.
            self._faces[face].positions = [corners[indices[i]] for i in (0, 1, 3, 2)]
            self._faces[face].visible = face in box.faces
            shaft, tip = self._arrows[face]
            shaft.visible = tip.visible = face in box.faces
            self._handles[face].visible = face in box.faces
            local = AXIS_VECTORS[face.axis] * face.sign * box.size[face.axis] * 0.5
            center = box.transform.Transform(local)
            outward = box.transform.TransformDir(AXIS_VECTORS[face.axis] * face.sign).GetNormalized()
            tangent_a = box.transform.TransformDir(AXIS_VECTORS[(face.axis + 1) % 3]).GetNormalized()
            tangent_b = box.transform.TransformDir(AXIS_VECTORS[(face.axis + 2) % 3]).GetNormalized()
            outer = center + outward * arrow_length
            base = center + outward * (arrow_length * 0.55)
            point = outer
            width = arrow_length * 0.18
            shaft.start, shaft.end = list(center), list(base)
            tip.positions = [
                list(base + tangent_a * width + tangent_b * width),
                list(base - tangent_a * width + tangent_b * width),
                list(base - tangent_a * width - tangent_b * width),
                list(base + tangent_a * width - tangent_b * width),
                list(point),
            ]
            self._handles[face].transform = sc.Matrix44.get_translation_matrix(*point)
        self._center.transform = sc.Matrix44.get_translation_matrix(*box.transform.ExtractTranslation())
