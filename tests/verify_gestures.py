"""Exercise Scene UI's real drag recognition with deterministic mouse rays."""

import omni.kit.app
import omni.kit.undo
import omni.kit.viewport.utility as vp_util
import omni.ui as ui
import omni.ui.scene as sc
from pxr import Gf

from section_box.manipulator import (
    SectionBoxManipulator,
    _ResizeDragGesture,
    _TranslateDragGesture,
)
from section_box.manipulator_model import SectionBoxManipulatorModel
from section_box.model import Face, SectionBox
from section_box.state import SectionBoxState


class DragInput(sc.GestureManager):
    def __init__(self, start_x=0.0, axis="x"):
        super().__init__()
        self.step = -10
        self.trace = []
        self.start_x = start_x
        self.axis = axis
        self.selection_layer = None
        self.selection_states = []

    def amend_input(self, event):
        step = min(self.step, 12)
        distance = min(max(step - 2, 0), 8) * 1.25
        x = self.start_x + (distance if self.axis == "x" else 0)
        y = distance if self.axis == "y" else 0
        event.mouse = sc.Vector2(x * 0.01, y * 0.01)
        event.mouse_origin = sc.Vector3(x, y, 5)
        event.mouse_direction = sc.Vector3(0, 0, -1)
        event.clicked = step == 1
        event.down = 1 <= step <= 10
        event.released = step == 11
        self.step += 1
        if step in (0, 1, 3):
            self.trace.append((step, list(event.mouse_origin), list(event.mouse_direction)))
        if self.selection_layer is not None and step in (1, 2, 3, 12):
            self.selection_states.append((step, self.selection_layer.visible))
        return event


async def verify_gestures():
    app = omni.kit.app.get_app()
    for mode in ("translate", "resize"):
        resize = mode == "resize"
        state = SectionBoxState()
        state.box = SectionBox()
        undo_count = len(omni.kit.undo.get_undo_stack())
        model = SectionBoxManipulatorModel(state)
        viewport_window = vp_util.get_active_viewport_window(usd_context_name=None)
        selection_layer = viewport_window._find_viewport_layer("Selection", "manipulator")
        assert selection_layer is not None, "Viewport selection layer is unavailable"
        selection_was_visible = selection_layer.visible
        assert selection_was_visible, "Normal viewport drag selection is disabled"
        grip = _ResizeDragGesture(model, Face.MAX_X) if resize else _TranslateDragGesture(model)
        grip.on_began()
        assert selection_layer.visible == selection_was_visible, "Grip drag disabled normal drag selection"
        grip.on_ended()
        assert selection_layer.visible == selection_was_visible
        grip.on_began()
        grip.on_canceled()
        assert selection_layer.visible == selection_was_visible
        window = ui.Window("Section Box drag check", width=400, height=400)
        with window.frame:
            projection = [0.01, 0, 0, 0, 0, 0.01, 0, 0, 0, 0, 0.001, 0, 0, 0, 0, 1]
            view = sc.SceneView(sc.CameraModel(projection, sc.Matrix44.get_translation_matrix(0, 0, -5)))
            with view.scene:
                gesture = _ResizeDragGesture(model, Face.MAX_X) if resize else _TranslateDragGesture(model)
                manager = DragInput()
                gesture.manager = manager
                SectionBoxManipulator._create_handle(7, ui.color.white, gesture)
        try:
            for _ in range(45):
                await app.next_update_async()
            expected_position = 5 if resize else 10
            assert abs(state.box.transform.ExtractTranslation()[0] - expected_position) < 0.01, (
                mode,
                state.box.transform.ExtractTranslation(),
                manager.trace,
            )
            assert abs(state.box.size[0] - (110 if resize else 100)) < 0.01
            assert len(omni.kit.undo.get_undo_stack()) == undo_count + 1
            moved_box = state.box
            omni.kit.undo.undo()
            assert state.box == SectionBox()
            omni.kit.undo.redo()
            assert state.box == moved_box
        finally:
            view.scene.clear()
            window.destroy()
            model.destroy()
            state.destroy()

    for face, manager, initial_size, expected_size in (
        (Face.MAX_X, DragInput(start_x=10), 20, 30),
        (Face.MIN_Z, DragInput(axis="y"), 20, None),
        (Face.MIN_Z, DragInput(axis="x"), 20, 20),
        (Face.MAX_X, DragInput(start_x=62), 100, 110),
    ):
        state = SectionBoxState()
        state.box = SectionBox(size=Gf.Vec3d(initial_size), faces=frozenset({face}))
        state.enabled = True
        model = SectionBoxManipulatorModel(state)
        window = ui.Window("Section Box arrow drag check", width=400, height=400)
        with window.frame:
            projection = [0.01, 0, 0, 0, 0, 0.01, 0, 0, 0, 0, 0.001, 0, 0, 0, 0, 1]
            view = sc.SceneView(sc.CameraModel(projection, sc.Matrix44.get_translation_matrix(0, 0, -5)))
            with view.scene:
                manipulator = SectionBoxManipulator(model)
        try:
            await app.next_update_async()
            if face == Face.MAX_X and initial_size == 20:
                selection_layer = vp_util.get_active_viewport_window(usd_context_name=None)._find_viewport_layer(
                    "Selection", "manipulator"
                )
                assert selection_layer.visible, "Normal drag selection is unavailable"
            for gesture in manipulator._face_gestures[face]:
                gesture.manager = manager
            if face == Face.MAX_X and initial_size == 20:
                manager.selection_layer = selection_layer
            for _ in range(45):
                await app.next_update_async()
            if manager.selection_layer is not None:
                assert (1, True) in manager.selection_states, manager.selection_states
                assert (2, True) in manager.selection_states, manager.selection_states
                assert (12, True) in manager.selection_states, manager.selection_states
                assert selection_layer.visible, "Selection stayed disabled after releasing the arrow"
            if expected_size is None:
                assert state.box.size[face.axis] > initial_size + 5, (face, state.box.size, manager.trace)
            else:
                assert abs(state.box.size[face.axis] - expected_size) < 0.01, (face, state.box.size, manager.trace)
            expected_center = face.sign * (state.box.size[face.axis] - initial_size) / 2
            assert abs(state.box.transform.ExtractTranslation()[face.axis] - expected_center) < 0.01
        finally:
            manipulator.destroy()
            view.scene.clear()
            window.destroy()
            model.destroy()
            state.destroy()
