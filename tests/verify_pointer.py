"""Exercise selection and arrow resizing with Kit's actual pointer event path."""

import asyncio
import traceback

import omni.kit.app
import omni.kit.ui_test as ui_test
import omni.kit.viewport.utility as vp_util
import omni.ui as ui
import omni.ui.scene as sc
from carb.input import MouseEventType
from pxr import Gf

from section_box.extension import get_runtime_state
from section_box.model import Face, SectionBox

APP = omni.kit.app.get_app()


async def frames(count=3):
    for _ in range(count):
        await APP.next_update_async()


async def move_and_press(position):
    ui.Workspace.get_window("Viewport").focus()
    await frames(5)
    await ui_test.input.emulate_mouse(MouseEventType.MOVE, position)
    await frames()
    await ui_test.input.emulate_mouse(MouseEventType.LEFT_BUTTON_DOWN)
    await frames()


async def release():
    await ui_test.input.emulate_mouse(MouseEventType.LEFT_BUTTON_UP)
    await frames()


async def selection_drag(gesture, model):
    start = ui_test.Vec2(450, 370)
    await move_and_press(start)
    for offset in (20, 60, 100):
        await ui_test.input.emulate_mouse(MouseEventType.MOVE, ui_test.Vec2(start.x + offset, start.y + offset))
        await frames()
    rect = model.get_as_floats("ndc_rect")
    assert gesture.state == sc.GestureState.CHANGED and abs(rect[2] - rect[0]) > 0.1, (gesture.state, rect)
    await release()


async def verify():
    try:
        await frames(20)
        viewport = vp_util.get_active_viewport_window()
        selection_layer = viewport._find_viewport_layer("Selection", "manipulator")
        selection_manipulator = selection_layer.layer._SelectionManipulatorItem__manipulator
        selection_gesture = next(
            gesture
            for gesture in selection_manipulator._GestureBindingManipulator__gestures
            if type(gesture).__name__ == "SelectionDragGesture"
        )

        await selection_drag(selection_gesture, selection_manipulator.model)
        state = get_runtime_state()
        state.enabled = True
        state.box = SectionBox(size=Gf.Vec3d(1), faces=frozenset({Face.MAX_X})).translated(Gf.Vec3d(0, 0, 5))
        await frames(10)

        manipulator = viewport._find_viewport_layer("SectionBox", "manipulator").layer.manipulator
        scene_view = manipulator.scene_view
        tip = Gf.Vec3d(*manipulator._arrows[Face.MAX_X][1].positions[4])
        clip = Gf.Vec4d(*tip, 1) * viewport.viewport_api.view * viewport.viewport_api.projection
        x = scene_view.screen_position_x + (clip[0] / clip[3] + 1) * scene_view.computed_width / 2
        y = scene_view.screen_position_y + (1 - clip[1] / clip[3]) * scene_view.computed_height / 2
        assert 0 < x < ui.Workspace.get_main_window_width()
        assert 0 < y < ui.Workspace.get_main_window_height()

        await move_and_press(ui_test.Vec2(x, y))
        for offset in (10, 30, 60, 100):
            await ui_test.input.emulate_mouse(MouseEventType.MOVE, ui_test.Vec2(x + offset, y))
            await frames()
            rect = selection_manipulator.model.get_as_floats("ndc_rect")
            assert selection_gesture.state != sc.GestureState.CHANGED, selection_gesture.state
            assert not rect or (rect[2] == rect[0] and rect[3] == rect[1]), rect
        assert state.box.size[0] > 1.1, state.box.size
        await release()
        assert selection_layer.visible, "Selection stayed disabled after the arrow drag"

        await selection_drag(selection_gesture, selection_manipulator.model)
        print("SECTION_BOX_POINTER_VERIFICATION_PASSED")
        APP.post_quit(0)
    except Exception:
        print(traceback.format_exc())
        APP.post_quit(1)


asyncio.ensure_future(verify())
