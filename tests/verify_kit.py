"""Run in the isolated test app through --exec; never in an occupied user stage."""

import asyncio
import importlib.util
import json
import math
import traceback
import weakref
from pathlib import Path
from unittest.mock import patch

import carb.settings
import omni.kit.app
import omni.kit.undo
import omni.kit.viewport.utility as vp_util
import omni.usd
from PIL import Image
from pxr import Gf, UsdGeom, UsdLux

from section_box.extension import SectionBoxExtension, get_runtime_state
from section_box.model import AXIS_VECTORS, Face, SectionBox
from section_box.selection import fit_box_to_paths

APP = omni.kit.app.get_app()
OUTPUT = Path(__file__).resolve().parent.parent / "verification"
PLANE_ATTR = "omni:rtx:scene:sectionPlane:plane"
_position_spec = importlib.util.spec_from_file_location(
    "verify_saved_positions", Path(__file__).with_name("verify_saved_positions.py")
)
_position_checks = importlib.util.module_from_spec(_position_spec)
_position_spec.loader.exec_module(_position_checks)
_selection_spec = importlib.util.spec_from_file_location(
    "verify_selection", Path(__file__).with_name("verify_selection.py")
)
_selection_checks = importlib.util.module_from_spec(_selection_spec)
_selection_spec.loader.exec_module(_selection_checks)


async def frames(count=5):
    for _ in range(count):
        await APP.next_update_async()


def probe_pixels(path):
    with Image.open(path) as image:
        data = image.convert("RGB").tobytes()
    green = orange = 0
    for r, g, b in zip(data[0::3], data[1::3], data[2::3]):
        green += g > r * 1.2 and g > b * 1.05
        orange += r > g * 1.1 and g > b * 1.1
    return green, orange


async def capture(viewport, name):
    path = OUTPUT / name
    path.unlink(missing_ok=True)
    await vp_util.capture_viewport_to_file(viewport, str(path)).wait_for_result()
    # Capture completion precedes the asynchronous PNG writer's completion.
    for _ in range(300):
        try:
            return probe_pixels(path)
        except OSError:
            await frames(1)
    raise AssertionError(f"Capture was not written: {path}")


async def capture_when(viewport, name, predicate):
    # Shader compilation and render-setting propagation are asynchronous.
    for _ in range(20):
        pixels = await capture(viewport, name)
        if predicate(pixels):
            return pixels
        await asyncio.sleep(0.25)
        await frames(20)
    prim = viewport.stage.GetPrimAtPath(viewport.render_product_path)
    raise AssertionError(
        (
            name,
            pixels,
            prim.GetAttribute(PLANE_ATTR).Get(),
            prim.GetAttribute("omni:rtx:scene:sectionPlane:enabled").Get(),
        )
    )


def verify_selection_fit(window, state, stage):
    selection = omni.usd.get_context().get_selection()
    parent = UsdGeom.Xform.Define(stage, "/FitTest")
    parent.AddTranslateOp().Set(Gf.Vec3d(30, 40, -20))
    parent.AddRotateZOp().Set(35)
    child = UsdGeom.Cube.Define(stage, "/FitTest/Child")
    child.AddTranslateOp().Set(Gf.Vec3d(7, -5, 2))
    child.AddRotateYOp().Set(23)
    child.AddScaleOp().Set(Gf.Vec3f(2, 3, 4))
    selection.set_selected_prim_paths([str(child.GetPath())], False)
    window._on_fit_to_selection()
    fitted = state.box
    selected_paths = selection.get_selected_prim_paths()
    assert fit_box_to_paths(stage, selected_paths) == fitted
    assert fit_box_to_paths(stage, ["/Cube"]) is not None
    assert selection.get_selected_prim_paths() == selected_paths, "Explicit fit changed active selection"
    assert state.box == fitted, "Calculating an explicit fit changed the active box"
    world = UsdGeom.XformCache().GetLocalToWorldTransform(child.GetPrim())
    corners = [world.Transform(Gf.Vec3d(x, y, z)) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    _selection_checks.check_optimal_footprint(fitted, corners)
    assert Gf.IsClose(fitted.transform.ExtractTranslation(), world.Transform(Gf.Vec3d(0)), 1e-6)
    assert fitted.faces == frozenset(Face)
    assert state.enabled

    sibling = UsdGeom.Cube.Define(stage, "/FitTest/Sibling")
    sibling.AddTranslateOp().Set(Gf.Vec3d(-10, 8, 6))
    paths = [str(child.GetPath()), str(sibling.GetPath())]
    selection.set_selected_prim_paths(paths, False)
    window._on_fit_to_selection()
    fitted = state.box
    world_corners = []
    for prim in (child.GetPrim(), sibling.GetPrim()):
        world = UsdGeom.XformCache().GetLocalToWorldTransform(prim)
        for x in (-1, 1):
            for y in (-1, 1):
                for z in (-1, 1):
                    corner = world.Transform(Gf.Vec3d(x, y, z))
                    world_corners.append(corner)
    _selection_checks.check_optimal_footprint(fitted, world_corners)
    selection.set_selected_prim_paths(list(reversed(paths)), False)
    window._on_fit_to_selection()
    assert state.box == fitted

    selection.set_selected_prim_paths(["/FitTest/Child", "/Cube"], False)
    window._on_fit_to_selection()
    world_corners = []
    for path in ("/FitTest/Child", "/Cube"):
        world = UsdGeom.XformCache().GetLocalToWorldTransform(stage.GetPrimAtPath(path))
        world_corners.extend(world.Transform(Gf.Vec3d(x, y, z)) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1))
    _selection_checks.check_optimal_footprint(state.box, world_corners)
    fitted = state.box
    selection.set_selected_prim_paths([], False)
    window._on_fit_to_selection()
    assert state.box == fitted
    stage.RemovePrim("/FitTest")

    mesh = _selection_checks.rectangle(stage, "/GeometryFit/Mesh")
    state.enabled = False
    before_fit = state.box
    before_root = stage.GetRootLayer().ExportToString()
    selection.set_selected_prim_paths(["/GeometryFit"], False)
    window._on_fit_to_selection()
    fitted = state.box
    _selection_checks.check_box(
        fitted, _selection_checks.world_points(mesh), (40, 10, 6), _selection_checks.rotation(31)
    )
    assert state.enabled and fitted.faces == frozenset(Face)
    assert stage.GetRootLayer().ExportToString() == before_root
    omni.kit.undo.undo()
    assert state.box == before_fit and not state.enabled
    omni.kit.undo.redo()
    assert state.box == fitted and state.enabled
    selection.set_selected_prim_paths([], False)
    stage.RemovePrim("/GeometryFit")


def verify_rotation_slider(window, state):
    model = window._rotation_slider.model
    fitted_axis = state.box.transform.TransformDir(Gf.Vec3d(1, 0, 0))
    assert abs(model.as_float - math.degrees(math.atan2(fitted_axis[1], fitted_axis[0]))) < 1e-4
    original = SectionBox(size=Gf.Vec3d(7, 11, 13), faces=frozenset({Face.MIN_X, Face.MAX_Z}))
    original = original.rotated(2, 17).translated(Gf.Vec3d(100, 200, 30))
    state.box = original
    state.enabled = False
    window._on_rotate(30)
    expected = Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0, 0, 1), 30))
    assert Gf.IsClose(state.box.transform.ExtractRotationMatrix(), expected.ExtractRotationMatrix(), 1e-8)
    first = state.box
    window._on_rotate(30)
    assert state.box == first, "The same displayed angle accumulated rotation"
    assert state.box.size == original.size and state.box.faces == original.faces
    assert state.box.transform.ExtractTranslation() == original.transform.ExtractTranslation()
    assert not state.enabled

    state.box = original
    assert abs(model.as_float - 17) < 1e-4
    undo_count = len(omni.kit.undo.get_undo_stack())
    # Native UI emits edit subscriptions separately from model.begin_edit().
    state.begin_edit()
    model.set_value(25)
    model.set_value(40)
    model.set_value(65)
    state.end_edit()
    assert len(omni.kit.undo.get_undo_stack()) == undo_count + 1
    final = state.box
    expected.SetRotate(Gf.Rotation(Gf.Vec3d(0, 0, 1), 65))
    assert Gf.IsClose(final.transform.ExtractRotationMatrix(), expected.ExtractRotationMatrix(), 1e-8)
    omni.kit.undo.undo()
    assert state.box == original and abs(model.as_float - 17) < 1e-4, (state.box, original, model.as_float)
    omni.kit.undo.redo()
    assert state.box == final and abs(model.as_float - 65) < 1e-4
    state.reset()
    assert abs(model.as_float) < 1e-4


async def verify():
    OUTPUT.mkdir(exist_ok=True)
    checks = []
    extension = None
    try:
        # Test the actual startup/shutdown methods with a retained instance.
        manager = APP.get_extension_manager()
        manager.set_extension_enabled_immediate("section.box", False)
        settings = carb.settings.get_settings()
        settings.set("/persistent/exts/section.box/enabled", False)
        settings.set("/persistent/exts/section.box/persistToStage", False)
        await omni.usd.get_context().new_stage_async()
        stage = omni.usd.get_context().get_stage()
        cube = UsdGeom.Cube.Define(stage, "/Cube")
        cube.AddTranslateOp().Set(Gf.Vec3d(100, 0, 0))
        extension = SectionBoxExtension()
        extension.on_startup("section.box")
        await frames(30)
        state = extension._state
        assert get_runtime_state() is state
        assert extension._scene_items
        assert extension._manipulator._root is not None
        selection_layer = vp_util.get_active_viewport_window()._find_viewport_layer("Selection", "manipulator")
        selection_manipulator = selection_layer.layer._SelectionManipulatorItem__manipulator
        assert extension._manipulator.scene_view is selection_manipulator.scene_view
        camera_layer = vp_util.get_active_viewport_window()._find_viewport_layer("Camera", "manipulator")
        assert extension._manipulator.scene_view is camera_layer.layer.manipulator.scene_view
        selection_drag = next(
            gesture
            for gesture in selection_manipulator._GestureBindingManipulator__gestures
            if type(gesture).__name__ == "SelectionDragGesture"
        )
        arrow_drag = extension._manipulator._face_gestures[Face.MAX_X][0]
        assert selection_drag.manager.should_prevent(selection_drag, arrow_drag)
        checks.append("startup places section grips alongside viewport camera and selection gestures")

        omni.usd.get_context().get_selection().set_selected_prim_paths(["/Cube"], False)
        extension._window._on_fit_to_selection()
        assert state.box.transform.ExtractTranslation() == Gf.Vec3d(100, 0, 0)
        assert Gf.IsClose(state.box.size, Gf.Vec3d(2, 2, 2), 1e-6)
        checks.append("fit to selection uses transformed world bounds")

        original = SectionBox(size=Gf.Vec3d(7, 11, 13), faces=frozenset({Face.MIN_X, Face.MAX_Z})).rotated(2, 31)
        state.enabled = False
        state.box = original
        extension._window._on_center_on_selection()
        assert state.box.transform.ExtractTranslation() == Gf.Vec3d(100, 0, 0)
        assert state.box.transform.ExtractRotationMatrix() == original.transform.ExtractRotationMatrix()
        assert state.box.size == original.size and state.box.faces == original.faces
        assert not state.enabled
        other = UsdGeom.Cube.Define(stage, "/Other")
        other.AddTranslateOp().Set(Gf.Vec3d(200, 40, -20))
        selection = omni.usd.get_context().get_selection()
        selection.set_selected_prim_paths(["/Cube", "/Other"], False)
        extension._window._on_center_on_selection()
        assert state.box.transform.ExtractTranslation() == Gf.Vec3d(150, 20, -10)
        assert state.box.size == original.size and state.box.faces == original.faces
        centered = state.box
        selection.set_selected_prim_paths([], False)
        extension._window._on_center_on_selection()
        assert state.box == centered
        stage.RemovePrim("/Other")
        checks.append(
            "center on selection moves to single or combined bounds, preserves box settings, and ignores empty selection"
        )

        verify_selection_fit(extension._window, state, stage)
        verify_rotation_slider(extension._window, state)
        checks.append(
            "rotation slider sets an absolute Z angle, follows external changes, and groups a drag into one undo"
        )
        checks.extend(_selection_checks.verify_selection())
        checks.append(
            "fit keeps world-XY faces for tilted and baked geometry, supports undo/redo, and leaves scene geometry unchanged"
        )

        state.box = SectionBox()
        state.enabled = True
        await frames(10)
        viewport = vp_util.get_active_viewport()
        attr = stage.GetPrimAtPath(viewport.render_product_path).GetAttribute(PLANE_ATTR)
        expected = [1, 0, 0, 50, -1, 0, 0, 50, 0, 1, 0, 50, 0, -1, 0, 50, 0, 0, 1, 50, 0, 0, -1, 50]
        assert list(attr.Get()) == expected, attr.Get()
        root_before = stage.GetRootLayer().ExportToString()
        state.box = state.box.rotated(1, 23).translated(Gf.Vec3d(3, 7, -2))
        assert len(attr.Get()) == 24
        assert stage.GetRootLayer().ExportToString() == root_before
        checks.append("all six planes reach RTX and leave the root layer unchanged")

        handles = dict(extension._manipulator._handles)
        notifications = []
        state.add_listener(lambda s: notifications.append(s.box))
        manipulator = extension._manipulator
        with patch.object(manipulator, "_update_geometry", wraps=manipulator._update_geometry) as refresh:
            state.set_face(Face.MAX_Z, False)
            assert refresh.call_count == 1, f"One state edit triggered {refresh.call_count} geometry refreshes"
        assert len(notifications) == 1
        assert Face.MAX_Z not in state.box.faces
        assert not manipulator._faces[Face.MAX_Z].visible
        assert not extension._window._face_checkboxes[Face.MAX_Z].model.as_bool
        assert len(attr.Get()) == 20
        with patch.object(manipulator, "_update_geometry", wraps=manipulator._update_geometry) as refresh:
            extension._window._face_checkboxes[Face.MAX_Z].model.set_value(True)
            assert refresh.call_count == 1, f"One control edit triggered {refresh.call_count} geometry refreshes"
        assert Face.MAX_Z in state.box.faces
        assert manipulator._faces[Face.MAX_Z].visible
        assert len(attr.Get()) == 24
        assert handles == extension._manipulator._handles
        checks.append("state and face-control edits refresh geometry once and keep drag handles alive")

        for face in Face:
            state.edit(box=SectionBox(faces=frozenset({face})).rotated(1, 23).translated(Gf.Vec3d(3, 7, -2)))
            assert {f for f, mesh in manipulator._faces.items() if mesh.visible} == {face}
            assert {f for f, handle in manipulator._handles.items() if handle.visible} == {face}
            assert {f for f, (_, tip) in manipulator._arrows.items() if tip.visible} == {face}
            shaft, tip = manipulator._arrows[face]
            outward = state.box.transform.TransformDir(AXIS_VECTORS[face.axis] * face.sign)
            plane_center = state.box.transform.Transform(AXIS_VECTORS[face.axis] * face.sign * 50)
            assert Gf.IsClose(Gf.Vec3d(*shaft.start), plane_center, 1e-4)
            assert Gf.Dot(Gf.Vec3d(*tip.positions[4]) - plane_center, outward) > 0
            outline = [line for line in manipulator._lines if line.visible]
            assert len(outline) == 4
            inverse = state.box.transform.GetInverse()
            for line in outline:
                for endpoint in (line.start, line.end):
                    local = inverse.Transform(Gf.Vec3d(*endpoint))
                    assert abs(local[face.axis] - face.sign * 50) < 1e-4
            extension._window._face_checkboxes[face].model.set_value(False)
            assert not any(line.visible for line in manipulator._lines)
            assert not any(handle.visible for handle in manipulator._handles.values())
            assert not any(mesh.visible for mesh in manipulator._faces.values())
            assert not any(tip.visible for _, tip in manipulator._arrows.values())
            assert manipulator._center.visible and manipulator._root.visible
            omni.kit.undo.undo()
            assert manipulator._faces[face].visible and manipulator._handles[face].visible
            assert sum(line.visible for line in manipulator._lines) == 4
        for faces, edge_count in (({Face.MIN_X, Face.MIN_Y}, 7), ({Face.MIN_X, Face.MAX_X}, 8), (set(Face), 12)):
            state.edit(box=SectionBox(faces=frozenset(faces)))
            assert sum(line.visible for line in manipulator._lines) == edge_count
        assert handles == manipulator._handles
        checks.append("only active faces show fills, outlines, and resize handles, including after undo")

        state.enabled = False
        assert not settings.get("/rtx/sectionPlane/enabled")
        assert len(attr.Get()) != 24
        extension._toolbar._model.set_value(True)
        assert state.enabled and extension._window.visible
        state.enabled = False
        assert not extension._toolbar._model.as_bool
        checks.append("disable clears clipping and toolbar state stays synchronized")

        state.enabled = True
        clipping_before = list(attr.Get())
        extension._window._show_checkbox.model.set_value(False)
        assert not extension._manipulator._root.visible
        assert state.enabled and list(attr.Get()) == clipping_before
        omni.kit.undo.undo()
        assert state.show_box and extension._manipulator._root.visible
        state.enabled = False
        checks.append("Show Box hides only the overlay and can be undone without changing clipping")

        stage.RemovePrim("/Cube")
        camera = UsdGeom.Camera.Define(stage, "/Camera")
        camera.AddTransformOp().Set(
            Gf.Matrix4d().SetLookAt(Gf.Vec3d(330, 280, 380), Gf.Vec3d(0, 0, 0), Gf.Vec3d(0, 1, 0)).GetInverse()
        )
        viewport.camera_path = camera.GetPath()
        viewport.resolution = (800, 600)
        light = UsdLux.DomeLight.Define(stage, "/Light")
        light.CreateIntensityAttr(1000)
        # The center cube must survive; one probe beyond each face must disappear.
        points = [(0, 0, 0), (-80, 0, 0), (80, 0, 0), (0, -80, 0), (0, 80, 0), (0, 0, -80), (0, 0, 80)]
        for index, point in enumerate(points):
            probe = UsdGeom.Cube.Define(stage, f"/Probe{index}")
            probe.CreateSizeAttr(22)
            probe.AddTranslateOp().Set(Gf.Vec3d(*point))
            probe.CreateDisplayColorAttr([Gf.Vec3f(0.1, 0.8, 0.3) if index == 0 else Gf.Vec3f(0.9, 0.3, 0.1)])
        state.box = SectionBox()
        await frames(90)
        baseline = await capture(viewport, "unclipped.png")
        state.enabled = True
        await frames(40)
        clipped = await capture_when(viewport, "six_faces.png", lambda p: p[0] > 100 and p[1] == 0)
        assert baseline[0] > 100 and baseline[1] > 100, baseline
        assert clipped[0] > 100 and clipped[1] == 0, clipped
        for face in Face:
            state.set_face(face, False)
            assert len(attr.Get()) == 20, (face, state.box.faces, attr.Get())
            await frames(40)
            green, orange = await capture_when(
                viewport, f"without_{face.name}.png", lambda p: p[0] > 100 and p[1] > 100
            )
            assert green > 100 and orange > 100, (face, green, orange)
            state.set_face(face, True)
        checks.append(
            "RTX images retain the center, clip all outside probes, and restore each probe when its face is disabled"
        )

        first_window = vp_util.get_active_viewport_window()
        other_window = vp_util.create_viewport_window("Unclipped overview", width=400, height=300)
        from omni.kit.viewport.window import ViewportWindow

        try:
            other_viewport = other_window.viewport_api
            other_viewport.camera_path = viewport.camera_path
            other_viewport.resolution = (800, 600)
            await frames(10)
            # Headless windows do not receive OS focus events.
            ViewportWindow.active_window = first_window
            await frames(50)
            assert vp_util.get_active_viewport() == viewport, (
                ViewportWindow.active_window.title,
                vp_util.get_active_viewport_window().title,
                first_window.title,
            )
            other_prim = stage.GetPrimAtPath(other_viewport.render_product_path)
            assert not other_prim.GetAttribute("omni:rtx:scene:sectionPlane:enabled").Get()
            overview = await capture_when(other_viewport, "overview_unclipped.png", lambda p: p[0] > 100 and p[1] > 100)
            assert overview[0] > 100 and overview[1] > 100, overview
            ViewportWindow.active_window = weakref.proxy(other_window)
            await frames(50)
            assert vp_util.get_active_viewport() == other_viewport
            assert (
                not stage.GetPrimAtPath(viewport.render_product_path)
                .GetAttribute("omni:rtx:scene:sectionPlane:enabled")
                .Get()
            )
            moved_clip = await capture_when(
                other_viewport, "other_viewport_clipped.png", lambda p: p[0] > 100 and p[1] == 0
            )
            assert moved_clip[0] > 100 and moved_clip[1] == 0, moved_clip
        finally:
            ViewportWindow.active_window = first_window
            other_window.destroy()
            await frames(20)
        checks.append("two real viewports keep the overview unclipped and move clipping with focus")

        await _position_checks.verify_saved_positions(extension, OUTPUT)
        checks.append(
            "named saved-box controls create, load, update, and delete independent snapshots that survive scene reopening"
        )

        await omni.usd.get_context().new_stage_async()
        await frames(30)
        new_stage = omni.usd.get_context().get_stage()
        assert not state.enabled
        assert (
            not new_stage.GetPrimAtPath(viewport.render_product_path)
            .GetAttribute("omni:rtx:scene:sectionPlane:enabled")
            .Get()
        )
        checks.append("a newly opened scene starts unclipped")

        extension.on_shutdown()
        extension = None
        assert get_runtime_state() is None
        assert not settings.get("/rtx/sectionPlane/enabled")
        checks.append("shutdown removes section grips, toolbar group, and clipping")
        extension = SectionBoxExtension()
        extension.on_startup("section.box")
        await frames(10)
        assert not extension._state.enabled
        assert get_runtime_state() is extension._state
        extension.on_shutdown()
        extension = None
        assert get_runtime_state() is None
        checks.append("extension restart starts unclipped")
        spec = importlib.util.spec_from_file_location("verify_gestures", Path(__file__).with_name("verify_gestures.py"))
        gestures = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gestures)
        await gestures.verify_gestures()
        checks.append("Scene UI mouse rays translate and resize the box by the expected world distance")
        (OUTPUT / "kit-results.json").write_text(json.dumps({"passed": checks}, indent=2))
        print("SECTION_BOX_VERIFICATION_PASSED", json.dumps(checks))
        APP.post_quit(0)
    except Exception:
        error = traceback.format_exc()
        print(error)
        (OUTPUT / "kit-results.json").write_text(json.dumps({"passed": checks, "error": error}, indent=2))
        try:
            if extension:
                extension.on_shutdown()
        finally:
            APP.post_quit(1)


asyncio.ensure_future(verify())
